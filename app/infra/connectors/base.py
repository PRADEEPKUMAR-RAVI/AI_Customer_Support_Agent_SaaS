"""Resolver seam for record data sources (PRD §4.9, audit [C3][DEL-3]).

Contract: ``fetch(tenant, record_type, key) -> RawRecord | NOT_FOUND``, raising
``ConnectorError`` on timeout / auth / connection failure. The resolver ONLY fetches — it
never receives the verify value and never decides "verified" (that stays in M2 engine code).
``RawRecord`` carries the verify-field value **plus** the returned fields so the engine can
run the §4.8.2 comparison.

POC scope [T4]: Upload fully + one DB (Postgres) + one API shape. Other SQL dialects,
per-dialect timeout tuning, and pub/sub engine-cache invalidation are post-POC.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# A raw record is the mapped {verify-field value + returned fields} dict, or NOT_FOUND.
RawRecord = dict


class _NotFound:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover
        return "NOT_FOUND"


NOT_FOUND = _NotFound()


class ConnectorError(Exception):
    """Timeout / auth / connection failure. The engine maps this to the tool-failure
    fallback→escalate path (same handling as any slow/failed tool, §4.1)."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind  # "timeout" | "auth" | "connection"
        self.detail = detail


@runtime_checkable
class Resolver(Protocol):
    async def fetch(
        self, tenant_id: str, record_type: str, key: str
    ) -> RawRecord | _NotFound: ...
