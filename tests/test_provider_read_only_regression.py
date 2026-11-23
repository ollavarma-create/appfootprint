"""Read-only regressions for Flatpak and RPM provider scans.

Only synthetic fixtures and mocked package-manager processes are used.
Access time is excluded because reads may legitimately update atime.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess

from appfootprint import scanner
from appfootprint.providers.rpm import RpmProvider, _QUERY, _FIELD, _FILE, _RECORD


def snapshot(root: Path) -> dict[str, tuple]:
    result = {}
    pending = [root]
    while pending:
        path = pending.pop()
        info = path.lstat()
        payload = None
        if stat.S_ISREG(info.st_mode):
            payload = hashlib.sha256(path.read_bytes()).hexdigest()
        elif stat.S_ISLNK(info.st_mode):
            payload = os.readlink(path)
        result[str(path.relative_to(root))] = (
            stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode),
            info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_uid, info.st_gid, info.st_nlink, payload,
        )
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(path) as listing:
                pending.extend(Path(item.path) for item in listing)
    return result


def test_flatpak_scan_preserves_deployment_and_user_data(tmp_path, monkeypatch):
    home = tmp_path / "home"
    deployment = tmp_path / "deployment"
    data = home / ".var" / "app" / "org.example.App"
    (deployment / "files").mkdir(parents=True)
    (deployment / "files" / "program").write_bytes(b"executable" * 200)
    (data / "cache").mkdir(parents=True)
    (data / "cache" / "item").write_bytes(b"cached" * 200)
    (data / "config").write_text("user settings")
    (data / "link").symlink_to(deployment, target_is_directory=True)
    monkeypatch.setattr(scanner.shutil, "which", lambda name: "/usr/bin/flatpak")
    monkeypatch.setattr(scanner.Path, "home", lambda: home)

    commands = []

    def fake_run(*args):
        commands.append(args)
        if args[0] == "list":
            return ("org.example.App\\tapp/org.example.App/x86_64/stable\\tsystem\\n"
                    if "--app" in args else "")
        if "--show-location" in args:
            return str(deployment)
        if "--show-runtime" in args:
            return "org.freedesktop.Platform/x86_64/25.08"
        raise AssertionError(f"Unexpected Flatpak operation: {args}")

    monkeypatch.setattr(scanner, "run_flatpak", fake_run)
    before = snapshot(tmp_path)
    items, issues = scanner.scan()
    assert not issues and len(items) == 1
    assert items[0].allocated_bytes is not None
    assert items[0].user_data_bytes is not None
    assert snapshot(tmp_path) == before
    assert all(cmd[0] in {"list", "info"} for cmd in commands)


def test_rpm_scan_preserves_owned_files_and_symlinks(tmp_path, monkeypatch):
    root = tmp_path / "root"
    installed = root / "usr" / "share" / "example"
    installed.mkdir(parents=True)
    (installed / "data.bin").write_bytes(b"package content" * 300)
    (installed / "link").symlink_to("data.bin")
    (root / "unowned").write_text("unrelated")
    output = (
        f"example{_FIELD}0{_FIELD}1.0{_FIELD}1{_FIELD}noarch{_FIELD}"
        f"/usr/share/example/data.bin{_FILE}"
        f"/usr/share/example/link{_FILE}{_RECORD}"
    ).encode()
    commands = []

    def fake_run(argv, **kwargs):
        commands.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr=b"")

    monkeypatch.setattr("appfootprint.providers.rpm.shutil.which",
                        lambda command: "/usr/bin/rpm")
    monkeypatch.setattr("appfootprint.providers.rpm.subprocess.run", fake_run)
    before = snapshot(tmp_path)
    records, issues = RpmProvider(root=root).scan()
    assert not issues and len(records) == 1
    assert records[0].identifier == "example"
    assert snapshot(tmp_path) == before
    assert len(commands) == 1
    assert commands[0][0] == ["rpm", "-qa", "--queryformat", _QUERY]
    assert commands[0][1]["check"] is False
