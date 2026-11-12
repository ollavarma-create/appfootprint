"""Read-only package-provider availability checks.

Never invoke a shell or request elevated privileges. A short timeout avoids
hanging indefinitely when a package manager is unhealthy.
"""
from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    available: bool
    reason: str
    version: str = ""


def probe_flatpak(timeout: float = 3.0) -> ProviderStatus:
    executable = shutil.which("flatpak")
    if not executable:
        return ProviderStatus("flatpak", False, "Flatpak executable not found in PATH.")
    try:
        version = subprocess.run(
            [executable, "--version"], check=True, capture_output=True,
            text=True, timeout=timeout,
        ).stdout.strip()
        # Verify the inventory operation itself, not just the executable.
        subprocess.run(
            [executable, "list", "--app", "--columns=application"],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProviderStatus("flatpak", False, "Flatpak did not respond in time.")
    except (OSError, subprocess.SubprocessError) as exc:
        return ProviderStatus("flatpak", False, f"Flatpak inventory unavailable: {exc}")
    return ProviderStatus("flatpak", True, "Flatpak inventory available.", version)


def detect_providers() -> dict[str, ProviderStatus]:
    """Only implemented providers are actionable in the current UI."""
    return {"flatpak": probe_flatpak()}
