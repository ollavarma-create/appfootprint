"""Read-only Flatpak inventory and storage measurements.

Measurements are allocated disk blocks (st_blocks * 512), not guaranteed
reclaimable bytes. Symlinks are never traversed and hard links are counted
once per measured tree. OSTree deduplication/reflinks/snapshots can make
cross-tree totals misleading, so no global physical-use total is claimed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
import os
from pathlib import Path
import shutil
import subprocess


@dataclass
class Item:
    app_id: str
    ref: str
    installation: str
    kind: str
    location: str = ""
    allocated_bytes: int | None = None
    runtime: str = ""
    user_data_bytes: int | None = None
    user_data_path: str = ""
    user_data_breakdown: list[tuple[str, int | None]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def run_flatpak(*args: str) -> str:
    result = subprocess.run(
        ["flatpak", *args], check=True, capture_output=True,
        text=True, timeout=60,
    )
    return result.stdout


def allocated_size(root: Path) -> int:
    """Count allocated bytes under a directory without following symlinks.

    st_blocks is a logical allocation indicator, not a reliable measure of
    uniquely reclaimable physical bytes on copy-on-write filesystems.
    """
    if not root.exists():
        raise FileNotFoundError(str(root))
    total = 0
    seen: set[tuple[int, int]] = set()
    pending = [root]
    while pending:
        path = pending.pop()
        stat = path.lstat()
        key = (stat.st_dev, stat.st_ino)
        if key in seen:
            continue
        seen.add(key)
        total += stat.st_blocks * 512
        if not path.is_dir() or path.is_symlink():
            continue
        with os.scandir(path) as entries:
            for entry in entries:
                pending.append(Path(entry.path))
    return total


def _list(kind: str) -> list[Item]:
    # --columns is tab-separated, stable across localized UI output.
    output = run_flatpak("list", "--app" if kind == "app" else "--runtime",
                         "--columns=application,ref,installation")
    items = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or not fields[1].strip():
            continue
        app_id, ref, installation = (value.strip() for value in fields)
        items.append(Item(app_id=app_id, ref=ref,
                          installation=installation, kind=kind))
    return items


def scan(progress: Callable[[str], None] | None = None) -> tuple[list[Item], list[str]]:
    if not shutil.which("flatpak"):
        return [], ["Flatpak executable was not found in PATH."]
    issues: list[str] = []
    items: list[Item] = []
    for kind in ("app", "runtime"):
        try:
            items.extend(_list(kind))
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(f"Could not list {kind}s: {exc}")
    for index, item in enumerate(items, start=1):
        if progress is not None:
            progress(f"Scanning {item.app_id} ({index}/{len(items)})…")
        # Flatpak installations may be named beyond 'user' and 'system'.
        # For these, do not guess an installation scope.
        scope = {"user": "--user", "system": "--system"}.get(item.installation)
        if scope is None:
            item.errors.append(f"Unsupported installation: {item.installation}")
            continue
        try:
            item.location = run_flatpak("info", scope, "--show-location",
                                        item.ref).strip()
            if item.location:
                item.allocated_bytes = allocated_size(Path(item.location))
            if item.kind == "app":
                item.runtime = run_flatpak("info", scope, "--show-runtime",
                                           item.ref).strip()
        except (OSError, subprocess.SubprocessError) as exc:
            item.errors.append(str(exc))
        if item.kind == "app":
            data_dir = Path.home() / ".var" / "app" / item.app_id
            item.user_data_path = str(data_dir)
            if data_dir.exists():
                try:
                    item.user_data_bytes = allocated_size(data_dir)
                    # Each immediate child is shown separately. These are
                    # directory measurements, not guaranteed reclaimable bytes.
                    for child in sorted(data_dir.iterdir(), key=lambda p: p.name):
                        try:
                            item.user_data_breakdown.append((child.name, allocated_size(child)))
                        except OSError as exc:
                            item.user_data_breakdown.append((child.name, None))
                            item.errors.append(f"Data child {child.name}: {exc}")
                except OSError as exc:
                    item.errors.append(f"User data: {exc}")
            else:
                item.user_data_bytes = 0
    return items, issues


def format_size(value: int | None) -> str:
    if value is None:
        return "Unknown"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return "Unknown"
