"""Provider-neutral tests run without Flatpak, Qt or an installed application."""
import pytest

from appfootprint.inventory import (
    EvidenceLevel, InventoryRecord, MeasurementStatus, PackageKind,
    StorageMeasurement, StorageRole, measured_total,
)
from appfootprint.providers.flatpak import FlatpakProvider, from_flatpak_item
from appfootprint.scanner import Item


def test_measurement_requires_valid_status_and_bytes():
    with pytest.raises(ValueError):
        StorageMeasurement(StorageRole.USER, MeasurementStatus.MEASURED)
    with pytest.raises(ValueError):
        StorageMeasurement(StorageRole.USER, MeasurementStatus.INACCESSIBLE, 0)
    with pytest.raises(ValueError):
        StorageMeasurement(StorageRole.USER, MeasurementStatus.MEASURED, -1)


def test_unknown_not_silently_counted_as_zero():
    record = InventoryRecord(
        "rpm", "example", "example-1", "system", PackageKind.APPLICATION,
        (StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.MEASURED, 4096),
         StorageMeasurement(StorageRole.USER, MeasurementStatus.INACCESSIBLE)),
    )
    assert measured_total(record, {StorageRole.DIRECT, StorageRole.USER}) is None
    assert measured_total(record, {StorageRole.DIRECT}) == 4096


def test_shared_not_part_of_application_total():
    record = InventoryRecord(
        "flatpak", "app", "app/x86_64/stable", "system", PackageKind.APPLICATION,
        (StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.MEASURED, 1024),
         StorageMeasurement(StorageRole.SHARED, MeasurementStatus.MEASURED, 8192),
         StorageMeasurement(StorageRole.USER, MeasurementStatus.MEASURED, 2048)),
    )
    assert measured_total(record, {StorageRole.DIRECT, StorageRole.USER}) == 3072


def test_provider_and_scope_part_of_identity():
    def record(provider, scope):
        return InventoryRecord(provider, "app", "app/x86_64/stable", scope,
                               PackageKind.APPLICATION)
    assert len({record("flatpak", "user").key, record("flatpak", "system").key,
                record("snap", "system").key}) == 3


def test_flatpak_adapter_preserves_runtime_and_user_data():
    app = Item("org.example.App", "app/org.example.App/x86_64/stable",
               "system", "app", allocated_bytes=2048,
               user_data_bytes=0, runtime="org.kde.Platform/x86_64/6.10")
    result = from_flatpak_item(app)
    assert result.dependencies == ("org.kde.Platform/x86_64/6.10",)
    assert result.measurements[1].status == MeasurementStatus.MEASURED
    assert result.measurements[1].allocated_bytes == 0
    runtime = Item("org.kde.Platform", "org.kde.Platform/x86_64/6.10",
                   "system", "runtime", allocated_bytes=8192)
    rt = from_flatpak_item(runtime)
    assert rt.measurements[0].role == StorageRole.SHARED
    assert len(rt.measurements) == 1


def test_provider_delegates_to_existing_scanner(monkeypatch):
    from appfootprint import scanner
    item = Item("example", "app/example/x86_64/stable", "user", "app")
    monkeypatch.setattr(scanner, "scan", lambda progress=None, cancelled=None: ([item], ["warning"]))
    records, issues = FlatpakProvider().scan()
    assert len(records) == 1
    assert issues == ["warning"]
    assert records[0].provider == "flatpak"
