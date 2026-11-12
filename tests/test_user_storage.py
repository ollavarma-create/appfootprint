"""Synthetic XDG inventory tests; never inspect the real home directory."""
import os
from pathlib import Path

import pytest

from appfootprint.scanner import ScanCancelled
from appfootprint.user_storage import scan_user_storage


def test_missing_directories_are_absent(tmp_path):
    entries, issues = scan_user_storage(tmp_path)
    assert not issues
    assert len(entries) == 5
    assert all(e.status == "absent" and e.allocated_bytes == 0 for e in entries)


def test_files_and_symlinks_are_not_followed(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "file").write_bytes(b"x" * 4096)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "large").write_bytes(b"x" * 65536)
    (cache / "external").symlink_to(outside, target_is_directory=True)
    entries, _ = scan_user_storage(tmp_path)
    item = entries[0]
    assert item.status == "measured"
    assert item.allocated_bytes == (
        cache.lstat().st_blocks + (cache / "file").lstat().st_blocks
        + (cache / "external").lstat().st_blocks
    ) * 512
    assert item.files == 3


def test_hardlinks_count_once_per_tree(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    file = cache / "first"
    file.write_bytes(b"x" * 4096)
    os.link(file, cache / "second")
    entry = scan_user_storage(tmp_path)[0][0]
    assert entry.allocated_bytes == (
        cache.lstat().st_blocks + file.lstat().st_blocks
    ) * 512


def test_symlinked_target_not_followed(tmp_path):
    (tmp_path / ".cache").symlink_to(tmp_path, target_is_directory=True)
    entry = scan_user_storage(tmp_path)[0][0]
    assert entry.status == "error"
    assert entry.allocated_bytes is None


def test_cancelled_scan(tmp_path):
    with pytest.raises(ScanCancelled):
        scan_user_storage(tmp_path, cancelled=lambda: True)


def test_partial_tree_keeps_subtotal_unknown(monkeypatch, tmp_path):
    from appfootprint import user_storage
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "ok").write_bytes(b"hello")
    real_scandir = user_storage.os.scandir

    def denied(path):
        if Path(path) == cache:
            raise PermissionError("synthetic denied")
        return real_scandir(path)

    monkeypatch.setattr(user_storage.os, "scandir", denied)
    entry = scan_user_storage(tmp_path)[0][0]
    assert entry.status == "incomplete"
    assert entry.allocated_bytes is None
    assert entry.skipped == 1
    assert entry.known_allocated_bytes >= 0
