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
