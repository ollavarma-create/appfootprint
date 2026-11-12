"""Conservative, provider-scoped summaries of *reported* measurements.

A coverage fraction counts known targets, NOT the fraction of disk bytes found.
Storage sums are accounting indicators, not unique or reclaimable physical bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
from .inventory import InventoryRecord, MeasurementStatus, StorageRole
from .scanner import Item
from .providers.snap_storage import SnapStorage


@dataclass(frozen=True)
class ProviderOverview:
    provider: str
    application_bytes: int
    shared_bytes: int
    measured_targets: int
    unknown_targets: int
    absent_targets: int
    scanned: bool

    @property
    def known_targets(self) -> int:
        return self.measured_targets + self.unknown_targets + self.absent_targets

    @property
    def partial(self) -> bool:
        return self.unknown_targets > 0

    @property
    def measured_bytes(self) -> int:
        return self.application_bytes + self.shared_bytes


def flatpak_overview(items: list[Item], *, scanned: bool) -> ProviderOverview:
    apps = shared = measured = unknown = absent = 0
    for item in items:
        # Every listed installation is a target, even when its size is unknown.
        if item.allocated_bytes is None:
            unknown += 1
        else:
            measured += 1
            if item.kind == "app":
                apps += item.allocated_bytes
            else:
                shared += item.allocated_bytes
        if item.kind == "app":
            if item.user_data_bytes is None:
                unknown += 1
            else:
                measured += 1
                apps += item.user_data_bytes
    return ProviderOverview("Flatpak", apps, shared, measured, unknown, absent, scanned)


def snap_overview(records: list[InventoryRecord], storage: SnapStorage | None,
                  *, scanned: bool) -> ProviderOverview:
    apps = shared = measured = unknown = absent = 0

    def account(status: MeasurementStatus, size: int | None,
                role: str) -> None:
        nonlocal apps, shared, measured, unknown, absent
        if status == MeasurementStatus.MEASURED and size is not None:
            measured += 1
            if role == "app":
                apps += size
            elif role == "shared":
                shared += size
        elif status == MeasurementStatus.ABSENT:
            absent += 1
        elif status != MeasurementStatus.NOT_APPLICABLE:
            unknown += 1

    for record in records:
        for m in record.measurements:
            role = "shared" if record.kind.value != "app" else "app"
            account(m.status, m.allocated_bytes, role)
    # These targets affect coverage but must NOT be added to the footprint bar.
    if scanned:
        if storage is None:
            unknown += 2
        else:
            for m in (storage.cache, storage.snapshots):
                account(m.status, m.allocated_bytes, "other")
    return ProviderOverview("Snap", apps, shared, measured, unknown, absent, scanned)


def rpm_overview(records: list[InventoryRecord], *, scanned: bool) -> ProviderOverview:
    """Count only complete RPM package measurements; unknown bytes stay unknown.

    RPM package kinds are unclassified. The shared slot represents the
    unclassified installed-package bucket, NOT known shared dependencies.
    """
    measured = unknown = absent = allocated = 0
    for record in records:
        measurement = next((m for m in record.measurements
                            if m.role == StorageRole.DIRECT), None)
        if measurement is None:
            unknown += 1
        elif measurement.status == MeasurementStatus.MEASURED and measurement.allocated_bytes is not None:
            measured += 1
            allocated += measurement.allocated_bytes
        elif measurement.status == MeasurementStatus.ABSENT:
            absent += 1
        else:
            unknown += 1
    return ProviderOverview("RPM", 0, allocated, measured, unknown, absent, scanned)
