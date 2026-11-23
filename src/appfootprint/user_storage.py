"""Read-only, bounded-scope hidden home-directory inventory.

Directory measurements are independent observations, not additive with
Flatpak or other provider totals. Never follow symlinks or cross mountpoints.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Callable

from .scanner import check_cancel

# Labels are explanatory only; discovery never depends on this mapping.
KNOWN_DIRECTORIES = {
    ".cache": "Cache (mixed applications)",
    ".config": "Configuration (mixed applications)",
    ".local": "Local application data (mixed)",
    ".var": "Flatpak and other application data",
    ".rustup": "Rust toolchains",
    ".cargo": "Cargo tools and cache",
    ".npm": "npm cache and metadata",
    ".gradle": "Gradle cache and metadata",
    ".m2": "Maven dependencies and configuration",
}


@dataclass(frozen=True)
class UserStorageEntry:
    label: str
    path: str
    status: str  # measured, absent, incomplete, inaccessible, error
    allocated_bytes: int | None
    known_allocated_bytes: int
    files: int
    skipped: int
    reason: str = ""


def _measure(root: Path, cancelled: Callable[[], bool] | None):
    total = files = skipped = 0
    reasons: set[str] = set()
    seen: set[tuple[int, int]] = set()
    pending = [root]
    root_dev = None
    while pending:
        check_cancel(cancelled)
        path = pending.pop()
        try:
            info = path.lstat()
        except OSError as exc:
            skipped += 1
            reasons.add(type(exc).__name__)
            continue
        if root_dev is None:
            root_dev = info.st_dev
        if info.st_dev != root_dev:
            skipped += 1
            reasons.add("different filesystem")
            continue
        key = (info.st_dev, info.st_ino)
        if key in seen:
            continue
        seen.add(key)
        total += info.st_blocks * 512
        files += 1
        if not stat.S_ISDIR(info.st_mode):
            continue
        try:
            with os.scandir(path) as listing:
                children = [Path(item.path) for item in listing]
        except OSError as exc:
            skipped += 1
            reasons.add(type(exc).__name__)
            continue
        pending.extend(children)
    return total, files, skipped, ", ".join(sorted(reasons))


def scan_user_storage(
    home: Path | None = None,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[UserStorageEntry], list[str]]:
    home = Path.home() if home is None else Path(home)
    entries: list[UserStorageEntry] = []
    issues: list[str] = []
    try:
        # Snapshot only the immediate children of home; never follow links.
        with os.scandir(home) as listing:
            candidates = sorted((Path(item.path) for item in listing
                                 if item.name.startswith(".") and item.name not in (".", "..")),
                                key=lambda path: path.name)
    except OSError as exc:
        return [], [f"Cannot list home directory: {exc}"]
    for path in candidates:
        check_cancel(cancelled)
        try:
            info = path.lstat()
        except OSError as exc:
            issues.append(f"{path.name}: {exc}")
            continue
        # Only actual directories qualify. Dotfiles and symlinks are not traversed.
        if not stat.S_ISDIR(info.st_mode):
            continue
        if progress:
            progress(f"Measuring {path.name}…")
        label = KNOWN_DIRECTORIES.get(path.name, "Unidentified hidden directory")
        known, files, skipped, reason = _measure(path, cancelled)
        entries.append(UserStorageEntry(
            label, str(path), "incomplete" if skipped else "measured",
            None if skipped else known, known, files, skipped, reason))
    check_cancel(cancelled)
    return entries, issues
