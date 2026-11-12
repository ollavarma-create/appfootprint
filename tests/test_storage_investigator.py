"""Storage investigation is read-only and scoped to XDG roots."""
import os
from pathlib import Path
import shlex

import pytest

from appfootprint.scanner import ScanCancelled
from appfootprint.storage_investigator import (
    allowed_root, allowed_directory, NavigationHistory,
    investigate, inspection_commands, inspection_script,
)


def test_scoped_roots_and_reject_arbitrary_paths(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    assert allowed_root(cache, tmp_path)
    assert not allowed_root(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        investigate(tmp_path, home=tmp_path)


def test_largest_first_and_no_symlink_traversal(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    (cache / "small").write_bytes(b"a")
    big = cache / "big"
    big.mkdir()
    (big / "data").write_bytes(b"x" * 65536)
    external = tmp_path / "external"
    external.mkdir()
    (external / "huge").write_bytes(b"x" * 131072)
    (cache / "linked").symlink_to(external, target_is_directory=True)
    result = investigate(cache, home=tmp_path)
    assert len(result.children) == 3
    assert result.children[0].label == "big"
    assert next(x for x in result.children if x.label == "linked").files == 1


def test_missing_or_symlink_root(tmp_path):
    cache = tmp_path / ".cache"
    with pytest.raises(FileNotFoundError):
        investigate(cache, home=tmp_path)
    cache.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        investigate(cache, home=tmp_path)


def test_cancellation(tmp_path):
    cache = tmp_path / ".cache"
    cache.mkdir()
    with pytest.raises(ScanCancelled):
        investigate(cache, home=tmp_path, cancelled=lambda: True)


def test_quoted_commands_never_delete():
    path = "/home/example/.cache/a 'quoted' ; rm -rf nope"
    commands = inspection_commands(path)
    assert commands[0] == "du -h --max-depth=1 -- " + shlex.quote(path)
    assert commands[1] == "find " + shlex.quote(path) + " -type f -size +500M -print"
    assert "rm -rf" not in commands[0].split(" -- ", 1)[0]


def test_inspection_script_has_real_newline_between_commands():
    script = inspection_script("/home/example/.cache/mozilla")
    assert script.count("\n") == 1
    assert "\\n" not in script
    assert script.splitlines() == list(inspection_commands("/home/example/.cache/mozilla"))


def test_nested_directory_navigation_and_symlink_barrier(tmp_path):
    cache = tmp_path / ".cache"
    nested = cache / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "payload").write_bytes(b"x" * 4096)
    assert allowed_directory(nested, tmp_path)
    result = investigate(cache / "a", home=tmp_path)
    assert result.children[0].label == "b"
    assert investigate(nested, home=tmp_path).children[0].label == "payload"
    outside = tmp_path / "outside"
    outside.mkdir()
    (cache / "link").symlink_to(outside, target_is_directory=True)
    assert not allowed_directory(cache / "link", tmp_path)
    assert not allowed_directory(cache / "link" / "sub", tmp_path)
    with pytest.raises(ValueError):
        investigate(cache / "link", home=tmp_path)
    assert not allowed_directory(tmp_path / "outside", tmp_path)


def test_history_back_forward_and_branching(tmp_path):
    root = tmp_path / ".cache"
    history = NavigationHistory.at(root)
    assert history.current == root
    assert not history.can_back
    history.visit(root / "a")
    history.visit(root / "a" / "b")
    assert history.back() == root / "a"
    assert history.back() == root
    assert history.forward() == root / "a"
    history.visit(root / "other")
    assert not history.can_forward
    assert history.paths == [root, root / "a", root / "other"]


def test_investigator_clears_stale_commands_on_navigation(tmp_path, monkeypatch):
    """Navigation must not display commands from the previously selected path."""
    from PySide6.QtWidgets import QApplication, QTableWidgetItem
    from appfootprint.gui import StorageInvestigatorDialog

    app = QApplication.instance() or QApplication([])
    root = tmp_path / ".cache"
    child = root / "child"
    child.mkdir(parents=True)
    # Keep this GUI regression deterministic: no background scan needed.
    monkeypatch.setattr(StorageInvestigatorDialog, "start_scan", lambda self: None)
    dialog = StorageInvestigatorDialog(root)
    dialog.table.setRowCount(1)
    dialog.table.setItem(0, 4, QTableWidgetItem(str(child)))
    dialog.table.setCurrentCell(0, 4)
    assert str(child) in dialog.commands.text()
    dialog.navigate_to(child)
    assert dialog.commands.text() == "Select a row to see inspection commands"
    assert not dialog.copy_button.isEnabled()
    assert not dialog.copy_path_button.isEnabled()
    assert dialog.table.rowCount() == 0
    dialog.close()
