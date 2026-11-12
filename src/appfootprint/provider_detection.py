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


def probe_snap(timeout: float = 3.0) -> ProviderStatus:
    executable = shutil.which("snap")
    if not executable:
        return ProviderStatus("snap", False, "Snap executable not found in PATH.")
    try:
        version = subprocess.run(
            [executable, "version"], check=True, capture_output=True,
            text=True, timeout=timeout,
        ).stdout.strip().splitlines()
        inventory = subprocess.run(
            [executable, "list", "--all"], capture_output=True,
            text=True, timeout=timeout,
        )
        message = (inventory.stderr or inventory.stdout).strip()
        if inventory.returncode and "no snaps are installed" not in message.casefold():
            return ProviderStatus("snap", False, f"Snap inventory unavailable: {message}")
    except subprocess.TimeoutExpired:
        return ProviderStatus("snap", False, "Snap did not respond in time.")
    except (OSError, subprocess.SubprocessError) as exc:
        return ProviderStatus("snap", False, f"Snap unavailable: {exc}")
    return ProviderStatus("snap", True, "Snap inventory available.",
                          " ".join(version[0].split()) if version else "Snap")


def probe_rpm(timeout: float = 3.0) -> ProviderStatus:
    executable = shutil.which("rpm")
    if not executable:
        return ProviderStatus("rpm", False, "RPM executable not found in PATH.")
    try:
        version = subprocess.run(
            [executable, "--version"], check=True, capture_output=True,
            text=True, timeout=timeout,
        ).stdout.strip()
        # Check the installed database without querying package files.
        subprocess.run(
            [executable, "-qa", "--queryformat", "%{NAME}\\n"],
            check=True, capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ProviderStatus("rpm", False, "RPM did not respond in time.")
    except (OSError, subprocess.SubprocessError) as exc:
        return ProviderStatus("rpm", False, f"RPM inventory unavailable: {exc}")
    return ProviderStatus("rpm", True, "RPM inventory available.", version)


def detect_providers() -> dict[str, ProviderStatus]:
    """Only implemented providers are actionable in the current UI."""
    return {"flatpak": probe_flatpak(), "snap": probe_snap(), "rpm": probe_rpm()}
