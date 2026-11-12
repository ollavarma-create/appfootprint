"""Read-only RPM database inventory and conservative filesystem measurements.

Uses one RPM query, never DNF, sudo, or an RPM transaction. Counts only
regular files and symlinks (lstat); directories are excluded. A package's
known bytes are NOT an estimate of physical/reclaimable space.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import subprocess
from typing import Callable

from ..inventory import (EvidenceLevel, InventoryRecord, MeasurementStatus,
                         PackageKind, StorageMeasurement, StorageRole)
from ..scanner import ScanCancelled, check_cancel

_FIELD = "\x1f"
_FILE = "\x1e"
_RECORD = "\x1d"
# Query one snapshot of the installed RPM database, including per-package
# filename arrays. The control characters are record delimiters, not shell code.
_QUERY = (f"%{{NAME}}{_FIELD}%{{EPOCHNUM}}{_FIELD}%{{VERSION}}{_FIELD}"
          f"%{{RELEASE}}{_FIELD}%{{ARCH}}{_FIELD}"
          f"[%{{FILENAMES}}{_FILE}]{_RECORD}")


@dataclass(frozen=True)
class RpmEntry:
    name: str
    reference: str
    architecture: str
    paths: tuple[str, ...]


def parse_rpm_query(output: str) -> list[RpmEntry]:
    """Parse our own explicitly delimited query format; reject bad records."""
    entries = []
    for raw in output.split(_RECORD):
        if not raw:
            continue
        fields = raw.split(_FIELD, 5)
        if len(fields) != 6:
            raise ValueError("Malformed RPM inventory record")
        name, epoch, version, release, arch, file_field = fields
        if not all((name, version, release, arch)):
            raise ValueError("RPM inventory has missing identity fields")
        if any(c in name + version + release + arch for c in (_RECORD, _FIELD)):
            raise ValueError("RPM identity contains delimiter")
        epoch_prefix = "" if epoch in ("", "0", "(none)") else f"{epoch}:"
        reference = f"{name}-{epoch_prefix}{version}-{release}.{arch}"
        paths = tuple(p for p in file_field.split(_FILE) if p)
        if any(not p.startswith("/") for p in paths):
            raise ValueError(f"RPM returned a nonabsolute path for {name}")
        entries.append(RpmEntry(name, reference, arch, paths))
    return sorted(entries, key=lambda entry: entry.reference)


class RpmProvider:
    name = "rpm"

    def __init__(self, root: Path = Path("/"), *, rpm_command: str = "rpm"):
        # root is a test seam; production uses the real filesystem.
        self.root = root
        self.rpm_command = rpm_command

    def scan(self, progress: Callable[[str], None] | None = None,
             cancelled: Callable[[], bool] | None = None
             ) -> tuple[list[InventoryRecord], list[str]]:
        if not shutil.which(self.rpm_command):
            return [], ["RPM executable not found in PATH."]
        check_cancel(cancelled)
        try:
            completed = subprocess.run(
                [self.rpm_command, "-qa", "--queryformat", _QUERY],
                capture_output=True, timeout=120, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return [], [f"RPM inventory unavailable: {exc}"]
        check_cancel(cancelled)
        if completed.returncode:
            message = completed.stderr.decode("utf-8", "replace").strip()
            return [], [f"RPM inventory unavailable: {message or 'query failed'}"]
        try:
            entries = parse_rpm_query(completed.stdout.decode("utf-8", "surrogateescape"))
        except ValueError as exc:
            return [], [f"RPM inventory format error: {exc}"]

        # A path may be listed by more than one package. A hardlinked inode
        # may also have different paths. Never assign those bytes arbitrarily.
        path_owners: dict[str, int] = {}
        for entry in entries:
            for path in set(entry.paths):
                path_owners[path] = path_owners.get(path, 0) + 1
        inode_owners: dict[tuple[int, int], set[str]] = {}
        # Identity is the full installed NEVRA, not the display name.
        path_package_owners: dict[str, set[str]] = {}
        for entry in entries:
            for path in set(entry.paths):
                path_package_owners.setdefault(path, set()).add(entry.reference)
        path_stats: dict[str, os.stat_result | OSError] = {}
        for index, path in enumerate(path_owners):
            check_cancel(cancelled)
            try:
                resolved = self.root / path.lstrip("/")
                result = resolved.lstat()
                path_stats[path] = result
                if not stat.S_ISDIR(result.st_mode):
                    inode_owners.setdefault((result.st_dev, result.st_ino), set()).add(path)
            except OSError as exc:
                path_stats[path] = exc

        records = []
        for index, entry in enumerate(entries, 1):
            check_cancel(cancelled)
            if progress:
                progress(f"Scanning RPM {entry.name} ({index}/{len(entries)})…")
            known = missing = inaccessible = errors = multi_owned = shared_inode = 0
            internal_hardlinks = cross_package_hardlinks = 0
            allocated = 0
            seen_paths = set()
            counted_inodes: set[tuple[int, int]] = set()
            for path in entry.paths:
                check_cancel(cancelled)
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                result = path_stats[path]
                if isinstance(result, OSError):
                    if isinstance(result, FileNotFoundError):
                        missing += 1
                    elif isinstance(result, PermissionError):
                        inaccessible += 1
                    else:
                        errors += 1
                    continue
                if stat.S_ISDIR(result.st_mode):
                    continue  # Directory contents are not package-owned bytes.
                # Exclusive categories: if the exact path has multiple RPM
                # owners, report that first. Only otherwise classify a path
                # sharing its inode with another distinct path as a hardlink.
                if path_owners[path] > 1:
                    multi_owned += 1
                    continue
                inode_key = (result.st_dev, result.st_ino)
                inode_paths = inode_owners[inode_key]
                inode_packages = set().union(
                    *(path_package_owners[p] for p in inode_paths)
                )
                if len(inode_packages) > 1:
                    # An inode spanning different packages cannot be
                    # attributed exclusively to this package.
                    shared_inode += 1
                    cross_package_hardlinks += 1
                    continue
                if inode_key in counted_inodes:
                    # Same-package hardlinks occupy one inode: count once.
                    internal_hardlinks += 1
                    continue
                counted_inodes.add(inode_key)
                allocated += result.st_blocks * 512
                known += 1
            ambiguous = multi_owned + shared_inode
            incomplete = bool(missing or inaccessible or errors or ambiguous)
            status = (MeasurementStatus.INACCESSIBLE if inaccessible else
                      MeasurementStatus.ERROR if incomplete else
                      MeasurementStatus.MEASURED)
            measurement = StorageMeasurement(
                StorageRole.DIRECT, status,
                allocated_bytes=allocated if not incomplete else None,
                evidence=EvidenceLevel.CONFIRMED if not incomplete else EvidenceLevel.UNKNOWN,
                reason=("Allocated blocks for RPM-owned nondirectory files; not reclaimable"
                        if not incomplete else
                        "Incomplete file measurement; known-byte subtotal in metadata"),
            )
            issues = []
            if incomplete:
                issues.append(
                    f"File measurement incomplete: {missing} absent, "
                    f"{inaccessible} inaccessible, {errors} errors, "
                    f"{multi_owned} multi-owned paths, "
                    f"{shared_inode} cross-package shared-inode paths"
                )
            records.append(InventoryRecord(
                provider="rpm", identifier=entry.name, reference=entry.reference,
                scope="system", kind=PackageKind.OTHER,
                measurements=(measurement,), issues=tuple(issues),
                metadata={
                    "architecture": entry.architecture,
                    "file_count": str(len(seen_paths)),
                    "measured_files": str(known),
                    "absent_files": str(missing),
                    "inaccessible_files": str(inaccessible),
                    "error_files": str(errors),
                    "ambiguous_files": str(ambiguous),
                    "multi_owned_paths": str(multi_owned),
                    "shared_inode_paths": str(shared_inode),
                    "cross_package_hardlink_paths": str(cross_package_hardlinks),
                    "internal_hardlink_paths": str(internal_hardlinks),
                    "known_allocated_bytes": str(allocated),
                    "classification": "unclassified",
                    "measurement_method": "lstat.st_blocks * 512",
                },
            ))
        return records, []
