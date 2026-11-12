"""Human-readable, conservative measurement explanations for the UI."""
from __future__ import annotations


def allocated_tooltip(value: int | None, *, incomplete: bool = False) -> str:
    """Show exact measured bytes without implying reclaimable disk space."""
    if value is None:
        return "Unknown allocated size; measurement is incomplete or unavailable."
    amount = f"{value:,}".replace(",", " ")
    qualifier = "Known subtotal (incomplete scan)" if incomplete else "Reported allocated size"
    return (
        f"{qualifier}: {amount} bytes. "
        "Allocated file blocks are not guaranteed to be physically unique "
        "or reclaimable, especially on Btrfs."
    )
