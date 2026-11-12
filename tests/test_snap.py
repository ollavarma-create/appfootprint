"""Snap inventory tests with synthetic CLI output and temporary directories."""
from pathlib import Path
import subprocess

from appfootprint.inventory import MeasurementStatus, StorageRole
from appfootprint.providers import snap as module
from appfootprint.provider_detection import probe_snap
from appfootprint import provider_detection


OUTPUT = """Name      Version      Rev    Tracking       Publisher     Notes
hello     2.12         42     latest/stable  canonical✓    -
hello     2.11         41     latest/stable  canonical✓    disabled
core22    2026         2000   latest/stable  canonical✓    base
"""


def test_parse_revisions_and_base():
    entries = module.parse_snap_list(OUTPUT)
    assert [(e.name, e.revision, e.active) for e in entries] == [
        ("hello", "42", True), ("hello", "41", False), ("core22", "2000", True)
    ]


def test_no_snap_installed(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    records, issues = module.SnapProvider().scan()
    assert not records and "not found" in issues[0]


def test_snap_inventory_and_no_double_count(monkeypatch, tmp_path):
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/snap")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args, 0, OUTPUT, ""))
    images = tmp_path / "images"
    images.mkdir()
    for name in ("hello_42", "hello_41", "core22_2000"):
        (images / (name + ".snap")).write_bytes(b"x" * 4096)
    home = tmp_path / "home"
    (home / "snap/hello/42").mkdir(parents=True)
    (home / "snap/hello/42/settings").write_bytes(b"test")
    (home / "snap/hello/common").mkdir()
    (home / "snap/hello/common/cache").write_bytes(b"test")
    provider = module.SnapProvider(images, home)
    records, issues = provider.scan()
    assert not issues and len(records) == 3
    assert records[0].metadata["state"] == "active"
    assert len(records[0].measurements) == 3
    assert records[1].metadata["state"] == "disabled"
    assert len(records[1].measurements) == 1
    assert records[2].kind.value == "runtime"
    assert records[2].measurements[0].role == StorageRole.SHARED
    assert all("/snap/hello/" not in m.path for record in records
               for m in record.measurements if m.role == StorageRole.DIRECT)


def test_empty_snapd(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/snap")
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 1, "", "No snaps are installed yet."))
    assert module.SnapProvider().scan() == ([], [])


def test_snap_probe_missing_and_empty(monkeypatch):
    monkeypatch.setattr(provider_detection.shutil, "which", lambda _: None)
    assert not probe_snap().available
    monkeypatch.setattr(provider_detection.shutil, "which", lambda _: "/usr/bin/snap")
    def fake_run(args, **kwargs):
        if args[1] == "version":
            return subprocess.CompletedProcess(args, 0, "snap 2.7\n", "")
        return subprocess.CompletedProcess(args, 1, "", "No snaps are installed yet.")
    monkeypatch.setattr(provider_detection.subprocess, "run", fake_run)
    assert probe_snap().available


def test_snap_probe_daemon_failure(monkeypatch):
    monkeypatch.setattr(provider_detection.shutil, "which", lambda _: "/usr/bin/snap")
    def fake_run(args, **kwargs):
        if args[1] == "version":
            return subprocess.CompletedProcess(args, 0, "snap 2.7\n", "")
        return subprocess.CompletedProcess(args, 1, "", "cannot communicate with server")
    monkeypatch.setattr(provider_detection.subprocess, "run", fake_run)
    assert not probe_snap().available
