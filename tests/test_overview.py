"""Provider-scoped overview accounting and coverage safeguards."""
from appfootprint.overview import flatpak_overview, snap_overview, rpm_overview
from appfootprint.scanner import Item
from appfootprint.inventory import (
    InventoryRecord, PackageKind, StorageMeasurement, StorageRole, MeasurementStatus,
)
from appfootprint.providers.snap_storage import SnapStorage


def test_flatpak_overview_keeps_shared_separate_and_unknown_visible():
    items = [
        Item("org.example.App", "app/example", "system", "app",
             allocated_bytes=1000, user_data_bytes=None),
        Item("org.example.Runtime", "runtime/example", "system", "runtime",
             allocated_bytes=2000),
    ]
    result = flatpak_overview(items, scanned=True)
    assert (result.application_bytes, result.shared_bytes) == (1000, 2000)
    assert (result.measured_targets, result.unknown_targets) == (2, 1)
    assert result.partial
    assert result.measured_bytes == 3000


def test_snap_overview_does_not_add_cache_or_snapshot_bytes_to_bar():
    record = InventoryRecord(
        "snap", "core24", "core24/2307", "system", PackageKind.RUNTIME,
        measurements=(StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED, 2048),),
    )
    storage = SnapStorage(
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED, 999999),
        StorageMeasurement(StorageRole.SHARED, MeasurementStatus.INACCESSIBLE, reason="protected"),
    )
    result = snap_overview([record], storage, scanned=True)
    assert result.shared_bytes == 2048
    assert result.application_bytes == 0
    assert result.measured_targets == 2
    assert result.unknown_targets == 1
    assert result.partial


def test_no_scans_does_not_claim_coverage():
    assert not flatpak_overview([], scanned=False).scanned
    assert not snap_overview([], None, scanned=False).scanned
    result = snap_overview([], None, scanned=True)
    assert result.unknown_targets == 2
    assert result.measured_bytes == 0


def test_rpm_overview_excludes_partial_known_subtotals():
    complete = InventoryRecord(
        "rpm", "one", "one-1.x86_64", "system", PackageKind.OTHER,
        measurements=(StorageMeasurement(
            StorageRole.DIRECT, MeasurementStatus.MEASURED, 4096),),
    )
    partial = InventoryRecord(
        "rpm", "two", "two-1.x86_64", "system", PackageKind.OTHER,
        measurements=(StorageMeasurement(
            StorageRole.DIRECT, MeasurementStatus.ERROR, reason="missing file"),),
        issues=("missing file",),
        metadata={"known_allocated_bytes": "9999999"},
    )
    overview = rpm_overview([complete, partial], scanned=True)
    assert overview.measured_bytes == 4096
    assert overview.application_bytes == 0
    assert (overview.measured_targets, overview.unknown_targets) == (1, 1)
    assert overview.partial
