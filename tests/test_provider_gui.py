"""Offscreen Qt tests for conditional provider UI."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from appfootprint import gui
from appfootprint.provider_detection import ProviderStatus


def test_provider_button_only_when_available(monkeypatch):
    app = QApplication.instance() or QApplication([])
    # Keep this deterministic and avoid starting real subprocesses.
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show()
    assert window.button.isHidden()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", False, "Not installed")
    })
    assert window.button.isHidden()
    assert "Not installed" in window.provider_status.text()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", True, "Available", "Flatpak 1.16")
    })
    assert window.button.isVisible()
    assert "Flatpak 1.16" in window.provider_status.text()
    window.close()


def test_scan_guard_when_unavailable(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.start_scan()
    assert window.worker is None
    window.close()


def test_guidance_follows_inventory_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    assert "Double-click" not in window.info.text()
    assert "No inventory yet" in window.info.text()
    window.show_results([], [])
    assert "Double-click" not in window.info.text()
    from appfootprint.scanner import Item
    item = Item(app_id="org.example.App", ref="app/org.example.App/x86_64/stable",
                installation="system", kind="app", allocated_bytes=1024,
                user_data_bytes=0)
    window.show_results([item], [])
    assert "Double-click" in window.info.text()
    window.scan_was_cancelled()
    assert "Previous results retained" in window.info.text()
    assert "Double-click" in window.info.text()
    window.close()


def test_snap_button_tracks_provider_availability(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show()
    assert window.snap_button.isHidden()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", True, "ok", "Flatpak 1.18"),
        "snap": ProviderStatus("snap", False, "Snap executable not found"),
    })
    assert window.snap_button.isHidden()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", True, "ok", "Flatpak 1.18"),
        "snap": ProviderStatus("snap", True, "ok", "snap 2.7"),
    })
    assert window.snap_button.isVisible()
    assert "Snap available" in window.provider_status.text()
    window.close()


def test_snap_dialog_empty_and_revision_rows():
    from appfootprint.inventory import (
        InventoryRecord, PackageKind, StorageMeasurement, MeasurementStatus, StorageRole,
    )
    app = QApplication.instance() or QApplication([])
    dialog = gui.SnapInventoryDialog()
    dialog.show_results([], [])
    assert "No Snap records" in dialog.status.text()
    record = InventoryRecord(
        "snap", "hello", "hello/42", "system", PackageKind.APPLICATION,
        measurements=(
            StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.MEASURED, 4096,
                               path="/var/lib/snapd/snaps/hello_42.snap"),
            StorageMeasurement(StorageRole.USER, MeasurementStatus.ABSENT),
        ),
        metadata={"state": "active", "version": "2.12"},
    )
    dialog.show_results([record], [])
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "active"
    assert "compressed backing files" in dialog.status.text()
    dialog.close()


def test_snap_dialog_protected_storage_and_shared_data():
    from appfootprint.inventory import (
        InventoryRecord, PackageKind, StorageMeasurement, MeasurementStatus, StorageRole,
    )
    from appfootprint.providers.snap_storage import SnapStorage
    app = QApplication.instance() or QApplication([])
    dialog = gui.SnapInventoryDialog()
    record = InventoryRecord(
        "snap", "core24", "core24/2307", "system", PackageKind.RUNTIME,
        measurements=(
            StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED,
                               4096, path="/var/lib/snapd/snaps/core24_2307.snap"),
        ),
        metadata={"state": "active", "version": "20261022"},
    )
    storage = SnapStorage(
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.INACCESSIBLE,
                           path="/var/lib/snapd/cache", reason="Permission denied"),
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.INACCESSIBLE,
                           path="/var/lib/snapd/snapshots", reason="Permission denied"),
    )
    dialog.show_results([record], [], storage)
    assert dialog.table.item(0, 5).text() == "Not applicable"
    summary = dialog.storage_summary.text()
    assert summary.count("Requires administrator access") == 2
    assert "does not request administrator privileges" in summary
    assert "Permission denied" not in summary
    assert "Partial inventory" in dialog.coverage.text()
    assert "No complete storage total" in dialog.coverage.text()
    dialog.close()


def test_unified_inventory_source_and_kind_filters(monkeypatch):
    from appfootprint.scanner import Item
    from appfootprint.inventory import (
        InventoryRecord, PackageKind, StorageMeasurement, MeasurementStatus, StorageRole,
    )
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show_results([
        Item(app_id="org.example.App", ref="app/example", installation="user",
             kind="app", allocated_bytes=4096, user_data_bytes=0)
    ], [])
    snap = InventoryRecord(
        "snap", "core24", "core24/2307", "system", PackageKind.RUNTIME,
        measurements=(StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED,
                                         8192, path="/var/lib/snapd/snaps/core24_2307.snap"),),
        metadata={"state": "active"},
    )
    window.show_snap_results([snap], [], None)
    assert window.table.rowCount() == 2
    assert {window.table.item(i, 9).data(gui.Qt.ItemDataRole.UserRole + 2)
            for i in range(2)} == {"Flatpak", "Snap"}
    window.source_filter.setCurrentText("Snap")
    assert sum(not window.table.isRowHidden(i) for i in range(2)) == 1
    window.kind_filter.setCurrentText("Applications")
    assert all(window.table.isRowHidden(i) for i in range(2))
    window.source_filter.setCurrentText("All")
    assert sum(not window.table.isRowHidden(i) for i in range(2)) == 1
    window.close()


def test_unified_size_columns_sort_with_unknown_and_not_applicable(monkeypatch):
    from appfootprint.scanner import Item
    from appfootprint.inventory import (
        InventoryRecord, PackageKind, StorageMeasurement, MeasurementStatus, StorageRole,
    )
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show_results([
        Item(app_id="org.example.App", ref="app/example", installation="user",
             kind="app", allocated_bytes=4096, user_data_bytes=0),
    ], [])
    shared = InventoryRecord(
        "snap", "core24", "core24/2307", "system", PackageKind.RUNTIME,
        measurements=(StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED,
                                         8192, path="/var/lib/snapd/snaps/core24_2307.snap"),),
    )
    window.show_snap_results([shared], [], None)
    for column in (4, 5, 6):
        for order in (gui.Qt.SortOrder.AscendingOrder, gui.Qt.SortOrder.DescendingOrder):
            window.table.sortItems(column, order)
        assert all(isinstance(window.table.item(row, column), gui.SizeCell)
                   for row in range(window.table.rowCount()))
    assert any(window.table.item(row, 5).text() == "Not applicable"
               for row in range(window.table.rowCount()))
    window.close()


def test_provider_scan_status_and_rescan_labels(monkeypatch):
    from appfootprint.provider_detection import ProviderStatus
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", True, "ok", "1.18"),
        "snap": ProviderStatus("snap", True, "ok", "2.78"),
    })
    assert "Not scanned" in window.flatpak_scan_status.text()
    assert "Not scanned" in window.snap_scan_status.text()
    window.show_results([], [])
    assert "Scanned" in window.flatpak_scan_status.text()
    assert "0 records" in window.flatpak_scan_status.text()
    assert "Rescan Flatpak" in window.button.text()
    assert "Not scanned" in window.snap_scan_status.text()
    window.show_snap_results([], [], None)
    assert "Partial coverage" in window.snap_scan_status.text()
    assert "Rescan Snap" in window.snap_button.text()
    window._scan_state["Snap"] = "scanning"
    window.scan_was_cancelled()
    assert "Cancelled" in window.snap_scan_status.text()
    assert "previous results retained" in window.snap_scan_status.text()
    window.close()


def test_provider_scan_with_issues_and_failed_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show_results([], ["some entries inaccessible"])
    assert "Scanned with issues" in window.flatpak_scan_status.text()
    window.show_results([], ["Scan failed: unavailable"])
    assert "Scan failed" in window.flatpak_scan_status.text()
    window.close()


def test_scan_progress_is_local_to_provider_status(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window._scan_state["Flatpak"] = "scanning"
    window._scan_state["Snap"] = "not_scanned"
    class Worker:
        class Cancel:
            def is_set(self):
                return False
        _cancel = Cancel()
    window.worker = Worker()
    window.show_progress("Scanning org.example.App (3/18)…")
    assert "org.example.App (3/18)" in window.flatpak_scan_status.text()
    assert "Not scanned" in window.snap_scan_status.text()
    assert "org.example.App" not in window.info.text()
    window.snap_worker = Worker()
    window._scan_state["Snap"] = "scanning"
    window.show_snap_progress("Scanning snap revision (2/6)…")
    assert "revision (2/6)" in window.snap_scan_status.text()
    assert "revision (2/6)" not in window.info.text()
    window.worker = None
    window.snap_worker = None
    window.close()


def test_overview_updates_per_provider_without_conflating_snap_storage(monkeypatch):
    from appfootprint.scanner import Item
    from appfootprint.inventory import StorageMeasurement, StorageRole, MeasurementStatus
    from appfootprint.providers.snap_storage import SnapStorage
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    assert "Not scanned" in window.flatpak_overview.heading.text()
    assert "Not scanned" in window.snap_overview.heading.text()
    window.show_results([
        Item("org.example.App", "app/example", "system", "app",
             allocated_bytes=4096, user_data_bytes=None)
    ], [])
    assert "Partial measurement" in window.flatpak_overview.coverage.text()
    assert "Not scanned" in window.snap_overview.heading.text()
    storage = SnapStorage(
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.INACCESSIBLE),
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.INACCESSIBLE),
    )
    window.show_snap_results([], [], storage)
    assert "2 unknown" in window.snap_overview.coverage.text()
    assert "0.0 B" in window.snap_overview.heading.text()
    window.close()


def test_provider_cards_adapt_and_hide_unavailable(monkeypatch):
    from appfootprint.provider_detection import ProviderStatus
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    statuses = {
        "flatpak": ProviderStatus("flatpak", True, "ok", "1.18"),
        "snap": ProviderStatus("snap", True, "ok", "2.78"),
    }
    window.providers_detected(statuses)
    assert window.overview_grid.indexOf(window.flatpak_card) >= 0
    assert window.overview_grid.indexOf(window.snap_card) >= 0
    assert window.button.parentWidget() is window.flatpak_card
    assert window.snap_button.parentWidget() is window.snap_card
    window.resize(1100, 700)
    assert window.overview_grid.itemAtPosition(0, 0).widget() is window.flatpak_card
    assert window.overview_grid.itemAtPosition(0, 1).widget() is window.snap_card
    window.resize(700, 700)
    assert window.overview_grid.itemAtPosition(1, 0).widget() is window.snap_card
    statuses["snap"] = ProviderStatus("snap", False, "missing", None)
    window.providers_detected(statuses)
    assert window.overview_grid.indexOf(window.snap_card) == -1
    assert window.overview_grid.indexOf(window.flatpak_card) >= 0
    window.close()
