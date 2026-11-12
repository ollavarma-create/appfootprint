"""Qt interface for read-only Flatpak storage inventory."""
from __future__ import annotations

import sys
from threading import Event

from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QColor, QBrush
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QLabel, QMenu,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QHBoxLayout, QComboBox, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .extensions import compatible_extension, parse_extension_points
from .navigation import NavigationHistory, history_labels
from .scanner import Item, ScanCancelled, allocated_size, direct_runtime_users, runtime_extension_hint, format_size, scan
from .advisor import assess_path, space_significance
from .provider_detection import ProviderStatus, detect_providers
from .providers.snap import SnapProvider
from .unified import combine
from .providers.snap_storage import scan_storage
from .inventory import StorageRole, MeasurementStatus


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


class ProviderProbeThread(QThread):
    """Check CLI availability without blocking Qt's event loop."""
    detected = Signal(object)

    def run(self) -> None:
        try:
            statuses = detect_providers()
        except Exception as exc:
            statuses = {"flatpak": ProviderStatus(
                "flatpak", False, f"Provider detection failed: {exc}"
            )}
        self.detected.emit(statuses)


class SnapScanThread(QThread):
    progress_changed = Signal(str)
    finished_scan = Signal(object, object, object)
    scan_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            records, issues = SnapProvider().scan(
                progress=self.progress_changed.emit, cancelled=self._cancel.is_set)
            self.progress_changed.emit('Measuring Snap cache and snapshots…')
            storage = scan_storage(cancelled=self._cancel.is_set)
        except ScanCancelled:
            self.scan_cancelled.emit()
            return
        except Exception as exc:
            records, issues, storage = [], [f"Snap scan failed: {exc}"], None
        self.finished_scan.emit(records, issues, storage)


class SnapInventoryDialog(QDialog):
    """Read-only revision inventory. Never count mounted squashfs contents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AppFootprint — Snap inventory")
        self.resize(1050, 540)
        self.records = []
        layout = QVBoxLayout(self)
        self.status = QLabel("Ready to scan Snap revisions (read-only).")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.storage_summary = QLabel("Package-manager storage: not measured yet.")
        self.storage_summary.setWordWrap(True)
        layout.addWidget(self.storage_summary)
        self.coverage = QLabel("Measurement coverage: not assessed yet.")
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)
        self.scan_button = QPushButton("Scan Snap installations")
        self.scan_button.clicked.connect(self.start_scan)
        layout.addWidget(self.scan_button)
        self.cancel_button = QPushButton("Cancel Snap scan")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Kind", "Snap / revision", "State", "Version",
            "Compressed image", "User data", "Path / status",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.worker = None

    def closeEvent(self, event):
        # A running QThread is owned by this dialog. Do not destroy it while
        # scanning: request cancellation and keep the dialog alive until done.
        if self.worker and self.worker.isRunning():
            self.cancel_scan()
            self.status.setText("Cancelling Snap scan before closing…")
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.cancel_scan()
            self.status.setText("Cancelling Snap scan before closing…")
            return
        super().reject()

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self.status.setText("Scanning Snap revisions… (read-only)")
        self.worker = SnapScanThread(self)
        self.worker.progress_changed.connect(self.status.setText)
        self.worker.finished_scan.connect(self.show_results)
        self.worker.scan_cancelled.connect(
            lambda: self.status.setText("Snap scan cancelled. Previous results retained."))
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def cancel_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling Snap scan…")

    def finish_scan(self):
        self.progress.hide()
        self.cancel_button.hide()
        self.scan_button.setEnabled(True)

    def show_results(self, records, issues, storage=None):
        self.records = records
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            image = next((m for m in record.measurements
                          if m.role in (StorageRole.DIRECT, StorageRole.SHARED)), None)
            user = [m for m in record.measurements if m.role == StorageRole.USER]
            user_bytes = (sum(m.allocated_bytes or 0 for m in user)
                          if user and all(m.status in (
                              MeasurementStatus.MEASURED, MeasurementStatus.ABSENT
                          ) for m in user) else None)
            values = [
                record.kind.value, record.reference, record.metadata.get("state", "?"),
                record.metadata.get("version", ""),
                image.allocated_bytes if image and image.status == MeasurementStatus.MEASURED else None,
                user_bytes,
                (image.path if image else "") +
                (" | " + image.reason if image and image.status not in (
                    MeasurementStatus.MEASURED, MeasurementStatus.ABSENT) else ""),
            ]
            for col, value in enumerate(values):
                if col == 5 and not user:
                    cell = QTableWidgetItem("Not applicable" if record.kind.value == "runtime" else "Not measured")
                else:
                    cell = SizeCell(value) if col in (4, 5) else QTableWidgetItem(str(value))
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.sortItems(4, Qt.SortOrder.DescendingOrder)
        message = (f"{len(records)} Snap revisions. Images are compressed backing files; "
                   "disabled revisions are retained, not automatically disposable. "
                   "User data covers the current user's active revision and common directory. "
                   "No mounted filesystem is counted; no files modified.")
        if not records:
            message = "No Snap records found. No files modified."
        if issues:
            message += " Issues: " + "; ".join(issues)
        self.status.setText(message)
        # Report coverage independently of totals. Inaccessible paths are
        # never silently treated as zero or as reclaimable storage.
        image_measurements = [
            m for record in records for m in record.measurements
            if m.role in (StorageRole.DIRECT, StorageRole.SHARED)
        ]
        incomplete = (
            storage is None or
            any(m.status not in (MeasurementStatus.MEASURED, MeasurementStatus.ABSENT)
                for m in (storage.cache, storage.snapshots)) or
            any(m.status not in (MeasurementStatus.MEASURED, MeasurementStatus.ABSENT)
                for m in image_measurements)
        )
        if incomplete:
            self.coverage.setText(
                "Partial inventory — some storage could not be measured. "
                "Installed Snap images may be measured, but protected or "
                "unavailable storage locations prevent a complete storage total. "
                "No complete storage total is available."
            )
        else:
            self.coverage.setText(
                "Measured locations are accessible. This is not a complete "
                "system-wide disk usage or reclaimable-space estimate."
            )
        if storage is not None:
            def describe(measurement):
                if measurement.status == MeasurementStatus.MEASURED:
                    return format_size(measurement.allocated_bytes)
                if measurement.status == MeasurementStatus.ABSENT:
                    return "Absent"
                if measurement.status == MeasurementStatus.INACCESSIBLE:
                    return "Requires administrator access"
                return f"Unknown ({measurement.status.value})"
            self.storage_summary.setText(
                f"Package-manager storage (separate from installed images): "
                f"Cache {describe(storage.cache)} | "
                f"Snapshots {describe(storage.snapshots)}. "
                "These are not per-app sizes or necessarily reclaimable. "
                "Some Snap storage locations are protected by the operating system; "
                "AppFootprint does not request administrator privileges or modify files."
            )
        else:
            self.storage_summary.setText("Package-manager storage: not measured.")


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

    def __init__(self, item: Item, items: list[Item], parent: QWidget | None = None,
                 navigate: Callable[[Item], None] | None = None):
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
        tree.setToolTip("Double-click a component to open its details. No rescan is performed.")
        tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        content_layout.addWidget(tree)

        def navigable(node: QTreeWidgetItem, target: Item, relation: str) -> None:
            node.setData(0, Qt.ItemDataRole.UserRole, target)
            node.setToolTip(0, f"{target.ref} ({target.installation})\n{relation}\nDouble-click to open details")
            node.setToolTip(1, relation)

        def show_target(node: QTreeWidgetItem, _column: int) -> None:
            target = node.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(target, Item):
                return
            if navigate is not None:
                navigate(target)
            elif target.kind == "runtime":
                RuntimeDialog(target, items, self).exec()
            elif target.kind == "app":
                DetailDialog(target, self).exec()

        tree.itemDoubleClicked.connect(show_target)
        users = direct_runtime_users(item, items)
        apps_root = QTreeWidgetItem(
            tree, [f"Direct applications ({len(users)})", "Declared primary runtime"]
        )
        for app in users:
            node = QTreeWidgetItem(
                apps_root, [f"{app.app_id} ({app.installation})", "Direct"]
            )
            navigable(node, app, "Application declares this primary runtime")
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
                            extension_rows.append((extension, point))
                elif compatible_extension(point, item.ref, platform.ref):
                    platform_rows.append((platform, point))

        if extension_rows or (item.metadata and not platform_rows):
            distinct = list(dict.fromkeys(
                (extension.ref, point.name, point.conditions)
                for extension, point in extension_rows
            ))
            ext_root = QTreeWidgetItem(
                tree, [f"Compatible installed extensions ({len(distinct)})",
                       "Metadata compatibility"]
            )
            for ref, point_name, conditions in distinct:
                node = QTreeWidgetItem(ext_root, [ref, "Compatible extension"])
                target = next((e for e, p in extension_rows
                               if e.ref == ref and p.name == point_name), None)
                if target is not None:
                    navigable(node, target, f"Compatible via {point_name}; activation not verified")
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
                node = QTreeWidgetItem(platforms_root, [platform_ref, "Compatible platform"])
                platform = next(
                    p for p, point in platform_rows
                    if p.ref == platform_ref and point.name == point_name
                )
                navigable(node, platform, f"Extension point: {point_name}; activation not verified")
                for condition in conditions:
                    QTreeWidgetItem(node, [condition, "Activation condition"])
                possible = direct_runtime_users(platform, items)
                apps = QTreeWidgetItem(
                    node, [f"Potential applications ({len(possible)})",
                           "Via primary platform"]
                )
                for app in possible:
                    app_node = QTreeWidgetItem(
                        apps, [f"{app.app_id} ({app.installation})",
                               "Potential, not verified"]
                    )
                    navigable(app_node, app, "Potential user via compatible platform; not verified")

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
            "Double-click an application, platform or extension to open its details. "
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


class NavigationDialog(QDialog):
    """One-window history with preserved Qt page state."""

    def __init__(self, initial: Item, items: list[Item], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("AppFootprint — Dependency Explorer")
        self.resize(950, 650)
        self._items = items
        self._navigation = NavigationHistory()
        self._pages: dict[tuple[str, str, str], QWidget] = {}
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.back_button = QPushButton("← Back")
        self.forward_button = QPushButton("Forward →")
        self.breadcrumb = QLabel()
        self.breadcrumb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        toolbar.addWidget(self.back_button)
        toolbar.addWidget(self.forward_button)
        toolbar.addWidget(self.breadcrumb, 1)
        layout.addLayout(toolbar)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.back_button.clicked.connect(self.back)
        self.forward_button.clicked.connect(self.forward)
        self.navigate(initial)

    @staticmethod
    def key(item: Item) -> tuple[str, str, str]:
        return (item.kind, item.ref, item.installation)

    def navigate(self, item: Item) -> None:
        key = self.key(item)
        if key not in self._pages:
            if item.kind == "runtime":
                page = RuntimeDialog(item, self._items, self, navigate=self.navigate)
            elif item.kind == "app":
                page = DetailDialog(item, self)
            else:
                return
            for buttons in page.findChildren(QDialogButtonBox):
                buttons.hide()
            self._pages[key] = page
            self.stack.addWidget(page)
        if self._navigation.visit(key):
            self._show_current()

    def _show_current(self) -> None:
        key = self._navigation.current
        if key is None:
            return
        self.stack.setCurrentWidget(self._pages[key])
        self.back_button.setEnabled(self._navigation.can_back)
        self.forward_button.setEnabled(self._navigation.can_forward)
        self._update_history_label()

    def _update_history_label(self) -> None:
        """Show the recent route without discarding the full history tooltip."""
        visible, full = history_labels(
            self._navigation.entries, self._navigation.position
        )
        self.breadcrumb.setToolTip(
            "Navigation history (↩ = previously visited component):\n" + full
        )
        self.breadcrumb.setMinimumWidth(0)
        self.breadcrumb.setWordWrap(False)
        self.breadcrumb.setText(
            self.breadcrumb.fontMetrics().elidedText(
                visible, Qt.TextElideMode.ElideLeft,
                max(80, self.breadcrumb.width() - 8),
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._navigation.current is not None:
            self._update_history_label()

    def back(self) -> None:
        if self._navigation.back():
            self._show_current()

    def forward(self) -> None:
        if self._navigation.forward():
            self._show_current()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AppFootprint — Storage inventory (alpha)")
        self.resize(1200, 650)
        self.items: list[Item] = []
        self.snap_records = []
        self._flatpak_issues = []
        self._snap_issues = []
        self.snap_storage = None
        container = QWidget()
        layout = QVBoxLayout(container)
        self.info = QLabel("No inventory yet. Choose an available provider to start a read-only scan.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.storage_summary = QLabel("Snap cache and snapshots: not measured.")
        self.storage_summary.setWordWrap(True)
        layout.addWidget(self.storage_summary)
        self.provider_status = QLabel("Checking available package providers…")
        self.provider_status.setWordWrap(True)
        layout.addWidget(self.provider_status)
        self.button = QPushButton("Scan Flatpak installations")
        self.button.clicked.connect(self.start_scan)
        self.button.hide()  # Only reveal after the provider probe succeeds.
        layout.addWidget(self.button)
        self.snap_button = QPushButton("Scan Snap installations")
        self.snap_button.clicked.connect(self.start_snap_scan)
        self.snap_button.hide()
        layout.addWidget(self.snap_button)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Source:"))
        self.source_filter = QComboBox()
        self.source_filter.addItems(["All", "Flatpak", "Snap"])
        self.source_filter.currentIndexChanged.connect(self.apply_filters)
        filters.addWidget(self.source_filter)
        filters.addWidget(QLabel("Show:"))
        self.kind_filter = QComboBox()
        self.kind_filter.addItems(["All", "Applications", "Shared components"])
        self.kind_filter.currentIndexChanged.connect(self.apply_filters)
        filters.addWidget(self.kind_filter)
        filters.addStretch()
        layout.addLayout(filters)
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
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Kind", "Application ID", "Ref / version", "Installation",
            "Installed", "User data", "App total", "Runtime", "Path / errors", "Source",
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
        self.snap_worker: SnapScanThread | None = None
        self._flatpak_available = False
        self._snap_available = False
        self.probe = ProviderProbeThread(self)
        self.probe.detected.connect(self.providers_detected)
        self.probe.start()

    def providers_detected(self, statuses: dict[str, ProviderStatus]) -> None:
        flatpak = statuses.get("flatpak")
        snap = statuses.get("snap")
        self._flatpak_available = bool(flatpak and flatpak.available)
        self._snap_available = bool(snap and snap.available)
        self.button.setVisible(self._flatpak_available)
        self.snap_button.setVisible(self._snap_available)
        messages = []
        for name, status in (("Flatpak", flatpak), ("Snap", snap)):
            if status and status.available:
                messages.append(f"{name} available ({status.version or 'version unknown'}).")
            else:
                messages.append(f"{name} unavailable: {status.reason if status else 'not detected'}.")
        messages.append("RPM scanner not implemented yet.")
        self.provider_status.setText(" ".join(messages))

    def open_snap_inventory(self) -> None:
        self.start_snap_scan()

    def start_snap_scan(self) -> None:
        if not self._snap_available or (self.snap_worker and self.snap_worker.isRunning()):
            return
        if self.worker and self.worker.isRunning():
            return
        self.snap_button.setEnabled(False)
        self.button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self.info.setText("Scanning Snap revisions… (read-only)")
        self.snap_worker = SnapScanThread(self)
        self.snap_worker.progress_changed.connect(self.info.setText)
        self.snap_worker.finished_scan.connect(self.show_snap_results)
        self.snap_worker.scan_cancelled.connect(self.scan_was_cancelled)
        self.snap_worker.finished.connect(self.finish_snap_scan)
        self.snap_worker.start()

    def show_snap_results(self, records, issues, storage) -> None:
        self.snap_records = records
        self._snap_issues = list(issues)
        self.snap_storage = storage
        self.render_inventory()

    def finish_snap_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        self.snap_button.setEnabled(True)
        self.button.setEnabled(True)


    def start_scan(self) -> None:
        if not self._flatpak_available:
            return
        if self.worker and self.worker.isRunning():
            return
        if self.snap_worker and self.snap_worker.isRunning():
            return
        self.snap_button.setEnabled(False)
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
        if self.snap_worker and self.snap_worker.isRunning():
            self.snap_worker.cancel()
            self.cancel_button.setEnabled(False)
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.info.setText("Cancelling scan… waiting for current operation.")

    def scan_was_cancelled(self) -> None:
        # Keep the last completed results rather than showing partial data.
        self.info.setText(
            "Scan cancelled. Previous results retained; no files modified. "
            + (self._explore_hint() if self.items else "")
        )

    def show_progress(self, message: str) -> None:
        if self.worker and not self.worker._cancel.is_set():
            self.info.setText(message + " (read-only)")

    def finish_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        self.button.setText("Scan Flatpak installations")
        self.button.setEnabled(True)
        self.snap_button.setEnabled(True)

    @staticmethod
    def _explore_hint() -> str:
        return ("Double-click an application to explore user data, or a runtime "
                "to examine shared dependencies.")

    def show_results(self, items: list[Item], issues: list[str]) -> None:
        self.items = items
        self._flatpak_issues = list(issues)
        self.render_inventory()

    def apply_filters(self, *_args) -> None:
        source = self.source_filter.currentText()
        category = self.kind_filter.currentText()
        for row in range(self.table.rowCount()):
            provider = self.table.item(row, 9).data(Qt.ItemDataRole.UserRole + 2)
            kind = self.table.item(row, 0).text()
            visible = ((source == "All" or source == provider) and
                       (category == "All" or
                        (category == "Applications" and kind == "app") or
                        (category == "Shared components" and kind != "app")))
            self.table.setRowHidden(row, not visible)

    def render_inventory(self) -> None:
        rows = combine(self.items, self.snap_records)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            values = [record.kind, record.identifier, record.reference, record.scope,
                      record.installed, record.user_data, record.app_total,
                      record.runtime, record.path, record.provider]
            for col, value in enumerate(values):
                if col in (4, 5, 6):
                    cell = (SizeCell(value) if value is not None else
                            QTableWidgetItem("Not applicable" if
                                             record.kind != "app" and col in (5, 6)
                                             else "Unknown"))
                else:
                    cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole + 1, record.index)
                cell.setData(Qt.ItemDataRole.UserRole + 2, record.provider)
                self.table.setItem(row, col, cell)
            source = self.table.item(row, 9)
            source.setText("● " + record.provider)
            source.setForeground(QBrush(QColor("#278b89" if record.provider == "Flatpak"
                                               else "#bf7837")))
            source.setToolTip(record.provider + " package manager")
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)
        self.apply_filters()
        message = (f"{len(self.items)} Flatpak records; {len(self.snap_records)} "
                   "Snap revisions. Shared components excluded from application "
                   "totals; unknown measurements are not zero. Read-only.")
        issues = self._flatpak_issues + self._snap_issues
        if issues:
            message += " Issues: " + "; ".join(issues)
        if self.items:
            message += " " + self._explore_hint()
        self.info.setText(message)
        if self.snap_storage is not None:
            def storage_label(m):
                if m.status == MeasurementStatus.MEASURED:
                    return format_size(m.allocated_bytes)
                if m.status == MeasurementStatus.INACCESSIBLE:
                    return "Requires administrator access"
                return "Unknown" if m.status != MeasurementStatus.ABSENT else "Absent"
            self.storage_summary.setText(
                "Snap package-manager storage (not included in app totals): "
                f"Cache {storage_label(self.snap_storage.cache)} | "
                f"Snapshots {storage_label(self.snap_storage.snapshots)}. "
                "A complete storage total is unavailable when paths are protected."
            )

    def show_detail(self, row: int, _column: int) -> None:
        cell = self.table.item(row, 0)
        if cell is None:
            return
        original_index = cell.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(original_index, int):
            return
        provider = cell.data(Qt.ItemDataRole.UserRole + 2)
        if provider == "Snap":
            record = self.snap_records[original_index]
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "Snap inventory",
                f"{record.reference} ({record.metadata.get('state', 'unknown')})\\n"
                "Snap dependency navigation is not implemented yet.\\n"
                "No files modified."
            )
            return
        item = self.items[original_index]
        if item.kind not in ("runtime", "app"):
            return
        NavigationDialog(item, self.items, self).exec()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
