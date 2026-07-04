"""StoragePort — file bytes live in a tenant-scoped ``bytea`` column (audit [IMP-SEC-2]),
NOT Postgres Large Objects, so the same RLS policy that governs every table governs the
bytes too. This port abstracts read/write/delete of a file blob keyed by (tenant, file_id).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StoragePort(Protocol):
    async def put(self, session, *, tenant_id: str, file_id: str, data: bytes,
                  content_type: str, filename: str) -> None: ...

    async def get(self, session, *, tenant_id: str, file_id: str) -> bytes | None: ...

    async def delete(self, session, *, tenant_id: str, file_id: str) -> None: ...
