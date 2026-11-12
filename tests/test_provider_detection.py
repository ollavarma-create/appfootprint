"""Detection tests use fakes: no installed package manager is required."""
import subprocess

from appfootprint import provider_detection as detection


def test_missing_flatpak(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda _: None)
    result = detection.probe_flatpak()
    assert not result.available
    assert "PATH" in result.reason


def test_available_flatpak(monkeypatch):
    calls = []
    monkeypatch.setattr(detection.shutil, "which", lambda _: "/usr/bin/flatpak")
    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="Flatpak 1.16\n")
    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    result = detection.probe_flatpak()
    assert result.available
    assert result.version == "Flatpak 1.16"
    assert calls == [
        ["/usr/bin/flatpak", "--version"],
        ["/usr/bin/flatpak", "list", "--app", "--columns=application"],
    ]


def test_timeout_and_error(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda _: "/usr/bin/flatpak")
    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
    monkeypatch.setattr(detection.subprocess, "run", timeout)
    assert not detection.probe_flatpak().available
    def failed(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv)
    monkeypatch.setattr(detection.subprocess, "run", failed)
    assert not detection.probe_flatpak().available


def test_only_implemented_providers_detected(monkeypatch):
    monkeypatch.setattr(detection, "probe_flatpak",
                        lambda: detection.ProviderStatus("flatpak", True, "ok"))
    monkeypatch.setattr(detection, "probe_snap",
                        lambda: detection.ProviderStatus("snap", False, "not installed"))
    monkeypatch.setattr(detection, "probe_rpm",
                        lambda: detection.ProviderStatus("rpm", True, "ok"))
    assert set(detection.detect_providers()) == {"flatpak", "snap", "rpm"}


def test_rpm_detection_missing(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda _: None)
    assert not detection.probe_rpm().available


def test_rpm_detection_available(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda _: "/usr/bin/rpm")
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="RPM version 4.20\\n")

    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    status = detection.probe_rpm()
    assert status.available
    assert len(calls) == 2
    assert calls[1][1:3] == ["-qa", "--queryformat"]


def test_snap_version_whitespace_normalized(monkeypatch):
    monkeypatch.setattr(detection.shutil, "which", lambda _: "/usr/bin/snap")

    def fake_run(argv, **kwargs):
        if argv[1] == "version":
            return subprocess.CompletedProcess(
                argv, 0, stdout="snap     2.77.1-0.fc44\nsnapd    2.77.1\n")
        return subprocess.CompletedProcess(argv, 0, stdout="Name Version\n")

    monkeypatch.setattr(detection.subprocess, "run", fake_run)
    status = detection.probe_snap()
    assert status.available
    assert status.version == "snap 2.77.1-0.fc44"
