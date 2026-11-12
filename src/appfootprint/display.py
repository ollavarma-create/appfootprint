"""Provider-neutral display labels and version normalization.

Presentation only: never changes inventory measurements or scan state.
"""
from __future__ import annotations


def provider_title(name: str, version: str | None) -> str:
    """Show each provider name once, regardless of CLI version formatting."""
    clean = " ".join((version or "").split())
    if not clean:
        return f"{name} (version unknown)"
    if clean.casefold().startswith(name.casefold() + " "):
        clean = clean[len(name):].strip()
    if clean.casefold().startswith("version "):
        clean = clean[8:].strip()
    return f"{name} ({clean or 'version unknown'})"


def inventory_column_labels() -> tuple[str, ...]:
    return (
        "Kind", "Package / application ID", "Ref / version", "Installation",
        "Installed", "User data", "App total", "Runtime",
        "Path / errors", "Source",
    )
