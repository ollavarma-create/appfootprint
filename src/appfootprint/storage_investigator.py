"""Read-only navigable storage investigation for trusted XDG roots."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import stat
from typing import Callable

from .scanner import check_cancel
from .user_storage import TARGETS, _measure, UserStorageEntry


@dataclass(frozen=True)
class Investigation:
    root: str
    children: tuple[UserStorageEntry, ...]
    issues: tuple[str, ...]


def allowed_root(path: Path, home: Path | None = None) -> bool:
    home = Path.home() if home is None else Path(home)
    # Lexical absolute path check, not resolve(): resolving symlinks could
    # silently change the intended scope.
    candidates = {os.path.abspath(home / relative) for _, relative in TARGETS}
    return os.path.abspath(path) in candidates


def allowed_directory(path: Path, home: Path | None = None) -> bool:
    """Validate every path component; never follow a symlink or escape XDG roots."""
    home = Path.home() if home is None else Path(home)
    path = Path(os.path.abspath(path))
    roots = [Path(os.path.abspath(home / relative)) for _, relative in TARGETS]
    for root in roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        # Validate the root itself and each child component. Symlinked parents
        # cannot redirect traversal outside the lexical XDG scope.
        for component in (root, *(root.joinpath(*relative.parts[:i])
                                  for i in range(1, len(relative.parts) + 1))):
            try:
                if not stat.S_ISDIR(component.lstat().st_mode):
                    return False
            except OSError:
                return False
        return True
    return False


@dataclass
class NavigationHistory:
    """Browser-like path history, independent of Qt and the filesystem."""
    paths: list[Path]
    index: int = 0

    @classmethod
    def at(cls, root: Path) -> "NavigationHistory":
        return cls([Path(root)])

    @property
    def current(self) -> Path:
        return self.paths[self.index]

    @property
    def can_back(self) -> bool:
        return self.index > 0

    @property
    def can_forward(self) -> bool:
        return self.index + 1 < len(self.paths)

    def visit(self, path: Path) -> None:
        path = Path(path)
        if path == self.current:
            return
        self.paths = self.paths[:self.index + 1] + [path]
        self.index += 1

    def back(self) -> Path:
        if self.can_back:
            self.index -= 1
        return self.current

    def forward(self) -> Path:
        if self.can_forward:
            self.index += 1
        return self.current


def investigate(
    root: Path,
    *,
    home: Path | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> Investigation:
    root = Path(root)
    # Preserve the established missing-root error contract. Symlinks and
    # non-directory targets remain rejected by the scope validation below.
    root.lstat()
    if not allowed_directory(root, home):
        raise ValueError("Select a real directory inside a configured XDG root")
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Root is not a real directory")
    entries = []
    with os.scandir(root) as listing:
        children = sorted((Path(item.path) for item in listing), key=lambda p: p.name)
    for path in children:
        check_cancel(cancelled)
        if progress:
            progress(f"Measuring {path.name}…")
        try:
            info = path.lstat()
            if info.st_dev != root.lstat().st_dev:
                entries.append(UserStorageEntry(path.name, str(path), "incomplete", None,
                                                0, 0, 1, "different filesystem"))
                continue
            if stat.S_ISDIR(info.st_mode):
                known, count, skipped, reason = _measure(path, cancelled)
            else:
                known, count, skipped, reason = info.st_blocks * 512, 1, 0, ""
            entries.append(UserStorageEntry(
                path.name, str(path), "incomplete" if skipped else "measured",
                None if skipped else known, known, count, skipped, reason))
        except OSError as exc:
            entries.append(UserStorageEntry(
                path.name, str(path), "inaccessible" if isinstance(exc, PermissionError)
                else "error", None, 0, 0, 1, str(exc)))
    check_cancel(cancelled)
    entries.sort(key=lambda e: (e.allocated_bytes is None,
                                -(e.allocated_bytes if e.allocated_bytes is not None
                                  else e.known_allocated_bytes), e.label))
    return Investigation(str(root), tuple(entries), ())


def inspection_commands(path: str) -> tuple[str, str]:
    """Generate copy-only inspection examples; never a deletion command."""
    quoted = shlex.quote(path)
    return (
        f"du -h --max-depth=1 -- {quoted}",
        f"find {quoted} -type f -size +500M -print",
    )


def inspection_script(path: str) -> str:
    """Return copyable commands separated by real shell newlines."""
    return "\n".join(inspection_commands(path))
