"""Read-only Flatpak inventory and per-application data browser."""
from __future__ import annotations

import sys

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QHeaderView, QLabel, QMainWindow, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .scanner import Item, format_size, scan


class SizeItem(QTableWidgetItem):
    """Sort numeric byte counts, not human-readable size strings."""

    def __init__(self, value: int | None):
        super().__init__(format_size(value))
        self.value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setData(Qt.ItemDataRole.UserRole, value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SizeItem):
            if self.value is None:
                return other.value is not None
            if other.value is None:
                return False
            return self.value < other.value
        return super().__lt__(other)


class ScanThread(QThread):
    finished_scan = Signal(object, object)

    def run(self) -> None:
        items, issues = scan()
        self.finished_scan.emit(items, issues)


class DetailsDialog(QDialog):
    def __init__(self, item: Item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Storage details — {item.app_id}")
        self.resize(800, 470)
        layout = QVBoxLayout(self)
        description = QLabel(
            f"<b>{item.app_id}</b><br>"
            f"Deployment: {format_size(item.allocated_bytes)}<br>"
            f"User data: {format_size(item.user_data_bytes)}<br>"
            f"Runtime: {item.runtime or 'Not available'}<br>"
            "Measurements are allocated blocks, not guaranteed reclaimable space."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Data entry", "Allocated"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        breakdown = sorted(
            item.user_data_breakdown,
            key=lambda pair: pair[1] if pair[1] is not None else -1,
            reverse=True,
        )
        table.setRowCount(len(breakdown))
        for row, (name, size) in enumerate(breakdown):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, SizeItem(size))
        layout.addWidget(table)
        note = QLabel(f"Data location: {item.user_data_path or 'Not available'}")
        note.setWordWrap(True)
        layout.addWidget(note)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AppFootprint — Flatpak inventory (alpha)")
        self.resize(1200, 650)
        self.items: list[Item] = []
        container = QWidget()
        layout = QVBoxLayout(container)
        self.info = QLabel(
            "Read-only inventory. Sizes are allocated blocks, not guaranteed "
            "reclaimable space. Shared runtimes appear as separate rows."
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.button = QPushButton("Scan Flatpak installations")
        self.button.clicked.connect(self.start_scan)
        layout.addWidget(self.button)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Kind", "Application ID", "Ref / version", "Installation",
            "Installed", "User data", "App + data", "Runtime", "Path / errors",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self.open_details)
        layout.addWidget(self.table)
        self.setCentralWidget(container)
        self.worker: ScanThread | None = None

    def start_scan(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.button.setEnabled(False)
        self.info.setText("Scanning… (read-only)")
        self.worker = ScanThread(self)
        self.worker.finished_scan.connect(self.show_results)
        self.worker.finished.connect(lambda: self.button.setEnabled(True))
        self.worker.start()

    def show_results(self, items: list[Item], issues: list[str]) -> None:
        self.items = items
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            combined = (
                item.allocated_bytes + item.user_data_bytes
                if item.kind == "app"
                and item.allocated_bytes is not None
                and item.user_data_bytes is not None
                else None
            )
            values = [
                item.kind, item.app_id, item.ref, item.installation,
                item.allocated_bytes,
                item.user_data_bytes if item.kind == "app" else None,
                combined if item.kind == "app" else None,
                item.runtime if item.kind == "app" else "—",
                item.location + (" | " if item.location and item.errors else "")
                + "; ".join(item.errors),
            ]
            for col, value in enumerate(values):
                cell = SizeItem(value) if col in (4, 5, 6) else QTableWidgetItem(value)
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, row)
                self.table.setItem(row, col, cell)
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)
        self.table.resizeColumnsToContents()
        summary = (
            f"{len(items)} Flatpak records. Double-click a row for details. "
            "App + data excludes shared runtimes; no files modified."
        )
        if issues:
            summary += " Issues: " + "; ".join(issues)
        self.info.setText(summary)

    def open_details(self, row: int, column: int) -> None:
        index = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        item = self.items[index]
        dialog = DetailsDialog(item, self)
        dialog.exec()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
