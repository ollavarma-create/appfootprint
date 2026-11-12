"""Package-manager-neutral inventory contracts.

This layer describes evidence, not physical reclaimability. It does not
perform I/O, execute commands or request elevated privileges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol, TypeAlias


class PackageKind(str, Enum):
    APPLICATION = "app"
    RUNTIME = "runtime"
    LIBRARY = "library"
    EXTENSION = "extension"
    OTHER = "other"


class EvidenceLevel(str, Enum):
    CONFIRMED = "confirmed"
    STRONG_MATCH = "strong_match"
    POSSIBLE_MATCH = "possible_match"
    UNKNOWN = "unknown"


class MeasurementStatus(str, Enum):
    MEASURED = "measured"
    ABSENT = "absent"
    INACCESSIBLE = "inaccessible"
    ERROR = "error"
    NOT_APPLICABLE = "not_applicable"


class StorageRole(str, Enum):
    DIRECT = "direct"
    SHARED = "shared"
    USER = "user"


@dataclass(frozen=True)
class StorageMeasurement:
    role: StorageRole
    status: MeasurementStatus
    allocated_bytes: int | None = None
    path: str = ""
    evidence: EvidenceLevel = EvidenceLevel.UNKNOWN
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status == MeasurementStatus.MEASURED:
            if self.allocated_bytes is None or self.allocated_bytes < 0:
                raise ValueError("Measured storage requires nonnegative allocated bytes")
        elif self.allocated_bytes is not None:
            raise ValueError("Only measured storage may have allocated bytes")


@dataclass(frozen=True)
class InventoryRecord:
    provider: str
    identifier: str
    reference: str
    scope: str
    kind: PackageKind
    measurements: tuple[StorageMeasurement, ...] = ()
    dependencies: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        """Do not conflate identical package IDs from different providers/scopes."""
        return (self.provider, self.reference, self.scope)


Progress: TypeAlias = Callable[[str], None]
Cancellation: TypeAlias = Callable[[], bool]


class InventoryProvider(Protocol):
    """Contract for future Snap, RPM and AppImage adapters.

    A provider must report missing tools as issues, not require the caller
    to install a package manager. Implementations must remain read-only.
    """
    name: str

    def scan(
        self,
        progress: Progress | None = None,
        cancelled: Cancellation | None = None,
    ) -> tuple[list[InventoryRecord], list[str]]:
        ...


def measured_total(record: InventoryRecord, roles: set[StorageRole]) -> int | None:
    """Sum only known measurements, never silently treat unknown as zero.

    This is an accounting sum, *not* an estimate of reclaimable physical bytes.
    Shared dependencies must not be added to per-app totals.
    """
    selected = [m for m in record.measurements if m.role in roles]
    if not selected or any(m.status not in (MeasurementStatus.MEASURED, MeasurementStatus.ABSENT,
                                            MeasurementStatus.NOT_APPLICABLE) for m in selected):
        return None
    return sum(m.allocated_bytes or 0 for m in selected)
