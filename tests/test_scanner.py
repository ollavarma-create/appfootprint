from pathlib import Path
import pytest
from appfootprint.scanner import allocated_size, format_size, _list


def test_format_size():
    assert format_size(None) == "Unknown"
    assert format_size(1024) == "1.0 KiB"


def test_directory_does_not_follow_symlinks(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "file").write_bytes(b"x" * 8192)
    (data / "link").symlink_to(data, target_is_directory=True)
    assert allocated_size(data) >= 8192


def test_hard_links_not_double_counted(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    first = data / "first"
    first.write_bytes(b"x" * 8192)
    (data / "second").hardlink_to(first)
    assert allocated_size(data) == data.stat().st_blocks * 512 + first.stat().st_blocks * 512


def test_parse_flatpak_list(monkeypatch):
    monkeypatch.setattr("appfootprint.scanner.run_flatpak",
                        lambda *args: "org.kicad.KiCad\tapp/org.kicad.KiCad/x86_64/stable\tsystem\n")
    items = _list("app")
    assert len(items) == 1
    assert items[0].installation == "system"
    assert items[0].app_id == "org.kicad.KiCad"
