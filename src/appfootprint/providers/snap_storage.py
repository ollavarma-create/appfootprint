"""Read-only Snap package-manager storage accounting.

Measure cache and snapshot directories independently of installed snap images.
Never cross filesystem boundaries, follow symlinks or infer reclaimable space.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Callable

from ..inventory import MeasurementStatus, StorageMeasurement, StorageRole, EvidenceLevel
from ..scanner import ScanCancelled, check_cancel


@dataclass(frozen=True)
class SnapStorage:
    cache: StorageMeasurement
    snapshots: StorageMeasurement


def measure_tree(path: Path, cancelled: Callable[[], bool] | None = None) -> StorageMeasurement:
    role = StorageRole.SHARED
    try:
        root = path.lstat()
    except FileNotFoundError:
        return StorageMeasurement(role, MeasurementStatus.ABSENT, path=str(path),
                                  reason="Directory not present")
    except PermissionError as exc:
        return StorageMeasurement(role, MeasurementStatus.INACCESSIBLE, path=str(path), reason=str(exc))
    except OSError as exc:
        return StorageMeasurement(role, MeasurementStatus.ERROR, path=str(path), reason=str(exc))
    if not stat.S_ISDIR(root.st_mode):
        return StorageMeasurement(role, MeasurementStatus.ERROR, path=str(path),
                                  reason="Expected a directory, not a file or symlink")
    total = 0
    pending = [path]
    seen = set()
    try:
        while pending:
            check_cancel(cancelled)
            current = pending.pop()
            info = current.lstat()
            if info.st_dev != root.st_dev or stat.S_ISLNK(info.st_mode):
                continue
            key = (info.st_dev, info.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += info.st_blocks * 512
            if stat.S_ISDIR(info.st_mode):
                with os.scandir(current) as children:
                    pending.extend(Path(child.path) for child in children)
    except ScanCancelled:
        raise
    except PermissionError as exc:
        return StorageMeasurement(role, MeasurementStatus.INACCESSIBLE, path=str(path),
                                  reason=f"Incomplete measurement: {exc}")
    except OSError as exc:
        return StorageMeasurement(role, MeasurementStatus.ERROR, path=str(path),
                                  reason=f"Incomplete measurement: {exc}")
    return StorageMeasurement(role, MeasurementStatus.MEASURED, allocated_bytes=total,
                              path=str(path), evidence=EvidenceLevel.CONFIRMED,
                              reason="Allocated blocks; not necessarily reclaimable")


def scan_storage(root: Path = Path("/var/lib/snapd"),
                 cancelled: Callable[[], bool] | None = None) -> SnapStorage:
    return SnapStorage(measure_tree(root / "cache", cancelled),
                       measure_tree(root / "snapshots", cancelled))
