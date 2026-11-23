"""Tests for the optional local catalog and built-in precedence."""
import json

from appfootprint.storage_catalog import (
    identify_directory, load_user_catalog, user_catalog_path,
)
from appfootprint.user_storage import scan_user_storage


def test_local_catalog_labels_unknown_directory(tmp_path, monkeypatch):
    config = tmp_path / "config"
    catalog = config / "appfootprint" / "catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps({
        "version": 1,
        "directories": {
            ".myide": {
                "title": "My IDE",
                "purpose": "User supplied IDE identification.",
                "contents": "Plugins and caches.",
                "caution": "Check before deleting.",
            }
        },
    }))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    assert user_catalog_path() == catalog
    (tmp_path / ".myide").mkdir()
    (tmp_path / ".unknown").mkdir()
    entries, issues = scan_user_storage(tmp_path)
    assert not issues
    labels = {entry.path.rsplit("/", 1)[-1]: entry.label for entry in entries}
    assert labels[".myide"] == "My IDE"
    assert labels[".unknown"] == "Unidentified hidden directory"
    assert identify_directory(".myide").purpose == "User supplied IDE identification."


def test_builtin_security_explanation_cannot_be_overridden(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"version": 1, "directories": {
        ".ssh": {"title": "Disposable cache"},
        ".special": {"title": "Special application"},
    }}))
    custom = load_user_catalog(path)
    assert ".ssh" not in custom
    assert identify_directory(".ssh", custom).category == "Sensitive credentials"
    assert identify_directory(".special", custom).title == "Special application"


def test_catalog_rejects_traversal_and_bad_schema(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"version": 1, "directories": {
        "../outside": {"title": "Unsafe"},
        ".okay": {"title": "Okay"},
        ".wrong": {"title": 12},
        ".badurl": {"title": "Bad", "documentation": "file:///etc/passwd"},
        ".extra": {"title": "Extra", "command": "rm -rf /"},
    }}))
    assert list(load_user_catalog(path)) == [".okay"]


def test_missing_and_invalid_catalog_are_ignored(tmp_path):
    path = tmp_path / "missing.json"
    assert load_user_catalog(path) == {}
    path.write_text("{ broken")
    assert load_user_catalog(path) == {}
    path.write_text(json.dumps({"version": 99, "directories": {".x": {"title": "X"}}}))
    assert load_user_catalog(path) == {}
    path.write_bytes(b"0" * (256 * 1024 + 1))
    assert load_user_catalog(path) == {}
