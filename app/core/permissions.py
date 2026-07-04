"""Static RBAC catalog (audit [C5]): admin + agent staff roles, plus the platform operator.

No ``owner`` tier and no per-endpoint checks — one ``require_permission`` dependency reads
this map. First signup becomes an admin; multiple admins are allowed.
"""

from __future__ import annotations

ADMIN = "admin"
AGENT = "agent"
PLATFORM = "platform"  # M10 operator — a separate platform-level principal, not a tenant role

ROLE_PERMISSIONS: dict[str, set[str]] = {
    ADMIN: {
        "kb:manage",
        "records:manage",
        "settings:manage",
        "staff:manage",
        "tags:approve",
        "tickets:read",
        "analytics:read",
        "embed:read",
        "agents:queue",
        "tickets:claim",
        "tickets:reply",
    },
    AGENT: {
        "agents:queue",
        "tickets:read",
        "tickets:claim",
        "tickets:reply",
    },
    PLATFORM: {"ops:read", "ops:manage"},
}


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))
