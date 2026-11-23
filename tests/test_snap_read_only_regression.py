"""Snap read-only regression using synthetic images, user data and snapd storage."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import subprocess

from appfootprint.providers import snap
from appfootprint.providers.snap_storage import scan_storage


def _snapshot(root: Path) -> dict[str, tuple]:
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
            with os.scandir(path) as children:
                pending.extend(Path(child.path) for child in children)
    return result


def test_snap_inventory_and_storage_preserve_files(tmp_path, monkeypatch):
    images = tmp_path / "snapd" / "snaps"
    cache = tmp_path / "snapd" / "cache"
    snapshots = tmp_path / "snapd" / "snapshots"
    home = tmp_path / "home"
    active = home / "snap" / "example" / "42"
    common = home / "snap" / "example" / "common"
    for directory in (images, cache, snapshots, active, common):
        directory.mkdir(parents=True)
    (images / "example_42.snap").write_bytes(b"image" * 1024)
    (images / "example_41.snap").write_bytes(b"old" * 1024)
    (images / "core22_2000.snap").write_bytes(b"base" * 1024)
    (active / "settings").write_text("settings")
    (common / "data").write_bytes(b"user data")
    (cache / "download").write_bytes(b"cache")
    (snapshots / "archive.zip").write_bytes(b"archive")
    (cache / "link").symlink_to(active, target_is_directory=True)
    (tmp_path / "unrelated").write_text("untouched")

    output = (
        "Name      Version      Rev    Tracking       Publisher     Notes\n"
        "example   1.0          42     latest/stable  example       -\n"
        "example   0.9          41     latest/stable  example       disabled\n"
        "core22    2026         2000   latest/stable  canonical     base\n"
    )
    commands = []

    def fake_run(argv, **kwargs):
        commands.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

    monkeypatch.setattr(snap.shutil, "which", lambda name: "/usr/bin/snap")
    monkeypatch.setattr(snap.subprocess, "run", fake_run)
    before = _snapshot(tmp_path)
    records, issues = snap.SnapProvider(image_dir=images, home=home).scan()
    storage = scan_storage(tmp_path / "snapd")
    assert not issues and len(records) == 3
    assert len(records[0].measurements) == 3
    assert len(records[1].measurements) == 1
    assert storage.cache.allocated_bytes is not None
    assert storage.snapshots.allocated_bytes is not None
    assert _snapshot(tmp_path) == before
    assert len(commands) == 1
    assert commands[0][0] == ["snap", "list", "--all"]
