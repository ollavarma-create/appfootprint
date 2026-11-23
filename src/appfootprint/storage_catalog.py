"""Optional user-maintained labels and explanations for hidden home directories.

The built-in explanations remain authoritative for known sensitive directories.
External catalogs are local JSON data, never executable rules or shell commands.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .storage_explanations import EXPLANATIONS, StorageExplanation, UNKNOWN

MAX_CATALOG_BYTES = 256 * 1024
MAX_ENTRIES = 256
FIELDS = frozenset({"title", "purpose", "contents", "caution", "category", "documentation"})


def user_catalog_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    config = Path(base).expanduser() if base and Path(base).is_absolute() else Path.home() / ".config"
    return config / "appfootprint" / "catalog.json"


def load_user_catalog(path: Path | None = None) -> dict[str, StorageExplanation]:
    """Read only a small, regular JSON file. Invalid catalogs are ignored safely."""
    path = user_catalog_path() if path is None else Path(path)
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_CATALOG_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("version") != 1:
        return {}
    entries = data.get("directories")
    if not isinstance(entries, dict) or len(entries) > MAX_ENTRIES:
        return {}
    result: dict[str, StorageExplanation] = {}
    for name, fields in entries.items():
        if (not isinstance(name, str) or not name.startswith(".")
                or name in (".", "..") or "/" in name or "\\" in name
                or len(name) > 100 or name in EXPLANATIONS):
            continue
        if not isinstance(fields, dict) or not fields.keys() <= FIELDS:
            continue
        if any(not isinstance(v, str) or len(v) > 1200 for v in fields.values()):
            continue
        if not isinstance(fields.get("title"), str) or not fields["title"].strip():
            continue
        if fields.get("documentation") and not fields["documentation"].startswith("https://"):
            continue
        result[name] = StorageExplanation(
            title=fields["title"],
            purpose=fields.get("purpose", "User-supplied directory identification."),
            contents=fields.get("contents", "Contents not verified."),
            caution=fields.get("caution", "User-supplied description; inspect before making changes."),
            category=fields.get("category", "User catalog"),
            documentation=fields.get("documentation", ""),
        )
    return result


def identify_directory(path: str | Path, catalog: dict[str, StorageExplanation] | None = None) -> StorageExplanation:
    name = Path(path).name
    if name in EXPLANATIONS:
        return EXPLANATIONS[name]
    custom = load_user_catalog() if catalog is None else catalog
    return custom.get(name, UNKNOWN)
