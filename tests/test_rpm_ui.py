"""RPM rows retain unknown sizes and never imply application classification."""
from appfootprint.inventory import (
    InventoryRecord, MeasurementStatus, PackageKind, StorageMeasurement, StorageRole,
)
from appfootprint.unified import combine


def test_rpm_rows_complete_and_partial():
    complete = InventoryRecord(
        "rpm", "one", "one-1.x86_64", "system", PackageKind.OTHER,
        measurements=(StorageMeasurement(
            StorageRole.DIRECT, MeasurementStatus.MEASURED, 4096),),
    )
    partial = InventoryRecord(
        "rpm", "two", "two-1.x86_64", "system", PackageKind.OTHER,
        measurements=(StorageMeasurement(
            StorageRole.DIRECT, MeasurementStatus.ERROR),),
        issues=("File measurement incomplete",),
        metadata={"known_allocated_bytes": "8192"},
    )
    rows = combine([], [], [complete, partial])
    assert [row.provider for row in rows] == ["RPM", "RPM"]
    assert [row.kind for row in rows] == ["rpm", "rpm"]
    assert rows[0].installed == 4096
    assert rows[1].installed is None
    assert all(row.app_total is None and row.user_data is None for row in rows)
    assert "incomplete" in rows[1].path
