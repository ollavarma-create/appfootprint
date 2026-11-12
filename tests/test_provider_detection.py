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
    assert set(detection.detect_providers()) == {"flatpak", "snap"}
