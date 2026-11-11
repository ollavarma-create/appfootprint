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


class ScanCancelled(Exception):
    """The user requested cancellation of a read-only scan."""


def check_cancel(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ScanCancelled()


@dataclass
class Item:
    app_id: str
    ref: str
    installation: str
    kind: str
    location: str = ""
    allocated_bytes: int | None = None
    runtime: str = ""
    metadata: str = ""
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


def allocated_size(root: Path, cancelled: Callable[[], bool] | None = None) -> int:
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
        check_cancel(cancelled)
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


def scan(progress: Callable[[str], None] | None = None,
         cancelled: Callable[[], bool] | None = None) -> tuple[list[Item], list[str]]:
    if not shutil.which("flatpak"):
        return [], ["Flatpak executable was not found in PATH."]
    issues: list[str] = []
    items: list[Item] = []
    for kind in ("app", "runtime"):
        check_cancel(cancelled)
        try:
            items.extend(_list(kind))
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(f"Could not list {kind}s: {exc}")
    for index, item in enumerate(items, start=1):
        check_cancel(cancelled)
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
                item.allocated_bytes = allocated_size(Path(item.location), cancelled)
            if item.kind == "runtime":
                try:
                    item.metadata = run_flatpak(
                        "info", scope, "--show-metadata", item.ref
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    item.errors.append(f"Extension metadata unavailable: {exc}")
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
                    item.user_data_bytes = allocated_size(data_dir, cancelled)
                    # Each immediate child is shown separately. These are
                    # directory measurements, not guaranteed reclaimable bytes.
                    for child in sorted(data_dir.iterdir(), key=lambda p: p.name):
                        check_cancel(cancelled)
                        try:
                            item.user_data_breakdown.append((child.name, allocated_size(child, cancelled)))
                        except OSError as exc:
                            item.user_data_breakdown.append((child.name, None))
                            item.errors.append(f"Data child {child.name}: {exc}")
                except OSError as exc:
                    item.errors.append(f"User data: {exc}")
            else:
                item.user_data_bytes = 0
    check_cancel(cancelled)
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


def direct_runtime_users(runtime: Item, items: list[Item]) -> list[Item]:
    """Find apps declaring the same runtime name, architecture and branch.

    Flatpak's --columns=ref output may omit the 'runtime/' type prefix.
    Installed runtime extensions and indirect dependencies are not inferred.
    """
    if runtime.kind != "runtime":
        return []

    def normalized(ref: str) -> str:
        return ref.strip().removeprefix("runtime/")

    target = normalized(runtime.ref)
    if len(target.split("/")) != 3:
        return []
    return sorted(
        (item for item in items
         if item.kind == "app"
         and normalized(item.runtime) == target),
        key=lambda item: item.app_id.casefold(),
    )


def runtime_extension_hint(runtime: Item) -> str | None:
    """Recognize extension families without claiming actual consumers.

    Flatpak runtime extensions are not necessarily listed as applications'
    --show-runtime values. Naming patterns alone cannot prove use or disuse.
    """
    if runtime.kind != "runtime":
        return None
    ref = runtime.ref.strip().removeprefix("runtime/")
    parts = ref.split("/")
    if len(parts) != 3:
        return None
    name, _arch, _branch = parts
    if name.startswith("org.freedesktop.Platform.GL."):
        return (
            "Graphics driver extension (Flatpak GL). Applications can use "
            "this through their platform's extension points rather than "
            "declaring it as their primary runtime. The direct-user list "
            "cannot establish whether it is in use."
        )
    if name.startswith("org.freedesktop.Platform.VAAPI."):
        return (
            "Video acceleration extension (VA-API). It may be selected "
            "through a platform extension point; direct runtime matching "
            "does not establish its usage."
        )
    if name.startswith("org.freedesktop.Platform.ffmpeg"):
        return (
            "Media codec extension. Its consumers cannot be established "
            "from the primary runtime field alone."
        )
    return None
