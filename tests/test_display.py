"""Presentation invariants across Flatpak, Snap and RPM."""
from appfootprint.display import provider_title, inventory_column_labels


def test_provider_titles_do_not_repeat_provider_names():
    assert provider_title("Flatpak", "Flatpak 1.18.4") == "Flatpak (1.18.4)"
    assert provider_title("Snap", "snap    2.77.1-0.fc44") == "Snap (2.77.1-0.fc44)"
    assert provider_title("RPM", "RPM version 6.0.2") == "RPM (6.0.2)"


def test_provider_titles_missing_and_whitespace():
    assert provider_title("RPM", None) == "RPM (version unknown)"
    assert provider_title("Snap", "  ") == "Snap (version unknown)"
    assert provider_title("Flatpak", "1.18.4") == "Flatpak (1.18.4)"


def test_unified_table_labels_cover_all_package_managers():
    labels = inventory_column_labels()
    assert len(labels) == 10
    assert labels[1] == "Package / application ID"
    assert labels[-1] == "Source"
