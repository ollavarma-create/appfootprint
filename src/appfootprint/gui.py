"""Qt interface for read-only Flatpak storage inventory."""
from __future__ import annotations

import sys
from threading import Event

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QLabel, QMenu,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .extensions import compatible_extension, parse_extension_points
from .scanner import Item, ScanCancelled, allocated_size, direct_runtime_users, runtime_extension_hint, format_size, scan
from .advisor import assess_path, space_significance


def total_bytes(item: Item) -> int | None:
    """Known app-specific bytes only; shared runtimes are excluded."""
    values = (item.allocated_bytes, item.user_data_bytes)
    if all(value is None for value in values):
        return None
    return sum(value or 0 for value in values)


class SizeCell(QTableWidgetItem):
    """Numeric sorting rather than lexicographic sorting of formatted sizes."""

    def __init__(self, value: int | None):
        super().__init__(format_size(value))
        self.value = value
        self.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.setData(Qt.ItemDataRole.UserRole, value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SizeCell):
            return (self.value if self.value is not None else -1) < (
                other.value if other.value is not None else -1
            )
        return super().__lt__(other)


class ScanThread(QThread):
    progress_changed = Signal(str)
    finished_scan = Signal(object, object)
    scan_cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cancel = Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            items, issues = scan(progress=self.progress_changed.emit,
                                 cancelled=self._cancel.is_set)
        except ScanCancelled:
            self.scan_cancelled.emit()
            return
        except Exception as exc:
            items, issues = [], [f"Scan failed: {exc}"]
        self.finished_scan.emit(items, issues)


class DirectoryTreeItem(QTreeWidgetItem):
    """Compare numeric allocated sizes when sorting the size column."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        if tree is not None and tree.sortColumn() == 1:
            a = self.data(1, Qt.ItemDataRole.UserRole)
            b = other.data(1, Qt.ItemDataRole.UserRole)
            return (a if a is not None else -1) < (b if b is not None else -1)
        return super().__lt__(other)


def directory_item(name: str, path: str, size: int | None) -> DirectoryTreeItem:
    node = DirectoryTreeItem([name, format_size(size)])
    node.setData(0, Qt.ItemDataRole.UserRole, path)
    node.setData(1, Qt.ItemDataRole.UserRole, size)
    return node


class DirectorySignals(QObject):
    ready = Signal(object, object, object)


class DirectoryJob(QRunnable):
    """Measure one directory level off the GUI thread."""

    def __init__(self, path: Path, sizes: dict[str, int | None]):
        super().__init__()
        self.path = path
        self.sizes = sizes
        self.signals = DirectorySignals()

    def run(self) -> None:
        children: list[tuple[str, int | None, bool]] = []
        error = ""
        try:
            # Never traverse a symlink, even if it points to a directory.
            if self.path.is_symlink():
                raise OSError("Symlink directories are not traversed")
            for child in sorted(self.path.iterdir(), key=lambda p: p.name):
                if child.is_symlink():
                    continue
                try:
                    is_dir = child.is_dir()
                    children.append((child.name, self.sizes[str(child)] if str(child) in self.sizes
                                     else allocated_size(child), is_dir))
                except OSError:
                    children.append((child.name, None, False))
        except OSError as exc:
            error = str(exc)
        self.signals.ready.emit(str(self.path), children, error)


class DetailDialog(QDialog):
    """Explore user data by expanding directories on background workers."""

    def __init__(self, item: Item, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Storage explorer — {item.app_id}")
        self.resize(900, 550)
        self._pending: set[str] = set()
        self._jobs: dict[str, DirectoryJob] = {}
        self._size_cache: dict[str, int | None] = {}
        self._directory_cache: dict[str, list[tuple[str, int | None, bool]]] = {}
        layout = QVBoxLayout(self)
        description = QLabel(
            f"Installed: {format_size(item.allocated_bytes)} | "
            f"User data: {format_size(item.user_data_bytes)} | "
            f"Runtime (shared, not included): {item.runtime or 'Unknown'}"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["User data location", "Allocated"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(1, Qt.SortOrder.DescendingOrder)
        self.tree.setColumnWidth(0, 660)
        self.tree.itemExpanded.connect(self.expand_directory)
        self.tree.currentItemChanged.connect(self.show_advice)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_path_menu)
        layout.addWidget(self.tree)

        self.data_root = Path(item.user_data_path)
        root_path = self.data_root
        if root_path.is_dir() and not root_path.is_symlink():
            root = directory_item(str(root_path), str(root_path), item.user_data_bytes)
            self._size_cache[str(root_path)] = item.user_data_bytes
            self.tree.addTopLevelItem(root)
            # The first level was already measured during the main scan.
            for name, size in sorted(
                item.user_data_breakdown,
                key=lambda pair: pair[1] if pair[1] is not None else -1,
                reverse=True,
            ):
                path = root_path / name
                if path.is_symlink():
                    continue
                child = directory_item(name, str(path), size)
                self._size_cache[str(path)] = size
                root.addChild(child)
                if path.is_dir():
                    child.addChild(QTreeWidgetItem(["Expand to scan…", ""]))
            root.setExpanded(True)
        else:
            layout.addWidget(QLabel("No accessible user-data directory."))

        self.status = QLabel(
            "Expand a folder to measure its contents. Measurements run in "
            "the background; symlinks are skipped. No files are modified."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.advice = QLabel(
            "Cleanup Advisor (read-only): Select a path to see a conservative assessment."
        )
        self.advice.setWordWrap(True)
        self.advice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.advice)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def show_advice(self, node: QTreeWidgetItem | None, _previous) -> None:
        if node is None:
            return
        path = node.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, str):
            return
        result = assess_path(self.data_root, Path(path))
        size = node.data(1, Qt.ItemDataRole.UserRole)
        significance = space_significance(size if isinstance(size, int) else None)
        self.advice.setText(
            f"Cleanup Advisor — {result.category} ({result.confidence})\n"
            f"Why: {result.explanation}\n"
            f"Consequence: {result.consequence}\n"
            f"Space: {significance} (allocated size, not guaranteed reclaimable)\n"
            f"Guidance: {result.action} No files are modified."
        )

    def show_path_menu(self, position) -> None:
        """Only offer navigation for real entries, never placeholder rows."""
        node = self.tree.itemAt(position)
        if node is None:
            return
        path = node.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return
        target = Path(path)
        directory = target if target.is_dir() else target.parent
        menu = QMenu(self.tree)
        copy_action = menu.addAction("Copy path")
        folder_action = menu.addAction("Copy containing folder path")
        open_action = menu.addAction("Open in file manager")
        selected = menu.exec(self.tree.viewport().mapToGlobal(position))
        if selected == copy_action:
            QApplication.clipboard().setText(path)
            self.status.setText(f"Copied path: {path}")
        elif selected == folder_action:
            QApplication.clipboard().setText(str(directory))
            self.status.setText(f"Copied folder path: {directory}")
        elif selected == open_action:
            # Open the parent of files, never execute them.
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
                self.status.setText(f"Could not open file manager: {directory}")

    def expand_directory(self, node: QTreeWidgetItem) -> None:
        path = node.data(0, Qt.ItemDataRole.UserRole)
        if not path or path in self._pending or node.childCount() != 1:
            return
        if node.child(0).data(0, Qt.ItemDataRole.UserRole) is not None:
            return  # Already populated with actual children.
        if path in self._directory_cache:
            self.populate_directory(node, path, self._directory_cache[path])
            self.status.setText(f"Loaded cached results for {path}. Read-only.")
            return
        node.child(0).setText(0, "Scanning…")
        self._pending.add(path)
        self.status.setText(f"Scanning {path}…")
        job = DirectoryJob(Path(path), dict(self._size_cache))
        self._jobs[path] = job
        job.signals.ready.connect(self.directory_ready)
        QThreadPool.globalInstance().start(job)

    def populate_directory(
        self, node: QTreeWidgetItem, path: str,
        children: list[tuple[str, int | None, bool]],
    ) -> None:
        self.tree.setSortingEnabled(False)
        node.takeChildren()
        for name, size, is_dir in children:
            child_path = str(Path(path) / name)
            child = directory_item(name, child_path, size)
            node.addChild(child)
            if is_dir:
                child.addChild(QTreeWidgetItem(["Expand to scan…", ""]))
        self.tree.setSortingEnabled(True)

    def directory_ready(self, path: str, children: list, error: str) -> None:
        self._pending.discard(path)
        self._jobs.pop(path, None)
        if not error:
            self._directory_cache[path] = children
            for name, size, _is_dir in children:
                self._size_cache[str(Path(path) / name)] = size
        nodes = self.tree.findItems(
            "*", Qt.MatchFlag.MatchWildcard | Qt.MatchFlag.MatchRecursive, 0
        )
        for node in nodes:
            if node.data(0, Qt.ItemDataRole.UserRole) != path:
                continue
            if error:
                node.takeChildren()
                node.addChild(QTreeWidgetItem(["Scan failed — collapse and retry", ""]))
            else:
                self.populate_directory(node, path, children)
            break
        self.status.setText(
            f"Could not scan {path}: {error}" if error
            else f"Scanned {path} ({len(children)} entries). Read-only."
        )


class RuntimeDialog(QDialog):
    """Explain shared Flatpak runtimes without attributing them to one app."""

    def __init__(self, item: Item, items: list[Item], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Shared runtime — {item.app_id}")
        self.resize(760, 480)
        layout = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        details = (
            f"Runtime: {item.app_id}\n"
            f"Ref: {item.ref}\n"
            f"Installation: {item.installation}\n"
            f"Measured deployment: {format_size(item.allocated_bytes)}\n"
            f"Location: {item.location or 'Unknown'}"
        )
        info = QLabel(details)
        info.setWordWrap(True)
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_layout.addWidget(info)
        explanation = QLabel(
            "A Flatpak runtime provides shared libraries and components used "
            "by applications. It does not have an application-specific user-data "
            "tree, so the Storage Explorer cannot open it as an app.\n\n"
            "Its measured deployment size is not necessarily unique physical "
            "disk usage or the space you would recover by removing it. "
            "Do not remove runtime files manually. Flatpak manages runtime "
            "dependencies and unused installations."
        )
        explanation.setWordWrap(True)
        content_layout.addWidget(explanation)
        extension_hint = runtime_extension_hint(item)
        if extension_hint:
            extension_heading = QLabel("Runtime extension — usage not verified")
            heading_font = extension_heading.font()
            heading_font.setBold(True)
            heading_font.setPointSize(heading_font.pointSize() + 1)
            extension_heading.setFont(heading_font)
            content_layout.addWidget(extension_heading)
            extension_details = QLabel(extension_hint)
            extension_details.setWordWrap(True)
            content_layout.addWidget(extension_details)

        tree = QTreeWidget()
        tree.setHeaderLabels(["Dependency / component", "Relationship"])
        tree.setRootIsDecorated(True)
        tree.setAlternatingRowColors(True)
        tree.setMinimumHeight(240)
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        content_layout.addWidget(tree)

        users = direct_runtime_users(item, items)
        apps_root = QTreeWidgetItem(
            tree, [f"Direct applications ({len(users)})", "Declared primary runtime"]
        )
        for app in users:
            QTreeWidgetItem(
                apps_root, [f"{app.app_id} ({app.installation})", "Direct"]
            )
        if not users:
            QTreeWidgetItem(
                apps_root, ["No primary-runtime matches found", "Not proof of non-use"]
            )

        # Inspect both directions. A match means metadata compatibility only.
        extension_rows = []
        platform_rows = []
        for platform in items:
            if platform.kind != "runtime" or not platform.metadata:
                continue
            try:
                points = parse_extension_points(platform.metadata)
            except ValueError:
                continue
            for point in points:
                if item is platform:
                    for extension in items:
                        if extension is platform or extension.kind != "runtime":
                            continue
                        if compatible_extension(point, extension.ref, platform.ref):
                            extension_rows.append((extension.ref, point))
                elif compatible_extension(point, item.ref, platform.ref):
                    platform_rows.append((platform, point))

        if extension_rows or (item.metadata and not platform_rows):
            distinct = list(dict.fromkeys(
                (ref, point.name, point.conditions)
                for ref, point in extension_rows
            ))
            ext_root = QTreeWidgetItem(
                tree, [f"Compatible installed extensions ({len(distinct)})",
                       "Metadata compatibility"]
            )
            for ref, point_name, conditions in distinct:
                node = QTreeWidgetItem(ext_root, [ref, point_name])
                for condition in conditions:
                    QTreeWidgetItem(node, [condition, "Activation condition"])
        else:
            distinct_platforms = list(dict.fromkeys(
                (platform.ref, point.name, point.conditions)
                for platform, point in platform_rows
            ))
            platforms_root = QTreeWidgetItem(
                tree, [f"Compatible platforms ({len(distinct_platforms)})",
                       "Metadata compatibility"]
            )
            for platform_ref, point_name, conditions in distinct_platforms:
                node = QTreeWidgetItem(platforms_root, [platform_ref, point_name])
                for condition in conditions:
                    QTreeWidgetItem(node, [condition, "Activation condition"])
                platform = next(
                    p for p, _ in platform_rows if p.ref == platform_ref
                )
                possible = direct_runtime_users(platform, items)
                apps = QTreeWidgetItem(
                    node, [f"Potential applications ({len(possible)})",
                           "Via primary platform"]
                )
                for app in possible:
                    QTreeWidgetItem(
                        apps, [f"{app.app_id} ({app.installation})",
                               "Potential, not verified"]
                    )

        apps_root.setExpanded(True)
        for i in range(tree.topLevelItemCount()):
            tree.topLevelItem(i).setExpanded(True)
        tree.header().setStretchLastSection(False)
        tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        legend = QLabel(
            "Direct = application-declared primary runtime. "
            "Compatible = metadata-based possibility, not verified activation. "
            "A missing match does not prove a runtime is unused. "
            "Installed size is not guaranteed reclaimable."
        )
        legend.setWordWrap(True)
        content_layout.addWidget(legend)
        if item.errors:
            errors = QLabel("Scan issues: " + "; ".join(item.errors))
            errors.setWordWrap(True)
            content_layout.addWidget(errors)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AppFootprint — Flatpak inventory (alpha)")
        self.resize(1200, 650)
        self.items: list[Item] = []
        container = QWidget()
        layout = QVBoxLayout(container)
        self.info = QLabel(
            "Read-only inventory. Totals exclude shared runtimes. "
            "Double-click an application to explore user data, or a runtime for an explanation."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.button = QPushButton("Scan Flatpak installations")
        self.button.clicked.connect(self.start_scan)
        layout.addWidget(self.button)
        self.cancel_button = QPushButton("Cancel scan")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Busy indicator: scan size is unknown.
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Flatpak scan in progress")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Kind", "Application ID", "Ref / version", "Installation",
            "Installed", "User data", "App total", "Runtime", "Path / errors",
        ])
        # Use the active KDE/Qt palette rather than fixed yellow/green colors.
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self.show_detail)
        layout.addWidget(self.table)
        self.setCentralWidget(container)
        self.worker: ScanThread | None = None

    def start_scan(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.button.setEnabled(False)
        self.button.setText("Scanning…")
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self.info.setText("Scanning Flatpak applications and user data… (read-only)")
        self.worker = ScanThread(self)
        self.worker.progress_changed.connect(self.show_progress)
        self.worker.finished_scan.connect(self.show_results)
        self.worker.scan_cancelled.connect(self.scan_was_cancelled)
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def cancel_scan(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.info.setText("Cancelling scan… waiting for current operation.")

    def scan_was_cancelled(self) -> None:
        # Keep the last completed results rather than showing partial data.
        self.info.setText("Scan cancelled. Previous results retained; no files modified.")

    def show_progress(self, message: str) -> None:
        if self.worker and not self.worker._cancel.is_set():
            self.info.setText(message + " (read-only)")

    def finish_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        self.button.setText("Scan Flatpak installations")
        self.button.setEnabled(True)

    def show_results(self, items: list[Item], issues: list[str]) -> None:
        self.items = items
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.kind, item.app_id, item.ref, item.installation,
                item.allocated_bytes,
                item.user_data_bytes if item.kind == "app" else None,
                total_bytes(item) if item.kind == "app" else None,
                item.runtime if item.kind == "app" else "—",
                item.location + (" | " if item.location and item.errors else "")
                + "; ".join(item.errors),
            ]
            for col, value in enumerate(values):
                cell = SizeCell(value) if col in (4, 5, 6) else QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole + 1, row)
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)
        summary = (
            f"{len(items)} Flatpak records. App total = installed + user data; "
            "shared runtimes excluded. No files modified."
        )
        if issues:
            summary += " Issues: " + "; ".join(issues)
        self.info.setText(summary)

    def show_detail(self, row: int, _column: int) -> None:
        cell = self.table.item(row, 0)
        if cell is None:
            return
        original_index = cell.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(original_index, int):
            return
        item = self.items[original_index]
        if item.kind == "runtime":
            dialog = RuntimeDialog(item, self.items, self)
        elif item.kind == "app":
            dialog = DetailDialog(item, self)
        else:
            return
        dialog.exec()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
