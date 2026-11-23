"""Offline, path-based hints for common cache directories.

These hints are not ownership proofs, cleanup instructions or filesystem reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StorageHint:
    title: str
    explanation: str
    caution: str
    keywords: tuple[str, ...]

    @property
    def search_terms(self) -> str:
        return " ".join(self.keywords)


CACHE_HINTS = {
    "pip": StorageHint("Python pip cache",
        "Often contains downloaded Python distributions and build artifacts.",
        "Usually reproducible, but may include locally built wheels; verify first.",
        ("Python", "pip", "cache", "Linux")),
    "mozilla": StorageHint("Mozilla browser cache",
        "Browser-generated temporary resources and other cache data.",
        "A cache path does not establish whether all its contents are disposable.",
        ("Firefox", "Mozilla", "cache", "Linux")),
    "thumbnails": StorageHint("Desktop thumbnails",
        "Generated previews used by desktop applications and file managers.",
        "Previews are often regenerated; do not infer their source files are expendable.",
        ("freedesktop", "thumbnails", "cache", "Linux")),
    "tauri": StorageHint("Tauri development cache",
        "May contain downloaded AppImage packaging helpers such as LinuxDeploy.",
        "The cache does not prove Tauri is installed or unused; verify before changes.",
        ("Tauri", "linuxdeploy", "AppImage", "cache", "Linux")),
    "libdnf5": StorageHint("DNF5 package manager cache",
        "Downloaded repository metadata and package-manager support files.",
        "Removing caches may force new downloads and affect offline operations.",
        ("Fedora", "DNF5", "libdnf5", "cache")),
    "borg": StorageHint("Borg backup cache",
        "Local cache data associated with BorgBackup repositories.",
        "Backup-related state deserves special care; do not assume it is safe to remove.",
        ("BorgBackup", "cache", "Linux")),
    "npm": StorageHint("npm cache",
        "Node.js package-manager download cache and related metadata.",
        "Project dependencies and configuration may be elsewhere; inspect first.",
        ("npm", "cache", "Node.js", "Linux")),
}


def identify_storage_hint(path: str | Path, home: Path | None = None) -> StorageHint | None:
    """Only match immediate children of ~/.cache, not arbitrary same-named paths."""
    home = Path.home() if home is None else Path(home)
    candidate = Path(path)
    if candidate.parent != home / ".cache":
        return None
    return CACHE_HINTS.get(candidate.name)
