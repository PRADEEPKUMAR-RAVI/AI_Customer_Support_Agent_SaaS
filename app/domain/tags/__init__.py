"""Pure tag-classification rule (curated + admin-approved growth, PRD §4.2.3)."""

from __future__ import annotations


def initial_status(name: str, allowed_tags: list[str]) -> str:
    """A tag within the tenant's curated ``allowed_tags`` list is auto-approved; any other
    (model-proposed, novel) tag name starts ``pending`` admin review."""
    return "approved" if name in allowed_tags else "pending"
