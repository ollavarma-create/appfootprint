"""Synthetic hidden-directory inventory tests; never inspect the real home directory."""
import os
from pathlib import Path

import pytest

from appfootprint.scanner import ScanCancelled
from appfootprint.user_storage import scan_user_storage


def test_missing_directories_are_absent(tmp_path):
    entries, issues = scan_user_storage(tmp_path)
    assert not issues
    assert entries == []


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
    entries, issues = scan_user_storage(tmp_path)
    assert entries == []
    assert issues == []


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


def test_discovers_unknown_hidden_directories_and_ignores_regular_files(tmp_path):
    (tmp_path / ".mystery").mkdir()
    (tmp_path / ".mystery" / "data").write_bytes(b"some data")
    (tmp_path / ".rustup").mkdir()
    (tmp_path / ".hidden-file").write_text("not a directory")
    (tmp_path / "visible").mkdir()
    entries, issues = scan_user_storage(tmp_path)
    assert not issues
    assert [Path(e.path).name for e in entries] == [".mystery", ".rustup"]
    assert entries[0].label == "Unidentified hidden directory"
    assert entries[0].status == "measured"
    assert entries[1].label == "Rust toolchains"


def test_nested_xdg_paths_are_not_counted_as_separate_roots(tmp_path):
    (tmp_path / ".local" / "share").mkdir(parents=True)
    (tmp_path / ".local" / "share" / "data").write_bytes(b"x")
    entries, _ = scan_user_storage(tmp_path)
    assert len(entries) == 1
    assert Path(entries[0].path).name == ".local"


def test_unreadable_home_reports_issue(monkeypatch, tmp_path):
    from appfootprint import user_storage
    original = user_storage.os.scandir

    def denied(path):
        if Path(path) == tmp_path:
            raise PermissionError("synthetic denied")
        return original(path)

    monkeypatch.setattr(user_storage.os, "scandir", denied)
    entries, issues = scan_user_storage(tmp_path)
    assert entries == []
    assert len(issues) == 1
    assert "Cannot list home directory" in issues[0]
