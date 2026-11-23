"""Educational storage explanations are read-only and safe for unknown directories."""
from pathlib import Path

from appfootprint.storage_explanations import explain_hidden_directory


def test_known_xdg_and_flatpak_explanations():
    cache = explain_hidden_directory(Path("/home/example/.cache"))
    assert "cache" in cache.title.lower()
    assert "reproducible" in cache.caution
    flatpak = explain_hidden_directory("/home/example/.var")
    assert "Flatpak" in flatpak.title
    assert "Minecraft" in flatpak.contents
    assert flatpak.documentation.startswith("https://")


def test_unknown_directory_is_not_assumed_disposable():
    info = explain_hidden_directory("/home/example/.something-new")
    assert info.category == "Unknown"
    assert "Unknown does not mean unnecessary" in info.caution


def test_sensitive_directories_warn_about_keys():
    for directory in (".ssh", ".gnupg"):
        info = explain_hidden_directory("/home/example/" + directory)
        assert info.category == "Sensitive credentials"
        assert "keys" in info.contents.lower()


def test_known_name_is_only_a_hint():
    info = explain_hidden_directory("/home/example/.vscode")
    assert "Common" in info.purpose
