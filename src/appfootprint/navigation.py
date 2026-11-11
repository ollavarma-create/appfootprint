"""Pure navigation history state; no Qt or Flatpak dependency."""
from __future__ import annotations

from dataclasses import dataclass, field

PageKey = tuple[str, str, str]


@dataclass
class NavigationHistory:
    entries: list[PageKey] = field(default_factory=list)
    position: int = -1

    @property
    def current(self) -> PageKey | None:
        if self.position < 0:
            return None
        return self.entries[self.position]

    @property
    def can_back(self) -> bool:
        return self.position > 0

    @property
    def can_forward(self) -> bool:
        return self.position + 1 < len(self.entries)

    def visit(self, key: PageKey) -> bool:
        if key == self.current:
            return False
        self.entries = self.entries[:self.position + 1]
        self.entries.append(key)
        self.position += 1
        return True

    def back(self) -> bool:
        if not self.can_back:
            return False
        self.position -= 1
        return True

    def forward(self) -> bool:
        if not self.can_forward:
            return False
        self.position += 1
        return True


def history_labels(entries: list[PageKey], position: int,
                   limit: int = 3) -> tuple[str, str]:
    """Visible recent trail and complete hover trail.

    Revisit detection uses the complete identity (kind, ref, installation),
    not the display name alone.
    """
    route = entries[:position + 1]
    if not route:
        return "History:", ""
    seen: set[PageKey] = set()
    labels: list[str] = []
    for key in route:
        label = key[1].split("/")[0]
        labels.append(("↩ " if key in seen else "") + label)
        seen.add(key)
    visible = labels[-limit:]
    prefix = "… › " if len(labels) > limit else ""
    full = " › ".join(key[1] for key in route)
    return "History: " + prefix + " › ".join(visible), full
