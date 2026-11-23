"""Offline path hints must never inspect files or imply cleanup."""
from pathlib import Path

from appfootprint.storage_hints import CACHE_HINTS, identify_storage_hint


def test_common_cache_hints():
    home = Path("/home/example")
    for name in ("pip", "mozilla", "thumbnails", "tauri", "libdnf5", "borg", "npm"):
        hint = identify_storage_hint(home / ".cache" / name, home)
        assert hint is not None
        assert hint.search_terms
        assert "remove" not in hint.title.lower()


def test_no_false_ownership_for_other_paths():
    home = Path("/home/example")
    assert identify_storage_hint(home / ".config" / "tauri", home) is None
    assert identify_storage_hint(home / ".cache" / "unknown", home) is None
    assert identify_storage_hint(home / ".cache" / "pip" / "nested", home) is None


def test_no_user_path_in_search_terms():
    assert all("/home/" not in hint.search_terms for hint in CACHE_HINTS.values())
