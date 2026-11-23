"""Regression: storage scans must not mutate the examined filesystem tree.

Use synthetic fixtures only.  Access times are intentionally excluded: reading
directories or metadata can update atime depending on mount options.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat

from appfootprint.storage_investigator import investigate
from appfootprint.user_storage import scan_user_storage


def _snapshot(root: Path) -> dict[str, tuple]:
    """Capture names, contents and stable metadata without following symlinks."""
    result = {}
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        rel = str(path.relative_to(root))
        kind = stat.S_IFMT(info.st_mode)
        content = None
        if stat.S_ISREG(info.st_mode):
            content = hashlib.sha256(path.read_bytes()).hexdigest()
        elif stat.S_ISLNK(info.st_mode):
            content = os.readlink(path)
        result[rel] = (
            kind, stat.S_IMODE(info.st_mode), info.st_size,
            info.st_mtime_ns, info.st_ctime_ns, info.st_uid, info.st_gid,
            info.st_nlink, content,
        )
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as entries:
                pending.extend(Path(item.path) for item in entries)
    return result


def test_storage_scans_preserve_contents_and_metadata(tmp_path, monkeypatch):
    """Inventory and nested investigation leave every fixture unchanged."""
    home = tmp_path / "synthetic-home"
    cache = home / ".cache"
    nested = cache / "pip" / "http-v2"
    nested.mkdir(parents=True)
    data = nested / "cached.bin"
    data.write_bytes(b"test cache data\\x00" * 1024)
    data.chmod(0o640)
    (cache / "empty").mkdir()
    (home / ".mystery").mkdir()
    (home / ".mystery" / "settings.json").write_text('{"key": "value"}')
    (home / ".cache" / "link").symlink_to(home / ".mystery", target_is_directory=True)
    os.link(data, nested / "hardlink.bin")
    (home / "visible.txt").write_text("unrelated file")

    # The local catalog belongs to a different location; avoid reading real
    # user configuration during this deterministic test.
    monkeypatch.setattr("appfootprint.user_storage.load_user_catalog", lambda: {})

    before = _snapshot(home)
    entries, issues = scan_user_storage(home)
    assert not issues
    assert {Path(entry.path).name for entry in entries} == {".cache", ".mystery"}
    assert all(entry.status == "measured" for entry in entries)

    top = investigate(cache, home=home)
    assert {item.label for item in top.children} == {"pip", "empty", "link"}
    middle = investigate(cache / "pip", home=home)
    assert middle.children[0].label == "http-v2"
    bottom = investigate(nested, home=home)
    assert {item.label for item in bottom.children} == {"cached.bin", "hardlink.bin"}

    after = _snapshot(home)
    assert after == before, "Scanning modified file contents, names, or stable metadata"
