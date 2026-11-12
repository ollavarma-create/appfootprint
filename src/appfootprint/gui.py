"""Qt interface for read-only Flatpak storage inventory."""
from __future__ import annotations

import sys
from datetime import datetime
from threading import Event

from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThread, QThreadPool, Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QColor, QPixmap, QIcon
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QLabel, QMenu, QFrame, QGroupBox, QGridLayout, QSizePolicy, QToolButton, QMessageBox,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QStackedWidget, QHBoxLayout, QComboBox, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .extensions import compatible_extension, parse_extension_points
from .navigation import NavigationHistory, history_labels
from .scanner import Item, ScanCancelled, allocated_size, direct_runtime_users, runtime_extension_hint, format_size, scan
from .advisor import assess_path, space_significance
from .provider_detection import ProviderStatus, detect_providers
from .providers.snap import SnapProvider
from .providers.rpm import RpmProvider
from .rpm_dependencies import scan_rpm_capabilities
from .display import provider_title, inventory_column_labels
from .user_storage import scan_user_storage
from .storage_investigator import investigate, inspection_commands, inspection_script
from .unified import combine
from .overview import flatpak_overview, snap_overview, rpm_overview
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


class RpmScanThread(QThread):
    progress_changed = Signal(str)
    finished_scan = Signal(object, object)
    scan_cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            records, issues = RpmProvider().scan(
                progress=self.progress_changed.emit, cancelled=self._cancel.is_set)
        except ScanCancelled:
            self.scan_cancelled.emit()
            return
        except Exception as exc:
            records, issues = [], [f"RPM scan failed: {exc}"]
        self.finished_scan.emit(records, issues)


class UserStorageThread(QThread):
    progress_changed = Signal(str)
    loaded = Signal(object, object)
    cancelled_scan = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            entries, issues = scan_user_storage(
                cancelled=self._cancel.is_set,
                progress=self.progress_changed.emit)
        except ScanCancelled:
            self.cancelled_scan.emit()
            return
        except Exception as exc:
            entries, issues = [], [f"User storage scan failed: {exc}"]
        self.loaded.emit(entries, issues)


class InvestigationThread(QThread):
    progress_changed = Signal(str)
    loaded = Signal(object, object)
    cancelled_scan = Signal()

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self._cancel = Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = investigate(
                self.root, cancelled=self._cancel.is_set,
                progress=self.progress_changed.emit)
        except ScanCancelled:
            self.cancelled_scan.emit()
            return
        except Exception as exc:
            self.loaded.emit(None, str(exc))
            return
        self.loaded.emit(result, None)


class StorageInvestigatorDialog(QDialog):
    """Read-only per-root breakdown with copy-only inspection commands."""

    def __init__(self, root, parent=None):
        super().__init__(parent)
        self.root = root
        self.setWindowTitle("Storage Investigator — " + str(root))
        self.resize(980, 580)
        layout = QVBoxLayout(self)
        self.note = QLabel(
            "Read-only allocated bytes. Each child is measured independently; "
            "hardlinks and Btrfs shared extents can overlap. No cleanup advice "
            "or reclaimable-space estimate. No commands are executed.")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.status = QLabel("Not scanned")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Allocated", "Status", "Known subtotal", "Path"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.show_commands)
        layout.addWidget(self.table)
        layout.addWidget(QLabel("Inspection examples (copy only; no execution):"))
        self.commands = QLabel("Select a row to see inspection commands")
        self.commands.setWordWrap(True)
        self.commands.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.commands)
        controls = QHBoxLayout()
        self.scan_button = QPushButton("Scan subdirectories")
        self.scan_button.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        controls.addWidget(self.cancel_button)
        self.copy_button = QPushButton("Copy inspection commands")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_commands)
        controls.addWidget(self.copy_button)
        controls.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.worker = None
        self.start_scan()

    def start_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Scanning…")
        self.worker = InvestigationThread(self.root, self)
        self.worker.progress_changed.connect(self.status.setText)
        self.worker.loaded.connect(self.show_results)
        self.worker.cancelled_scan.connect(
            lambda: self.status.setText("Cancelled; previous results retained"))
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def finish_scan(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def cancel_scan(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling…")

    def show_results(self, result, error):
        if error:
            self.status.setText("Investigation failed: " + error)
            return
        self.table.setRowCount(len(result.children))
        for row, entry in enumerate(result.children):
            values = [
                entry.label, format_size(entry.allocated_bytes), entry.status,
                format_size(entry.known_allocated_bytes)
                if entry.status == "incomplete" else "—", entry.path]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if entry.reason:
                    item.setToolTip(entry.reason)
                self.table.setItem(row, col, item)
        unknown = sum(e.allocated_bytes is None for e in result.children)
        self.status.setText(
            f"{len(result.children)} immediate children · {unknown} unknown/incomplete")

    def selected_commands(self):
        row = self.table.currentRow()
        if row < 0:
            return ()
        item = self.table.item(row, 4)
        return inspection_commands(item.text()) if item is not None else ()

    def show_commands(self):
        commands = self.selected_commands()
        self.commands.setText(inspection_script(self.table.item(self.table.currentRow(), 4).text()) if commands else
                              "Select a row to see inspection commands")
        self.copy_button.setEnabled(bool(commands))

    def copy_commands(self):
        commands = self.selected_commands()
        if commands:
            QApplication.clipboard().setText(inspection_script(self.table.item(self.table.currentRow(), 4).text()))

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.cancel_scan()
            self.status.setText("Waiting for cancellation before closing…")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.cancel_scan()
            event.ignore()
            return
        super().closeEvent(event)


class UserStorageDialog(QDialog):
    """Separate XDG observations; intentionally not added to provider totals."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User Storage — read-only XDG inventory")
        self.resize(880, 440)
        layout = QVBoxLayout(self)
        note = QLabel(
            "Independent allocated-byte observations. Flatpak user data may overlap; "
            "do not add these values to provider totals. On Btrfs, reported bytes "
            "are not guaranteed physical or reclaimable space. No deletion.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel("Not scanned")
        layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Category", "Path", "Status", "Allocated", "Known subtotal"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.table.cellDoubleClicked.connect(self.open_investigator)
        hint = QLabel("Double-click a measured directory to inspect its immediate children.")
        layout.addWidget(hint)
        controls = QHBoxLayout()
        self.scan_button = QPushButton("Scan user storage")
        self.scan_button.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_scan)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.cancel_button)
        controls.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.worker = None

    def open_investigator(self, row, _column):
        status = self.table.item(row, 2)
        path = self.table.item(row, 1)
        if status is None or path is None or status.text() != "measured":
            return
        StorageInvestigatorDialog(Path(path.text()), self).exec()

    def start_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status.setText("Scanning XDG directories…")
        self.worker = UserStorageThread(self)
        self.worker.progress_changed.connect(self.status.setText)
        self.worker.loaded.connect(self.show_results)
        self.worker.cancelled_scan.connect(
            lambda: self.status.setText("Scan cancelled; previous results retained"))
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def cancel_scan(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText("Cancelling…")

    def finish_scan(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def show_results(self, entries, issues):
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            values = [
                entry.label, entry.path, entry.status,
                format_size(entry.allocated_bytes),
                format_size(entry.known_allocated_bytes)
                if entry.status == "incomplete" else "—",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if entry.reason:
                    cell.setToolTip(entry.reason)
                self.table.setItem(row, column, cell)
        incomplete = sum(e.status in ("incomplete", "inaccessible", "error")
                         for e in entries)
        self.status.setText(
            f"{len(entries)} directories · {incomplete} incomplete/unknown"
            + (f" · {'; '.join(issues)}" if issues else ""))

    def reject(self):
        if self.worker is not None and self.worker.isRunning():
            self.cancel_scan()
            self.status.setText("Waiting for cancellation before closing…")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.cancel_scan()
            event.ignore()
            return
        super().closeEvent(event)


class RpmDependencyThread(QThread):
    loaded = Signal(object, object)

    def run(self):
        try:
            self.loaded.emit(scan_rpm_capabilities(), None)
        except Exception as exc:
            self.loaded.emit(None, str(exc))


class RpmDependencyDialog(QDialog):
    """Navigate candidate RPM capability matches; never imply removability."""

    def __init__(self, reference: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RPM capability explorer — candidate matches")
        self.resize(940, 620)
        self.reference = reference
        self.measurements_by_reference = {}
        self.index = None
        self.history = [reference]
        self.position = 0
        layout = QVBoxLayout(self)
        self.note = QLabel(
            "Read-only capability-name matches. Versions, rich expressions and "
            "DNF resolution are NOT verified. Matches are not removal advice."
        )
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.heading = QLabel("Loading RPM capabilities…")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        nav = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(self.back)
        self.back_button.setEnabled(False)
        nav.addWidget(self.back_button)
        self.forward_button = QPushButton("Forward")
        self.forward_button.clicked.connect(self.forward)
        self.forward_button.setEnabled(False)
        nav.addWidget(self.forward_button)
        nav.addStretch()
        layout.addLayout(nav)
        self.requires_tree = QTreeWidget()
        self.requires_tree.setHeaderLabels(["Required capability", "Candidate installed provider"])
        self.requires_tree.itemDoubleClicked.connect(self.navigate_item)
        layout.addWidget(QLabel("Requires — candidate providers (double-click to navigate)"))
        layout.addWidget(self.requires_tree)
        self.reverse_tree = QTreeWidget()
        self.reverse_tree.setHeaderLabels(["Potential dependent package", "Matching capability"])
        self.reverse_tree.itemDoubleClicked.connect(self.navigate_item)
        layout.addWidget(QLabel("Potential reverse dependencies (double-click to navigate)"))
        layout.addWidget(self.reverse_tree)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        layout.addWidget(close)
        self.worker = RpmDependencyThread(self)
        self.worker.loaded.connect(self.loaded)
        self.worker.start()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.heading.setText("Waiting for RPM query to finish before closing…")
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self):
        if self.worker.isRunning():
            self.heading.setText("Waiting for RPM query to finish before closing…")
            return
        super().reject()

    def loaded(self, index, error):
        if error:
            self.heading.setText("RPM capability inventory failed: " + error)
            return
        self.index = index
        self.show_package(self.reference)

    def show_measurement(self):
        record = self.measurements_by_reference.get(self.reference)
        if record is None:
            QMessageBox.information(
                self, "RPM measurement",
                "Measurement unavailable for this package. Scan RPM inventory "
                "to collect allocated-byte measurements.")
            return
        measurement = record.measurements[0] if record.measurements else None
        status = measurement.status.value if measurement else "unknown"
        details = [
            record.reference,
            f"Measurement: {status}",
            f"Allocated: {format_size(measurement.allocated_bytes if measurement else None)}",
            f"Known subtotal (not complete size): {format_size(int(record.metadata.get('known_allocated_bytes', '0')))}",
            f"File count: {record.metadata.get('file_count', '?')}",
            f"Internal hardlinks: {record.metadata.get('internal_hardlink_paths', '?')}",
            f"Multi-owned paths: {record.metadata.get('multi_owned_paths', '?')}",
            f"Missing files: {record.metadata.get('absent_files', '?')}",
            f"Inaccessible files: {record.metadata.get('inaccessible_files', '?')}",
            *record.issues,
            "Read-only. No DNF dependency resolution or reclaimable-space estimate.",
        ]
        QMessageBox.information(self, "RPM measurement", "\n".join(details))

    def show_package(self, reference):
        if self.index is None:
            return
        if reference not in self.index.packages:
            self.heading.setText("Package not found in capability inventory: " + reference)
            return
        self.reference = reference
        view = self.index.view(reference)
        self.heading.setText(view.package.reference)
        self.requires_tree.clear()
        for link in view.requirements:
            if not link.candidates:
                QTreeWidgetItem(self.requires_tree, [link.requirement, "No name match / unresolved"])
            else:
                for candidate in link.candidates:
                    item = QTreeWidgetItem(self.requires_tree, [link.requirement, candidate])
                    item.setData(0, Qt.ItemDataRole.UserRole, candidate)
        self.reverse_tree.clear()
        for candidate, capability in view.required_by:
            item = QTreeWidgetItem(self.reverse_tree, [candidate, capability])
            item.setData(0, Qt.ItemDataRole.UserRole, candidate)
        for tree in (self.requires_tree, self.reverse_tree):
            tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            tree.header().setStretchLastSection(True)
        self.back_button.setEnabled(self.position > 0)
        self.forward_button.setEnabled(self.position + 1 < len(self.history))

    def navigate_item(self, item, _column):
        reference = item.data(0, Qt.ItemDataRole.UserRole)
        if reference and reference != self.reference:
            self.history = self.history[:self.position + 1] + [reference]
            self.position += 1
            self.show_package(reference)

    def back(self):
        if self.position > 0:
            self.position -= 1
            self.show_package(self.history[self.position])

    def forward(self):
        if self.position + 1 < len(self.history):
            self.position += 1
            self.show_package(self.history[self.position])


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


class FootprintOverview(QWidget):
    """Small, provider-specific bar with separate target coverage disclosure."""

    def __init__(self, provider: str, parent=None):
        super().__init__(parent)
        self.provider = provider
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        self.heading = QLabel("Not scanned")
        layout.addWidget(self.heading)
        self.bar = QFrame()
        self.bar.setFixedHeight(14)
        self.bar_layout = QHBoxLayout(self.bar)
        self.bar_layout.setContentsMargins(0, 0, 0, 0)
        self.bar_layout.setSpacing(2)
        self.application_segment = QFrame()
        self.shared_segment = QFrame()
        self.application_segment.setStyleSheet("background-color: #278b89; border-radius: 2px;")
        self.shared_segment.setStyleSheet("background-color: #7c76bc; border-radius: 2px;")
        self.bar_layout.addWidget(self.application_segment)
        self.bar_layout.addWidget(self.shared_segment)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        layout.addWidget(self.legend)
        self.coverage = QLabel("")
        self.coverage.setWordWrap(True)
        layout.addWidget(self.coverage)

    def update_overview(self, overview) -> None:
        if not overview.scanned:
            self.heading.setText("Not scanned")
            self.bar.hide()
            self.legend.setText("Run a scan to see measured storage.")
            self.coverage.setText("")
            return
        self.heading.setText(
            f"{format_size(overview.measured_bytes)} "
            "in reported measurements (not reclaimable space)"
        )
        self.legend.setText(
            f"Apps: {format_size(overview.application_bytes)} · "
            f"Shared: {format_size(overview.shared_bytes)}"
        )
        a, b = overview.application_bytes, overview.shared_bytes
        self.bar.setVisible(a + b > 0)
        # Relative bar widths describe only reported measured bytes.
        total = a + b
        self.bar_layout.setStretch(0, max(1, round(1000 * a / total)) if a else 0)
        self.bar_layout.setStretch(1, max(1, round(1000 * b / total)) if b else 0)
        self.application_segment.setVisible(a > 0)
        self.shared_segment.setVisible(b > 0)
        self.coverage.setText(
            f"{overview.measured_targets} measured · "
            f"{overview.absent_targets} absent · "
            f"{overview.unknown_targets} unknown"
            + (" · Partial measurement" if overview.partial else "")
        )
        self.coverage.setToolTip(
            "Counts describe identified measurement targets, not a percentage "
            "of disk bytes. Unknown locations may contain arbitrarily large "
            "amounts of data. The bar excludes unknown sizes and does not "
            "estimate reclaimable storage."
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AppFootprint — Storage inventory (alpha)")
        self.resize(1200, 650)
        self.items: list[Item] = []
        self.snap_records = []
        self.rpm_records = []
        self._flatpak_issues = []
        self._snap_issues = []
        self._rpm_issues = []
        self.snap_storage = None
        self._flatpak_available = False
        self._snap_available = False
        self._rpm_available = False
        self._scan_state = {"Flatpak": "not_scanned", "Snap": "not_scanned", "RPM": "not_scanned"}
        self._scan_time = {"Flatpak": None, "Snap": None, "RPM": None}
        self._scan_count = {"Flatpak": 0, "Snap": 0, "RPM": 0}
        self._scan_progress = {"Flatpak": "", "Snap": "", "RPM": ""}
        container = QWidget()
        layout = QVBoxLayout(container)
        self.info = QLabel("No inventory yet. Choose an available provider to start a read-only scan.")
        self.info.setWordWrap(True)
        self.info.hide()  # Detail text is available from provider info buttons.
        self.storage_summary = QLabel("Snap cache and snapshots: not measured.")
        self.storage_summary.setWordWrap(True)
        self.storage_summary.hide()
        self.provider_status = QLabel("Checking available package providers…")
        self.provider_status.setWordWrap(True)
        self.provider_status.hide()
        self.overview_group = QGroupBox("Storage overview — reported bytes, not reclaimable space")
        self.overview_grid = QGridLayout(self.overview_group)
        self.overview_grid.setContentsMargins(8, 8, 8, 8)
        self.overview_grid.setSpacing(8)
        self._overview_columns = 0

        self.button = QPushButton("Scan Flatpak installations")
        self.button.clicked.connect(self.start_scan)
        self.flatpak_scan_status = QLabel("Flatpak: Not scanned")
        self.flatpak_scan_status.setWordWrap(True)
        self.flatpak_overview = FootprintOverview("Flatpak")
        self.flatpak_card = self._create_provider_card(
            "Flatpak", self.flatpak_overview, self.button, self.flatpak_scan_status
        )

        self.snap_button = QPushButton("Scan Snap installations")
        self.snap_button.clicked.connect(self.start_snap_scan)
        self.snap_scan_status = QLabel("Snap: Not scanned")
        self.snap_scan_status.setWordWrap(True)
        self.snap_overview = FootprintOverview("Snap")
        self.snap_card = self._create_provider_card(
            "Snap", self.snap_overview, self.snap_button, self.snap_scan_status
        )
        self.rpm_button = QPushButton("Scan RPM installations")
        self.rpm_button.clicked.connect(self.start_rpm_scan)
        self.rpm_scan_status = QLabel("RPM: Not scanned")
        self.rpm_scan_status.setWordWrap(True)
        self.rpm_overview = FootprintOverview("RPM")
        self.rpm_card = self._create_provider_card(
            "RPM", self.rpm_overview, self.rpm_button, self.rpm_scan_status
        )
        self.provider_versions = {"Flatpak": None, "Snap": None, "RPM": None}
        self.flatpak_info_button = self._add_info_button(self.flatpak_card, "Flatpak")
        self.snap_info_button = self._add_info_button(self.snap_card, "Snap")
        self.rpm_info_button = self._add_info_button(self.rpm_card, "RPM")
        self.button.hide()  # Preserve explicit visibility until availability probe completes.
        self.snap_button.hide()
        self.rpm_button.hide()
        self.rpm_card.hide()
        self.flatpak_card.hide()
        self.snap_card.hide()
        self._layout_overview_cards()
        layout.addWidget(self.overview_group)
        self.overview_note = QLabel(
            "Teal: applications · Violet: shared or unclassified package bytes. "
            "Bars show measured bytes within each provider only; "
            "unknown sizes are excluded. Target counts are not disk percentages."
        )
        self.overview_note.setWordWrap(True)
        layout.addWidget(self.overview_note)
        filters = QHBoxLayout()
        filters.addWidget(QLabel("Source:"))
        self.source_filter = QComboBox()
        self.source_filter.addItems(["All", "Flatpak", "Snap", "RPM"])
        self.source_filter.currentIndexChanged.connect(self.apply_filters)
        filters.addWidget(self.source_filter)
        filters.addWidget(QLabel("Show:"))
        self.kind_filter = QComboBox()
        self.kind_filter.addItems(["All", "Applications", "Shared components", "RPM packages"])
        self.kind_filter.currentIndexChanged.connect(self.apply_filters)
        filters.addWidget(self.kind_filter)
        filters.addStretch()
        self.user_storage_button = QPushButton("User Storage…")
        self.user_storage_button.clicked.connect(self.open_user_storage)
        filters.addWidget(self.user_storage_button)
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
        self.table.setHorizontalHeaderLabels(inventory_column_labels())
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
        self.rpm_worker: RpmScanThread | None = None
        self._flatpak_available = False
        self._snap_available = False
        self.probe = ProviderProbeThread(self)
        self.probe.detected.connect(self.providers_detected)
        self.probe.start()

    def open_user_storage(self):
        UserStorageDialog(self).exec()

    @staticmethod
    def _create_provider_card(provider, overview, button, status):
        card = QGroupBox(provider)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body = QVBoxLayout(card)
        body.setContentsMargins(8, 6, 8, 6)
        body.setSpacing(4)
        body.addWidget(overview)
        body.addWidget(button)
        body.addWidget(status)
        return card

    def _add_info_button(self, card: QGroupBox, provider: str) -> QToolButton:
        # A button beside the title is keyboard-accessible, unlike a tooltip alone.
        # QGroupBox owns the border/title; the button sits in the header area.
        button = QToolButton(card)
        button.setText("ⓘ")
        button.setMinimumSize(24, 24)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setAccessibleName(f"{provider} information")
        button.setToolTip(f"Show {provider} scan details and measurement limitations")
        button.setAutoRaise(True)
        button.clicked.connect(lambda: self.show_provider_information(provider))
        return button

    def _position_info_buttons(self) -> None:
        for card, button in (
            (self.flatpak_card, self.flatpak_info_button),
            (self.snap_card, self.snap_info_button),
            (self.rpm_card, self.rpm_info_button),
        ):
            # Keep the information button on the right side of the card title.
            button.adjustSize()
            button.move(max(0, card.width() - button.width() - 9), 1)
            button.raise_()

    def _provider_information(self, provider: str) -> str:
        version = self.provider_versions.get(provider) or "version unknown"
        count = self._scan_count[provider]
        status = self._scan_state[provider].replace("_", " ")
        details = [
            f"{provider} {version}",
            f"Scan status: {status}; {count} records in last completed inventory.",
            "AppFootprint is read-only and never requests administrator privileges.",
            "Reported bytes are not a prediction of space reclaimed by uninstalling.",
            "Shared components and filesystem deduplication can affect physical usage.",
            "Unknown measurements are not zero; target counts are not disk percentages.",
        ]
        issues = {"Flatpak": self._flatpak_issues, "Snap": self._snap_issues, "RPM": self._rpm_issues}[provider]
        if issues:
            details.append("Scan issues: " + "; ".join(issues))
        if provider == "Snap":
            details.append(self.storage_summary.text())
            details.append(
                "Snap cache and snapshots are not included in application totals. "
                "Protected locations may require administrator access; "
                "AppFootprint does not elevate privileges."
            )
        elif provider == "RPM":
            details.append("RPM packages are unclassified. Only complete package measurements "
                           "contribute to the overview. Unknown bytes are not zero; "
                           "RPM user data is not measured.")
        else:
            details.append(self._explore_hint())
        return "\n\n".join(details)

    def show_provider_information(self, provider: str) -> None:
        QMessageBox.information(
            self, f"{provider} — measurement information",
            self._provider_information(provider)
        )

    def _layout_overview_cards(self) -> None:
        cards = [card for card, available in (
            (self.flatpak_card, self._flatpak_available),
            (self.snap_card, self._snap_available),
            (self.rpm_card, self._rpm_available),
        ) if available]
        # One column when narrow; otherwise put provider cards side by side.
        # Keep all available provider cards in a responsive grid.
        columns = 1 if self.width() < 820 else min(3, max(1, len(cards)))
        all_cards = (self.flatpak_card, self.snap_card, self.rpm_card)
        # Check exact membership, not only whether currently available
        # cards are present: an unavailable provider may still be in the grid.
        current_cards = {
            card for card in all_cards
            if self.overview_grid.indexOf(card) >= 0
        }
        if columns == self._overview_columns and current_cards == set(cards):
            return
        self._overview_columns = columns
        for card in all_cards:
            self.overview_grid.removeWidget(card)
            card.hide()
        for index, card in enumerate(cards):
            self.overview_grid.addWidget(card, index // columns, index % columns)
            card.show()
        self.overview_group.setVisible(bool(cards))
        if hasattr(self, "flatpak_info_button"):
            self._position_info_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "overview_grid") and hasattr(self, "flatpak_info_button"):
            self._layout_overview_cards()
            self._position_info_buttons()

    def closeEvent(self, event):
        # Keep worker-owned Qt objects alive until scans stop.
        running = [worker for worker in (self.worker, self.snap_worker, self.rpm_worker)
                   if worker is not None and worker.isRunning()]
        if running:
            for worker in running:
                worker.cancel()
            self.info.setText("Cancelling active scans before closing…")
            event.ignore()
            return
        super().closeEvent(event)

    def providers_detected(self, statuses: dict[str, ProviderStatus]) -> None:
        flatpak = statuses.get("flatpak")
        snap = statuses.get("snap")
        rpm = statuses.get("rpm")
        self._flatpak_available = bool(flatpak and flatpak.available)
        self._snap_available = bool(snap and snap.available)
        self._rpm_available = bool(rpm and rpm.available)
        self.provider_versions["Flatpak"] = flatpak.version if flatpak and flatpak.available else None
        self.provider_versions["Snap"] = snap.version if snap and snap.available else None
        self.provider_versions["RPM"] = rpm.version if rpm and rpm.available else None
        self.flatpak_card.setTitle(
            provider_title("Flatpak", self.provider_versions["Flatpak"])
        )
        self.snap_card.setTitle(
            provider_title("Snap", self.provider_versions["Snap"])
        )
        self.rpm_card.setTitle(
            provider_title("RPM", self.provider_versions["RPM"])
        )
        self._layout_overview_cards()
        self._position_info_buttons()
        self.button.setVisible(self._flatpak_available)
        self.snap_button.setVisible(self._snap_available)
        self.rpm_button.setVisible(self._rpm_available)
        messages = []
        for name, status in (("Flatpak", flatpak), ("Snap", snap), ("RPM", rpm)):
            if status and status.available:
                messages.append(f"{name} available ({status.version or 'version unknown'}).")
            else:
                messages.append(f"{name} unavailable: {status.reason if status else 'not detected'}.")
        self.provider_status.setText(" ".join(messages))
        self._update_scan_labels()
        self.update_overviews()

    def update_overviews(self) -> None:
        self.flatpak_overview.update_overview(flatpak_overview(
            self.items, scanned=self._scan_time["Flatpak"] is not None
        ))
        self.snap_overview.update_overview(snap_overview(
            self.snap_records, self.snap_storage,
            scanned=self._scan_time["Snap"] is not None
        ))
        self.rpm_overview.update_overview(rpm_overview(
            self.rpm_records, scanned=self._scan_time["RPM"] is not None
        ))
        if self._scan_time["RPM"] is not None:
            self.rpm_overview.legend.setText(
                "RPM packages (unclassified); complete measurements only"
            )

    def _update_scan_labels(self) -> None:
        """Separate provider availability, scan state and coverage."""
        for provider, button, label, available in (
            ("Flatpak", self.button, self.flatpak_scan_status, self._flatpak_available),
            ("Snap", self.snap_button, self.snap_scan_status, self._snap_available),
            ("RPM", self.rpm_button, self.rpm_scan_status, self._rpm_available),
        ):
            state = self._scan_state[provider]
            if state == "scanning":
                button.setText(f"Scanning {provider}…")
                status = self._scan_progress[provider] or "Scanning…"
            else:
                button.setText(f"{'Rescan' if self._scan_time[provider] else 'Scan'} {provider} installations")
                if state == "not_scanned":
                    status = "Not scanned"
                elif state == "cancelled":
                    status = "Cancelled"
                elif state == "failed":
                    status = "Scan failed"
                else:
                    status = ("Scanned with issues" if state == "issues" else "Scanned")
                if self._scan_time[provider] is not None:
                    status += (f" · {self._scan_count[provider]} records"
                               f" · at {self._scan_time[provider].strftime('%H:%M:%S')}")
                    if state == "cancelled":
                        status += " (previous results retained)"
            if provider == "RPM" and self._scan_time["RPM"] is not None:
                incomplete = sum(bool(record.issues) for record in self.rpm_records)
                if incomplete:
                    status += f" · {incomplete} incomplete"
            if provider == "Snap" and self._scan_time["Snap"] is not None:
                if self.snap_storage is None or any(
                    m.status not in (MeasurementStatus.MEASURED, MeasurementStatus.ABSENT)
                    for m in (self.snap_storage.cache, self.snap_storage.snapshots)
                ):
                    status += " · Partial coverage"
            if not available:
                status += " · Provider unavailable"
            label.setText(f"{provider}: {status}")
            label.setVisible(available or self._scan_time[provider] is not None)

    def _scan_completed(self, provider: str, count: int, issues: list[str]) -> None:
        self._scan_count[provider] = count
        self._scan_time[provider] = datetime.now().astimezone()
        self._scan_progress[provider] = ""
        self._scan_state[provider] = ("failed" if any(
            issue.startswith(("Scan failed:", "Snap scan failed:", "RPM scan failed:")) for issue in issues
        ) else "issues" if issues else "scanned")
        self._update_scan_labels()

    def start_rpm_scan(self) -> None:
        if not self._rpm_available or any(
            worker is not None and worker.isRunning()
            for worker in (self.worker, self.snap_worker, self.rpm_worker)
        ):
            return
        for button in (self.button, self.snap_button, self.rpm_button):
            button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self._scan_state["RPM"] = "scanning"
        self._scan_progress["RPM"] = "Reading RPM inventory… (read-only)"
        self._update_scan_labels()
        self.rpm_worker = RpmScanThread(self)
        self.rpm_worker.progress_changed.connect(self.show_rpm_progress)
        self.rpm_worker.finished_scan.connect(self.show_rpm_results)
        self.rpm_worker.scan_cancelled.connect(self.scan_was_cancelled)
        self.rpm_worker.finished.connect(self.finish_rpm_scan)
        self.rpm_worker.start()

    def show_rpm_progress(self, message: str) -> None:
        if self.rpm_worker and not self.rpm_worker._cancel.is_set():
            self._scan_progress["RPM"] = message + " (read-only)"
            self._update_scan_labels()

    def show_rpm_results(self, records, issues) -> None:
        self.rpm_records = records
        self._rpm_issues = list(issues)
        self._scan_completed("RPM", len(records), self._rpm_issues)
        self.update_overviews()
        self.render_inventory()

    def finish_rpm_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        for button in (self.button, self.snap_button, self.rpm_button):
            button.setEnabled(True)
        self._update_scan_labels()

    def open_snap_inventory(self) -> None:
        self.start_snap_scan()

    def start_snap_scan(self) -> None:
        if not self._snap_available or (self.snap_worker and self.snap_worker.isRunning()):
            return
        if self.worker and self.worker.isRunning():
            return
        if self.rpm_worker and self.rpm_worker.isRunning():
            return
        self.rpm_button.setEnabled(False)
        self.snap_button.setEnabled(False)
        self.button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        self._scan_progress["Snap"] = "Scanning revisions… (read-only)"
        self._scan_state["Snap"] = "scanning"
        self._update_scan_labels()
        self.snap_worker = SnapScanThread(self)
        self.snap_worker.progress_changed.connect(self.show_snap_progress)
        self.snap_worker.finished_scan.connect(self.show_snap_results)
        self.snap_worker.scan_cancelled.connect(self.scan_was_cancelled)
        self.snap_worker.finished.connect(self.finish_snap_scan)
        self.snap_worker.start()

    def show_snap_results(self, records, issues, storage) -> None:
        self.snap_records = records
        self._snap_issues = list(issues)
        self.snap_storage = storage
        self._scan_completed("Snap", len(records), self._snap_issues)
        self.update_overviews()
        self.render_inventory()

    def finish_snap_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        self.snap_button.setEnabled(True)
        self.button.setEnabled(True)
        self.rpm_button.setEnabled(True)
        self._update_scan_labels()

    def start_scan(self) -> None:
        if not self._flatpak_available:
            return
        if self.worker and self.worker.isRunning():
            return
        if self.snap_worker and self.snap_worker.isRunning():
            return
        if self.rpm_worker and self.rpm_worker.isRunning():
            return
        self.rpm_button.setEnabled(False)
        self.snap_button.setEnabled(False)
        self.rpm_button.setEnabled(False)
        self.button.setEnabled(False)
        self._scan_progress["Flatpak"] = "Scanning applications and user data… (read-only)"
        self._scan_state["Flatpak"] = "scanning"
        self._update_scan_labels()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.progress.show()
        # Detailed progress belongs to the Flatpak status line.
        self.worker = ScanThread(self)
        self.worker.progress_changed.connect(self.show_progress)
        self.worker.finished_scan.connect(self.show_results)
        self.worker.scan_cancelled.connect(self.scan_was_cancelled)
        self.worker.finished.connect(self.finish_scan)
        self.worker.start()

    def cancel_scan(self) -> None:
        if self.rpm_worker and self.rpm_worker.isRunning():
            self.rpm_worker.cancel()
            self.cancel_button.setEnabled(False)
        if self.snap_worker and self.snap_worker.isRunning():
            self.snap_worker.cancel()
            self.cancel_button.setEnabled(False)
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.info.setText("Cancelling scan… waiting for current operation.")

    def scan_was_cancelled(self) -> None:
        provider = next((name for name in ("RPM", "Snap", "Flatpak")
                         if self._scan_state[name] == "scanning"), "Flatpak")
        self._scan_state[provider] = "cancelled"
        self._scan_progress[provider] = ""
        self._update_scan_labels()
        # Keep the last completed results rather than showing partial data.
        self.info.setText(
            "Scan cancelled. Previous results retained; no files modified. "
            + (self._explore_hint() if self.items else "")
        )

    def show_progress(self, message: str) -> None:
        if self.worker and not self.worker._cancel.is_set():
            self._scan_progress["Flatpak"] = message + " (read-only)"
            self._update_scan_labels()

    def show_snap_progress(self, message: str) -> None:
        if self.snap_worker and not self.snap_worker._cancel.is_set():
            self._scan_progress["Snap"] = message + " (read-only)"
            self._update_scan_labels()

    def finish_scan(self) -> None:
        self.cancel_button.hide()
        self.progress.hide()
        self.button.setEnabled(True)
        self.snap_button.setEnabled(True)
        self.rpm_button.setEnabled(True)
        self._update_scan_labels()

    @staticmethod
    def _explore_hint() -> str:
        return ("Double-click an application to explore user data, or a runtime "
                "to examine shared dependencies.")

    def show_results(self, items: list[Item], issues: list[str]) -> None:
        self.items = items
        self._flatpak_issues = list(issues)
        self._scan_completed("Flatpak", len(items), self._flatpak_issues)
        self.update_overviews()
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
                        (category == "Shared components" and kind not in ("app", "rpm")) or
                        (category == "RPM packages" and kind == "rpm")))
            self.table.setRowHidden(row, not visible)

    def render_inventory(self) -> None:
        rows = combine(self.items, self.snap_records, self.rpm_records)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for row, record in enumerate(rows):
            values = [record.kind, record.identifier, record.reference, record.scope,
                      record.installed, record.user_data, record.app_total,
                      record.runtime, record.path, record.provider]
            for col, value in enumerate(values):
                if col in (4, 5, 6):
                    # Keep a single item subclass per numeric column. Mixing
                    # QTableWidgetItem and SizeCell causes Qt's comparison
                    # dispatch to recurse when sorting missing values.
                    cell = SizeCell(value)
                    if value is None:
                        cell.setText("Not applicable" if
                                     record.kind != "app" and col in (5, 6)
                                     else "Unknown")
                else:
                    cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole + 1, record.index)
                cell.setData(Qt.ItemDataRole.UserRole + 2, record.provider)
                self.table.setItem(row, col, cell)
            source = self.table.item(row, 9)
            # Only the marker is colored. Text and row selection remain
            # controlled by the active Qt/KDE palette (including dark mode).
            source.setText(record.provider)
            marker = QPixmap(9, 16)
            marker.fill(Qt.GlobalColor.transparent)
            from PySide6.QtGui import QPainter
            painter = QPainter(marker)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#278b89" if record.provider == "Flatpak"
                                    else "#8b78bd" if record.provider == "RPM" else "#bf7837"))
            painter.drawRoundedRect(1, 1, 7, 14, 2, 2)
            painter.end()
            source.setIcon(QIcon(marker))
            source.setToolTip(record.provider + " package manager")
        self.table.setSortingEnabled(True)
        self.table.sortItems(6, Qt.SortOrder.DescendingOrder)
        self.apply_filters()
        message = (f"{len(self.items)} Flatpak records; {len(self.snap_records)} "
                   "Snap revisions. Shared components excluded from application "
                   "totals; unknown measurements are not zero. Read-only.")
        issues = self._flatpak_issues + self._snap_issues + self._rpm_issues
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
            QMessageBox.information(
                self, "Snap inventory",
                f"{record.reference} ({record.metadata.get('state', 'unknown')})\\n"
                "Snap dependency navigation is not implemented yet.\\n"
                "No files modified."
            )
            return
        if provider == "RPM":
            record = self.rpm_records[original_index]
            dialog = RpmDependencyDialog(record.reference, self)
            dialog.measurements_by_reference = {
                item.reference: item for item in self.rpm_records
            }
            detail_button = QPushButton("Show selected package measurement")
            detail_button.clicked.connect(dialog.show_measurement)
            dialog.layout().insertWidget(2, detail_button)
            dialog.exec()
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
