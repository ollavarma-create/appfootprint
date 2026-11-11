"""Conservative, read-only hints for Flatpak user-data paths.

A directory name is not proof that removing its contents is safe.
No cleanup operations are provided by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Advice:
    category: str
    confidence: str
    explanation: str
    consequence: str = "Review the application's needs before changing files."
    action: str = "Inspect only; no automatic cleanup."


def assess_path(root: Path, selected: Path) -> Advice:
    """Classify a path relative to one application's ~/.var/app directory."""
    try:
        relative = selected.relative_to(root)
    except ValueError:
        return Advice("Outside application data", "Not assessed",
                      "The selected path is outside this application's data directory.")

    if not relative.parts:
        return Advice("Application data", "Not assessed",
                      "Contains mixed data. No cleanup recommendation is possible.")

    top = relative.parts[0]
    # A path's location and name provide clues, not proof of disposability.
    # Minecraft log archives are diagnostic history, not a generic cache.
    if (top == "data" and "minecraft" in relative.parts
            and "logs" in relative.parts and selected.name.endswith(".log.gz")):
        return Advice(
            "Archived diagnostic log", "Pattern-based only",
            "An older compressed Minecraft log; it may help diagnose crashes, "
            "mod conflicts or security incidents. Its name does not prove it "
            "is unnecessary.",
            "Deleting it permanently loses that diagnostic history.",
            "Keep if troubleshooting or retaining evidence; otherwise review "
            "manually with the application closed.",
        )
    if "telemetry" in relative.parts:
        return Advice(
            "Possible telemetry data", "Name-based only",
            "Telemetry may record diagnostics or usage history. Its exact "
            "purpose and retention requirements are not verified.",
            "Deleting it may lose information needed for diagnosis or auditing.",
            "Inspect its contents and application documentation first.",
        )
    if top == "data" and "minecraft" in relative.parts and (
            "saves" in relative.parts or "dimensions" in relative.parts):
        return Advice(
            "Saved game data", "Conservative classification",
            "This path appears to contain Minecraft world data.",
            "Deleting it may irreversibly destroy saved worlds or progress.",
            "Keep and back up important worlds; no cleanup recommended.",
        )
    if top == "cache":
        return Advice(
            "Possible cache", "Name-based only",
            "This path is under the application's cache directory. Some contents "
            "may be recreated, but the name alone does not prove removal is safe. "
            "Review in the application and close it before considering manual changes.",
        )
    if top in {"config", "data", ".local", ".ld.so"}:
        return Advice(
            "Application state", "Conservative classification",
            "May contain settings, saved work, databases or other important data. "
            "No cleanup is recommended.",
        )
    return Advice(
        "Unclassified user data", "Not assessed",
        "No documented cleanup rule matches this path. A folder name or large "
        "size is not sufficient evidence for deletion.",
    )


def space_significance(size: int | None) -> str:
    """Describe scale, not reclaimable bytes or a deletion recommendation."""
    if size is None:
        return "Size unknown — benefit cannot be estimated."
    if size < 10 * 1024 * 1024:
        return "Very small (under 10 MiB) — negligible likely space benefit."
    if size < 100 * 1024 * 1024:
        return "Small (under 100 MiB) — limited potential space benefit."
    if size < 1024 * 1024 * 1024:
        return "Moderate (under 1 GiB) — may be worth investigating."
    return "Large (at least 1 GiB) — worth understanding, not necessarily removing."
