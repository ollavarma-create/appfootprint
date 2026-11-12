"""Read-only Snap inventory, including inactive revisions and shared bases.

Snap packages are compressed squashfs files. Measure the backing .snap file,
never its mounted /snap/<name>/<revision> tree (which would double-count).
No root access, snap mutations, or automatic cleanup.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable

from ..inventory import (EvidenceLevel, InventoryRecord, MeasurementStatus,
                         PackageKind, StorageMeasurement, StorageRole)
from ..scanner import ScanCancelled, allocated_size, check_cancel


@dataclass(frozen=True)
class SnapEntry:
    name: str
    version: str
    revision: str
    notes: str

    @property
    def active(self) -> bool:
        return "disabled" not in self.notes.split(",")


def parse_snap_list(output: str) -> list[SnapEntry]:
    """Parse snap list --all's aligned, human-readable columns.

    Snap does not guarantee a JSON interface for 'list'. Separate on 2+
    spaces; version/publisher may contain a single space.
    """
    result: list[SnapEntry] = []
    for line in output.splitlines():
        if not line.strip() or line.lstrip().startswith("Name "):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 6:
            continue
        name, version, revision = parts[:3]
        if not revision.isdigit():
            continue
        result.append(SnapEntry(name, version, revision, parts[-1]))
    return result


def _size(path: Path, cancelled: Callable[[], bool] | None) -> StorageMeasurement:
    if not path.exists():
        return StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.ABSENT,
                                  path=str(path), reason="Backing snap image not found")
    try:
        # st_blocks includes the allocated blocks of the compressed image.
        value = allocated_size(path, cancelled)
        return StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.MEASURED,
                                  allocated_bytes=value, path=str(path),
                                  evidence=EvidenceLevel.CONFIRMED,
                                  reason="Compressed snap image; not mounted contents")
    except ScanCancelled:
        raise
    except PermissionError as exc:
        return StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.INACCESSIBLE,
                                  path=str(path), reason=str(exc))
    except OSError as exc:
        return StorageMeasurement(StorageRole.DIRECT, MeasurementStatus.ERROR,
                                  path=str(path), reason=str(exc))


def _user_size(path: Path, cancelled: Callable[[], bool] | None) -> StorageMeasurement:
    if not path.exists():
        return StorageMeasurement(StorageRole.USER, MeasurementStatus.ABSENT,
                                  path=str(path), reason="User-data path absent")
    try:
        value = allocated_size(path, cancelled)
        return StorageMeasurement(StorageRole.USER, MeasurementStatus.MEASURED,
                                  allocated_bytes=value, path=str(path),
                                  evidence=EvidenceLevel.CONFIRMED,
                                  reason="Allocated blocks; not guaranteed reclaimable")
    except ScanCancelled:
        raise
    except PermissionError as exc:
        return StorageMeasurement(StorageRole.USER, MeasurementStatus.INACCESSIBLE,
                                  path=str(path), reason=str(exc))
    except OSError as exc:
        return StorageMeasurement(StorageRole.USER, MeasurementStatus.ERROR,
                                  path=str(path), reason=str(exc))


def _classification(name: str, notes: str) -> tuple[PackageKind, str]:
    """Distinguish Snap-declared bases from *inferred* shared content snaps.

    snap list does not expose content interface declarations. These familiar
    naming families are heuristics and must be labelled as such.
    """
    tokens = set(notes.split(","))
    if "base" in tokens or name in {"core", "core18", "core20", "core22",
                                    "core24", "core26", "snapd", "bare"}:
        return PackageKind.RUNTIME, "declared_base_or_system"
    if (re.fullmatch(r"gnome-\d+-\d+", name) or
            re.fullmatch(r"mesa-\d+", name) or
            name == "gtk-common-themes"):
        return PackageKind.RUNTIME, "inferred_shared_content"
    return PackageKind.APPLICATION, "unverified_application"


def _kind(name: str, notes: str) -> PackageKind:
    return _classification(name, notes)[0]


class SnapProvider:
    name = "snap"

    def __init__(self, image_dir: Path = Path("/var/lib/snapd/snaps"),
                 home: Path | None = None):
        self.image_dir = image_dir
        self.home = home if home is not None else Path.home()

    def scan(self, progress=None, cancelled=None) -> tuple[list[InventoryRecord], list[str]]:
        if not shutil.which("snap"):
            return [], ["Snap executable not found in PATH."]
        check_cancel(cancelled)
        try:
            completed = subprocess.run(["snap", "list", "--all"], text=True,
                                       capture_output=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as exc:
            return [], [f"Snap inventory unavailable: {exc}"]
        if completed.returncode:
            message = (completed.stderr or completed.stdout).strip()
            if "no snaps are installed" in message.casefold():
                return [], []
            return [], [f"Snap inventory unavailable: {message or 'command failed'}"]
        entries = parse_snap_list(completed.stdout)
        if completed.stdout.strip() and not entries and "Name " not in completed.stdout:
            return [], ["Unrecognized Snap inventory output; no records inferred."]
        records: list[InventoryRecord] = []
        for index, entry in enumerate(entries, 1):
            check_cancel(cancelled)
            if progress:
                progress(f"Scanning Snap {entry.name} revision {entry.revision} ({index}/{len(entries)})…")
            kind, classification = _classification(entry.name, entry.notes)
            image = self.image_dir / f"{entry.name}_{entry.revision}.snap"
            image_measure = _size(image, cancelled)
            if kind == PackageKind.RUNTIME:
                image_measure = StorageMeasurement(
                    StorageRole.SHARED, image_measure.status,
                    allocated_bytes=image_measure.allocated_bytes,
                    path=image_measure.path, evidence=image_measure.evidence,
                    reason=image_measure.reason)
            measurements = [image_measure]
            # User data is scoped to the current user's active revision and
            # common directory. Never count the same data in every revision.
            if entry.active and kind == PackageKind.APPLICATION:
                for path in (self.home / "snap" / entry.name / entry.revision,
                             self.home / "snap" / entry.name / "common"):
                    measurements.append(_user_size(path, cancelled))
            records.append(InventoryRecord(
                provider="snap", identifier=entry.name,
                reference=f"{entry.name}/{entry.revision}", scope="system",
                kind=kind, measurements=tuple(measurements),
                metadata={"version": entry.version, "revision": entry.revision,
                          "notes": entry.notes, "state": "active" if entry.active else "disabled",
                          "classification": classification},
            ))
        check_cancel(cancelled)
        return records, []
