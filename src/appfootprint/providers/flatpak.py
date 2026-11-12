"""Compatibility adapter for the existing, tested Flatpak scanner.

The Qt UI continues to consume scanner.Item for PR #13. This adapter lets
future providers use the neutral inventory contract without changing the
Flatpak scanner or its runtime/extension behavior.
"""
from __future__ import annotations

from .. import scanner
from ..inventory import (
    EvidenceLevel, InventoryRecord, MeasurementStatus,
    PackageKind, StorageMeasurement, StorageRole,
)


def _measurement(role: StorageRole, value: int | None, path: str,
                 *, absent: bool = False, applicable: bool = True) -> StorageMeasurement:
    if not applicable:
        status = MeasurementStatus.NOT_APPLICABLE
    elif value is not None:
        status = MeasurementStatus.MEASURED
    elif absent:
        status = MeasurementStatus.ABSENT
    else:
        status = MeasurementStatus.ERROR
    return StorageMeasurement(
        role=role, status=status, allocated_bytes=value,
        path=path, evidence=EvidenceLevel.CONFIRMED if value is not None else EvidenceLevel.UNKNOWN,
        reason="Allocated file blocks, not guaranteed uniquely reclaimable"
               if value is not None else "No reliable measurement",
    )


def from_flatpak_item(item: scanner.Item) -> InventoryRecord:
    kind = PackageKind.APPLICATION if item.kind == "app" else PackageKind.RUNTIME
    direct_role = StorageRole.DIRECT if kind == PackageKind.APPLICATION else StorageRole.SHARED
    measurements = [_measurement(direct_role, item.allocated_bytes, item.location)]
    if kind == PackageKind.APPLICATION:
        # The legacy scanner uses 0 for absent ~/.var/app data and None for
        # unreadable data. Preserve this distinction rather than guessing.
        measurements.append(_measurement(StorageRole.USER, item.user_data_bytes,
                                         item.user_data_path))
    return InventoryRecord(
        provider="flatpak", identifier=item.app_id, reference=item.ref,
        scope=item.installation, kind=kind, measurements=tuple(measurements),
        dependencies=(item.runtime,) if item.runtime else (),
        issues=tuple(item.errors),
        metadata={"flatpak_metadata": item.metadata} if item.metadata else {},
    )


class FlatpakProvider:
    name = "flatpak"

    def scan(self, progress=None, cancelled=None) -> tuple[list[InventoryRecord], list[str]]:
        items, issues = scanner.scan(progress=progress, cancelled=cancelled)
        return [from_flatpak_item(item) for item in items], issues
