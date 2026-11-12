"""Storage investigation is read-only and scoped to XDG roots."""
import os
from pathlib import Path
import shlex

import pytest

from appfootprint.scanner import ScanCancelled
from appfootprint.storage_investigator import (
    allowed_root, investigate, inspection_commands,
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
