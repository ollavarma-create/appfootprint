"""Synthetic RPM capability graph tests; no installed RPM database required."""
import subprocess

import pytest

from appfootprint import rpm_dependencies as dep


def entry(name, requires=(), provides=(), version="1"):
    return (dep._FIELD.join((
        name, "0", version, "1", "x86_64",
        "".join(x + dep._ITEM for x in requires),
        "".join(x + dep._ITEM for x in provides),
    )) + dep._RECORD)


def test_capability_candidates_and_reverse_links():
    text = (
        entry("client", ["libvirtual.so.1()(64bit)", "missing-cap", "libvirtual.so.1()(64bit)"]) +
        entry("provider", provides=["libvirtual.so.1()(64bit)"]) +
        entry("alternative", provides=["libvirtual.so.1()(64bit)"])
    )
    index = dep.RpmDependencyIndex(dep.parse_capabilities(text))
    client = index.view("client-1-1.x86_64")
    assert client.requirements[0].requirement == "libvirtual.so.1()(64bit)"
    assert len(client.requirements[0].candidates) == 2
    assert client.requirements[1].candidates == ()
    provider = index.view("provider-1-1.x86_64")
    assert ("client-1-1.x86_64", "libvirtual.so.1()(64bit)") in provider.required_by


def test_duplicate_identity_and_malformed_input():
    with pytest.raises(ValueError):
        dep.parse_capabilities(entry("x") + entry("x"))
    with pytest.raises(ValueError):
        dep.parse_capabilities("bad" + dep._RECORD)


def test_scan_invokes_one_read_only_query(monkeypatch):
    calls = []
    monkeypatch.setattr(dep.shutil, "which", lambda _: "/usr/bin/rpm")
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=entry("one").encode(), stderr=b"")
    monkeypatch.setattr(dep.subprocess, "run", fake_run)
    index = dep.scan_rpm_capabilities()
    assert len(index.packages) == 1
    assert calls == [["/usr/bin/rpm", "-qa", "--queryformat", dep._QUERY]]


def test_missing_rpm_and_cancel(monkeypatch):
    monkeypatch.setattr(dep.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError):
        dep.scan_rpm_capabilities()
    monkeypatch.setattr(dep.shutil, "which", lambda _: "/usr/bin/rpm")
    from appfootprint.scanner import ScanCancelled
    with pytest.raises(ScanCancelled):
        dep.scan_rpm_capabilities(cancelled=lambda: True)
