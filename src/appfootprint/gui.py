"""Qt interface for read-only Flatpak storage inventory."""
from __future__ import annotations

import sys

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QLabel,
    QMainWindow, QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .scanner import Item, format_size, scan


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
    finished_scan = Signal(object, object)

    def run(self) -> None:
        try:
            items, issues = scan()
        except Exception as exc:
            items, issues = [], [f"Scan failed: {exc}"]
        self.finished_scan.emit(items, issues)


class DetailDialog(QDialog):
    """Read-only breakdown of the selected app's user data."""

    def __init__(self, item: Item, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Storage details — {item.app_id}")
        self.resize(800, 440)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"Installed: {format_size(item.allocated_bytes)} | "
            f"User data: {format_size(item.user_data_bytes)} | "
            f"Runtime (shared, not included): {item.runtime or 'Unknown'}"
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["User data location", "Allocated"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)
        # Use measurements captured by the background scan. Rewalking large
        # directories on the UI thread would freeze the window.
        for name, size in sorted(
            item.user_data_breakdown,
            key=lambda pair: (pair[1] is not None, pair[1] or 0),
            reverse=True,
        ):
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(
                row, 0, QTableWidgetItem(f"{item.user_data_path}/{name}")
            )
            self.table.setItem(row, 1, SizeCell(size))
        if not item.user_data_breakdown:
            layout.addWidget(QLabel("No user-data children found or accessible."))
        layout.addWidget(QLabel(
            "Sizes are allocated blocks, not guaranteed reclaimable space. "
            "No files are modified."
        ))
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
            "Double-click an application for user data details."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.button = QPushButton("Scan Flatpak installations")
        self.button.clicked.connect(self.start_scan)
        layout.addWidget(self.button)
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
        self.progress.show()
        self.info.setText("Scanning Flatpak applications and user data… (read-only)")
        self.worker = ScanThread(self)
        self.worker.finished_scan.connect(self.show_results)
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def finish_scan(self) -> None:
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
        if item.kind != "app":
            return
        dialog = DetailDialog(item, self)
        dialog.exec()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
