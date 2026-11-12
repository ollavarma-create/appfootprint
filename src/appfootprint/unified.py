"""Provider-neutral presentation rows for the combined inventory."""
from __future__ import annotations

from dataclasses import dataclass
from .inventory import InventoryRecord, MeasurementStatus, StorageRole
from .scanner import Item


@dataclass(frozen=True)
class UnifiedRow:
    provider: str
    index: int
    kind: str
    identifier: str
    reference: str
    scope: str
    installed: int | None
    user_data: int | None
    app_total: int | None
    runtime: str
    path: str


def combine(flatpaks: list[Item], snaps: list[InventoryRecord],
            rpms: list[InventoryRecord] = ()) -> list[UnifiedRow]:
    rows = []
    for index, item in enumerate(flatpaks):
        total = None
        if item.kind == "app" and any(v is not None for v in (item.allocated_bytes, item.user_data_bytes)):
            total = (item.allocated_bytes or 0) + (item.user_data_bytes or 0)
        rows.append(UnifiedRow(
            "Flatpak", index, item.kind, item.app_id, item.ref, item.installation,
            item.allocated_bytes, item.user_data_bytes if item.kind == "app" else None,
            total, item.runtime if item.kind == "app" else "—",
            item.location + (" | " if item.location and item.errors else "") + "; ".join(item.errors)))
    for index, record in enumerate(snaps):
        image = next((m for m in record.measurements
                      if m.role in (StorageRole.DIRECT, StorageRole.SHARED)), None)
        users = [m for m in record.measurements if m.role == StorageRole.USER]
        image_bytes = image.allocated_bytes if image and image.status == MeasurementStatus.MEASURED else None
        user_bytes = (sum(m.allocated_bytes or 0 for m in users)
                      if users and all(m.status in (MeasurementStatus.MEASURED, MeasurementStatus.ABSENT)
                                       for m in users) else None)
        total = (image_bytes + user_bytes if record.kind.value == "app"
                 and image_bytes is not None and user_bytes is not None else None)
        rows.append(UnifiedRow(
            "Snap", index, record.kind.value, record.identifier, record.reference,
            record.scope, image_bytes, user_bytes, total, "—", image.path if image else ""))
    for index, record in enumerate(rpms):
        measurement = next((m for m in record.measurements
                            if m.role == StorageRole.DIRECT), None)
        complete = (measurement is not None and
                    measurement.status == MeasurementStatus.MEASURED)
        installed = measurement.allocated_bytes if complete else None
        # RPM's known subtotal is diagnostic only, never a complete size.
        detail = ("Complete package measurement" if complete else
                  "; ".join(record.issues) or "Unknown package measurement")
        rows.append(UnifiedRow(
            "RPM", index, "rpm", record.identifier, record.reference,
            record.scope, installed, None, None, "—", detail))
    return rows
