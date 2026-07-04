"""M4 — record resolver dispatch (walking-skeleton slice).

Returns a resolver that ONLY fetches ([C3]/[IMP-DEL-3]) — verification stays in the M2 engine.
Person-2 fills in the real Upload/DB/API resolvers + record data; the skeleton UploadResolver
returns NOT_FOUND because no record datasets have been uploaded yet. The CONTRACT
(`fetch -> RawRecord | NOT_FOUND | raise ConnectorError`) is what M2 codes against.
"""

from __future__ import annotations

from app.infra.connectors.base import NOT_FOUND, RawRecord, Resolver, _NotFound


class UploadResolver(Resolver):
    async def fetch(self, tenant_id: str, record_type: str, key: str) -> RawRecord | _NotFound:
        # TODO(person-2, M4): read record_row for (tenant, record_type, key). No data yet.
        return NOT_FOUND


def get_resolver(tenant_id: str, record_type: str) -> Resolver:
    # POC: Upload only. person-2 dispatches to ApiResolver / DbResolver by connector config [T4].
    return UploadResolver()
