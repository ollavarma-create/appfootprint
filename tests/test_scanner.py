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

def test_system_app_user_data_is_scanned(monkeypatch, tmp_path: Path):
    from appfootprint import scanner
    monkeypatch.setattr(scanner.shutil, "which", lambda name: "/usr/bin/flatpak")
    monkeypatch.setattr(scanner, "_list", lambda kind: [
        scanner.Item("org.example.App", "app/org.example.App/x86_64/stable",
                     "system", "app")
    ] if kind == "app" else [])
    monkeypatch.setattr(scanner, "run_flatpak", lambda *args:
                        str(tmp_path / "deployment") if "--show-location" in args
                        else "org.freedesktop.Platform/x86_64/25.08")
    (tmp_path / "deployment").mkdir()
    home = tmp_path / "home"
    data = home / ".var" / "app" / "org.example.App"
    data.mkdir(parents=True)
    (data / "cache").write_bytes(b"x" * 8192)
    monkeypatch.setattr(scanner.Path, "home", lambda: home)
    items, issues = scanner.scan()
    assert not issues
    assert items[0].user_data_bytes is not None
    assert items[0].user_data_bytes >= 8192
