"""Offscreen Qt tests for conditional provider UI."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from appfootprint import gui
from appfootprint.provider_detection import ProviderStatus


def test_provider_button_only_when_available(monkeypatch):
    app = QApplication.instance() or QApplication([])
    # Keep this deterministic and avoid starting real subprocesses.
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.show()
    assert window.button.isHidden()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", False, "Not installed")
    })
    assert window.button.isHidden()
    assert "Not installed" in window.provider_status.text()
    window.providers_detected({
        "flatpak": ProviderStatus("flatpak", True, "Available", "Flatpak 1.16")
    })
    assert window.button.isVisible()
    assert "Flatpak 1.16" in window.provider_status.text()
    window.close()


def test_scan_guard_when_unavailable(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    window.start_scan()
    assert window.worker is None
    window.close()


def test_guidance_follows_inventory_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui.ProviderProbeThread, "start", lambda self: None)
    window = gui.MainWindow()
    assert "Double-click" not in window.info.text()
    assert "No inventory yet" in window.info.text()
    window.show_results([], [])
    assert "Double-click" not in window.info.text()
    from appfootprint.scanner import Item
    item = Item(app_id="org.example.App", ref="app/org.example.App/x86_64/stable",
                installation="system", kind="app", allocated_bytes=1024,
                user_data_bytes=0)
    window.show_results([item], [])
    assert "Double-click" in window.info.text()
    window.scan_was_cancelled()
    assert "Previous results retained" in window.info.text()
    assert "Double-click" in window.info.text()
    window.close()
