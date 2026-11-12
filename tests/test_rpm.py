"""RPM provider tests: synthetic database, real temporary filesystem, no root."""
import os
import subprocess

import pytest

from appfootprint.inventory import MeasurementStatus, PackageKind
from appfootprint.providers import rpm as module
from appfootprint.scanner import ScanCancelled


def record(name, paths, version="1", release="2", arch="x86_64", epoch="0"):
    return (module._FIELD.join((name, epoch, version, release, arch,
                                "".join(path + module._FILE for path in paths)))
            + module._RECORD)


def fake_cli(monkeypatch, output, returncode=0):
    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/rpm")
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, returncode, output.encode("utf-8"), b"bad database" if returncode else b""),
    )


def test_parse_package_identity_and_empty_file_list():
    result = module.parse_rpm_query(
        record("firefox", ["/usr/bin/firefox"], epoch="1")
        + record("empty", [], arch="noarch")
    )
    assert result[0].reference == "empty-1-2.noarch"
    assert result[1].reference == "firefox-1:1-2.x86_64"
    assert result[1].paths == ("/usr/bin/firefox",)


def test_bad_query_is_rejected_not_silently_ignored():
    with pytest.raises(ValueError):
        module.parse_rpm_query("not a valid record" + module._RECORD)
    with pytest.raises(ValueError):
        module.parse_rpm_query(record("bad", ["relative/file"]))


def test_missing_cli_and_failed_database(monkeypatch):
    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert "not found" in module.RpmProvider().scan()[1][0]
    fake_cli(monkeypatch, "", returncode=1)
    assert "bad database" in module.RpmProvider().scan()[1][0]


def test_measurement_excludes_directories_and_preserves_unknown(monkeypatch, tmp_path):
    (tmp_path / "usr/bin").mkdir(parents=True)
    (tmp_path / "usr/bin/app").write_bytes(b"x" * 8192)
    (tmp_path / "usr/bin/alias").symlink_to("app")
    fake_cli(monkeypatch, record("app", ["/usr/bin", "/usr/bin/app", "/usr/bin/alias"]))
    records, issues = module.RpmProvider(tmp_path).scan()
    assert not issues and len(records) == 1
    assert records[0].kind == PackageKind.OTHER
    assert records[0].measurements[0].status == MeasurementStatus.MEASURED
    assert records[0].measurements[0].allocated_bytes == (
        (tmp_path / "usr/bin/app").lstat().st_blocks +
        (tmp_path / "usr/bin/alias").lstat().st_blocks
    ) * 512
    assert records[0].metadata["measured_files"] == "2"
    assert records[0].metadata["classification"] == "unclassified"


def test_missing_and_ambiguous_ownership_never_claim_full_measurement(monkeypatch, tmp_path):
    (tmp_path / "usr").mkdir()
    (tmp_path / "usr/shared").write_bytes(b"shared")
    (tmp_path / "usr/first").write_bytes(b"first")
    os.link(tmp_path / "usr/first", tmp_path / "usr/second")
    fake_cli(monkeypatch, record("a", ["/usr/shared", "/usr/first", "/usr/gone"]) +
             record("b", ["/usr/shared", "/usr/second"]))
    records, issues = module.RpmProvider(tmp_path).scan()
    assert not issues
    assert all(r.measurements[0].allocated_bytes is None for r in records)
    assert all(r.measurements[0].status == MeasurementStatus.ERROR for r in records)
    assert records[0].metadata["absent_files"] == "1"
    assert records[0].metadata["ambiguous_files"] == "2"
    assert records[1].metadata["ambiguous_files"] == "2"


def test_cancel_before_query_and_during_measurement(monkeypatch, tmp_path):
    fake_cli(monkeypatch, record("app", ["/one", "/two"]))
    with pytest.raises(ScanCancelled):
        module.RpmProvider(tmp_path).scan(cancelled=lambda: True)
    calls = iter([False, False, True])
    with pytest.raises(ScanCancelled):
        module.RpmProvider(tmp_path).scan(cancelled=lambda: next(calls))


def test_empty_rpm_database(monkeypatch, tmp_path):
    fake_cli(monkeypatch, "")
    assert module.RpmProvider(tmp_path).scan() == ([], [])
