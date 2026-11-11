"""Minimal Qt front end for the read-only Flatpak inventory."""
from __future__ import annotations

import sys

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QApplication, QHeaderView, QLabel, QMainWindow, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .scanner import Item, format_size, scan


class ScanThread(QThread):
    finished_scan = Signal(object, object)

    def run(self) -> None:
        items, issues = scan()
        self.finished_scan.emit(items, issues)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AppFootprint — Flatpak inventory (alpha)")
        self.resize(1050, 620)
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
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            "Kind", "Application ID", "Ref / version", "Installation", "Installed",
            "User data", "Runtime", "Path / errors",
        ])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
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
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = [
                item.kind, item.app_id, item.ref, item.installation,
                format_size(item.allocated_bytes),
                format_size(item.user_data_bytes) if item.kind == "app" else "—",
                item.runtime if item.kind == "app" else "—",
                item.location + (" | " if item.location and item.errors else "")
                + "; ".join(item.errors),
            ]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if col in (4, 5):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(row, col, cell)
        summary = f"{len(items)} Flatpak records. No files modified."
        if issues:
            summary += " Issues: " + "; ".join(issues)
        self.info.setText(summary)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
