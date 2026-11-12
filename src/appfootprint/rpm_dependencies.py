"""Read-only RPM capability-name dependency exploration.

This is a candidate graph, not an RPM/DNF dependency solver. Requirement
versions, rich dependency expressions, alternatives, and transaction effects
are deliberately NOT resolved.
"""
from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from typing import Callable

from .scanner import check_cancel

_FIELD = "\x1f"
_RECORD = "\x1d"
_ITEM = "\x1e"
_QUERY = (
    f"%{{NAME}}{_FIELD}%{{EPOCHNUM}}{_FIELD}%{{VERSION}}{_FIELD}"
    f"%{{RELEASE}}{_FIELD}%{{ARCH}}{_FIELD}"
    f"[%{{REQUIRENAME}}{_ITEM}]{_FIELD}"
    f"[%{{PROVIDENAME}}{_ITEM}]{_RECORD}"
)


@dataclass(frozen=True)
class RpmCapabilities:
    reference: str
    name: str
    requires: tuple[str, ...]
    provides: tuple[str, ...]


@dataclass(frozen=True)
class DependencyLink:
    requirement: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class DependencyView:
    package: RpmCapabilities
    requirements: tuple[DependencyLink, ...]
    required_by: tuple[tuple[str, str], ...]


def parse_capabilities(output: str) -> tuple[RpmCapabilities, ...]:
    entries = []
    for raw in output.split(_RECORD):
        if not raw:
            continue
        fields = raw.split(_FIELD)
        if len(fields) != 7:
            raise ValueError("Malformed RPM capability record")
        name, epoch, version, release, arch, requires, provides = fields
        if not all((name, version, release, arch)):
            raise ValueError("Incomplete RPM capability identity")
        prefix = "" if epoch in ("", "0", "(none)") else f"{epoch}:"
        ref = f"{name}-{prefix}{version}-{release}.{arch}"
        def split(value):
            return tuple(sorted(set(x for x in value.split(_ITEM) if x)))
        entries.append(RpmCapabilities(ref, name, split(requires), split(provides)))
    if len({e.reference for e in entries}) != len(entries):
        raise ValueError("Duplicate RPM package identity")
    return tuple(sorted(entries, key=lambda e: e.reference))


class RpmDependencyIndex:
    def __init__(self, packages: tuple[RpmCapabilities, ...]):
        self.packages = {p.reference: p for p in packages}
        by_capability: dict[str, set[str]] = {}
        for p in packages:
            # RPM names can be provided implicitly, but also record them
            # explicitly to tolerate synthetic/older metadata.
            for capability in (*p.provides, p.name):
                by_capability.setdefault(capability, set()).add(p.reference)
        self.providers = {key: tuple(sorted(value))
                          for key, value in by_capability.items()}

    def view(self, reference: str) -> DependencyView:
        package = self.packages[reference]
        requirements = tuple(DependencyLink(req, self.providers.get(req, ()))
                             for req in package.requires)
        reverse = []
        # Reverse lookup is candidate matching, NOT proven installed resolution.
        own_capabilities = set(package.provides) | {package.name}
        for other in self.packages.values():
            if other.reference == reference:
                continue
            for requirement in other.requires:
                if requirement in own_capabilities:
                    reverse.append((other.reference, requirement))
        return DependencyView(package, requirements, tuple(sorted(reverse)))


def scan_rpm_capabilities(*, cancelled: Callable[[], bool] | None = None
                          ) -> RpmDependencyIndex:
    executable = shutil.which("rpm")
    if not executable:
        raise RuntimeError("RPM executable not found")
    check_cancel(cancelled)
    try:
        result = subprocess.run(
            [executable, "-qa", "--queryformat", _QUERY],
            capture_output=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"RPM capability query failed: {exc}") from exc
    check_cancel(cancelled)
    if result.returncode:
        raise RuntimeError("RPM capability query failed: " +
                           result.stderr.decode("utf-8", "replace").strip())
    return RpmDependencyIndex(parse_capabilities(
        result.stdout.decode("utf-8", "surrogateescape")))
