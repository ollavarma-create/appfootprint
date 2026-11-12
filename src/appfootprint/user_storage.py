"""Read-only, bounded-scope XDG user storage inventory.

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

TARGETS = (
    ("Cache", ".cache"),
    ("Configuration", ".config"),
    ("Application data", ".local/share"),
    ("Application state", ".local/state"),
    ("Flatpak user data", ".var/app"),
)


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
    for label, relative in TARGETS:
        check_cancel(cancelled)
        if progress:
            progress(f"Measuring {relative}…")
        path = home / relative
        try:
            info = path.lstat()
        except FileNotFoundError:
            entries.append(UserStorageEntry(label, str(path), "absent", 0, 0, 0, 0))
            continue
        except PermissionError as exc:
            entries.append(UserStorageEntry(label, str(path), "inaccessible", None, 0, 0, 1, str(exc)))
            continue
        except OSError as exc:
            entries.append(UserStorageEntry(label, str(path), "error", None, 0, 0, 1, str(exc)))
            continue
        if not stat.S_ISDIR(info.st_mode):
            entries.append(UserStorageEntry(label, str(path), "error", None, 0, 0, 1,
                                            "Not a real directory (symlink or file)"))
            continue
        known, files, skipped, reason = _measure(path, cancelled)
        entries.append(UserStorageEntry(
            label, str(path), "incomplete" if skipped else "measured",
            None if skipped else known, known, files, skipped, reason))
    check_cancel(cancelled)
    return entries, []
