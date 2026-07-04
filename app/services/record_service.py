"""M4 — Records & Connectors: resolver dispatch + the engine-side ``lookup_record`` assembler.

The non-negotiable split ([C3]/[IMP-DEL-3]): **resolvers only FETCH** the raw record (verify-field
value + returned fields); **verification + status assembly live here** in ``lookup_record`` (engine
code), never in a resolver and never in the model. ``not_found`` and ``unverified`` return the SAME
customer message so keys can't be enumerated; the durable per-``(tenant, record_type, key)`` counter
([IMP-SEC-6]) counts only failed *verify* attempts (not benign not-founds, per [IMP-ESC-4]).
"""

from __future__ import annotations

import csv
import io
import json
import uuid

from sqlalchemy import delete, or_, select

from app.core import ratelimit
from app.core.config import TenantDefaults
from app.core.security import decrypt_credential
from app.domain.records.schemas import (
    Industry,
    RecordSchema,
    get_schema,
    max_verify_attempts,
    record_types_for,
    verify_record,
)
from app.infra.connectors.api_resolver import ApiResolver
from app.infra.connectors.base import NOT_FOUND, ConnectorError, RawRecord, Resolver, _NotFound
from app.infra.connectors.db_resolver import DbResolver
from app.infra.db.models.records import Connector, RecordDataset, RecordRow
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.schemas.records import (
    DatasetUploadReport,
    LiveRecordResponse,
    LookupRecordResponse,
    LookupStatus,
    RowErrorOut,
)


def _verify_counter_key(tenant_id, record_type: str, key: str) -> str:
    return f"verify:{tenant_id}:{record_type}:{key}"


class UploadResolver(Resolver):
    """Reads the tenant's uploaded ``record_row`` store. Matches the provided value against the
    schema's primary key OR any alias key ([C2], e.g. warranty ``order_id``). Fetch only."""

    async def fetch(self, tenant_id: str, record_type: str, key: str) -> RawRecord | _NotFound:
        async with with_tenant(tenant_id) as session:
            tenant = await session.get(Tenant, uuid.UUID(str(tenant_id)))
            schema = get_schema(Industry(tenant.industry), record_type) if tenant else None

            conditions = [RecordRow.key == str(key)]
            if schema is not None:
                for alias in schema.alias_keys:
                    conditions.append(RecordRow.data[alias].astext == str(key))

            row = (
                await session.execute(
                    select(RecordRow).where(
                        RecordRow.record_type == record_type, or_(*conditions)
                    )
                )
            ).scalars().first()
            return dict(row.data) if row is not None else NOT_FOUND


async def get_resolver(session, tenant_id: str, record_type: str) -> Resolver:
    """Dispatch to the resolver backing this record_type: a configured Connector (db/api) if one
    exists, else the uploaded dataset. Credentials are decrypted here (AAD-bound to tenant+id)."""
    connector = (
        await session.execute(select(Connector).where(Connector.record_type == record_type))
    ).scalar_one_or_none()
    if connector is None:
        return UploadResolver()

    secret = decrypt_credential(
        connector.encrypted_credentials,
        tenant_id=str(tenant_id),
        connector_id=str(connector.id),
    )
    if connector.source_type == "db":
        return DbResolver(
            connector_id=str(connector.id),
            version=connector.version,
            dsn=secret,
            query_template=connector.config["query_template"],
            field_map=connector.field_map,
        )
    if connector.source_type == "api":
        cfg = connector.config
        return ApiResolver(
            base_url=cfg["base_url"],
            path_template=cfg.get("path_template", "/{key}"),
            field_map=connector.field_map,
            method=cfg.get("method", "GET"),
            auth_header=cfg.get("auth_header"),
            auth_scheme=cfg.get("auth_scheme"),
            auth_secret=secret,
        )
    return UploadResolver()


async def lookup_record(
    session,
    *,
    tenant_id,
    industry: Industry,
    record_type: str,
    key: str,
    verify_value: str | None,
) -> LookupRecordResponse:
    """Engine-side tool implementation: validate type -> lockout check -> fetch -> verify-in-code
    -> assemble status/record. Raises ``ConnectorError`` (does NOT swallow) so the engine can map a
    connector failure to its tool-failure fallback -> escalate path."""
    schema = get_schema(industry, record_type)
    if schema is None or record_type not in record_types_for(industry):
        return LookupRecordResponse(status=LookupStatus.INVALID_TYPE)

    counter_key = _verify_counter_key(tenant_id, record_type, key)
    cap = max_verify_attempts(industry)
    if await ratelimit.current(counter_key) >= cap:
        return LookupRecordResponse(status=LookupStatus.RATE_LIMITED)

    resolver = await get_resolver(session, tenant_id, record_type)
    raw = await resolver.fetch(str(tenant_id), record_type, str(key))  # ConnectorError propagates

    if raw is NOT_FOUND:
        # benign (typo / wrong id) — do NOT count against the verify lockout ([IMP-ESC-4]).
        return LookupRecordResponse(status=LookupStatus.NOT_FOUND)

    if verify_value is None or not verify_record(schema, verify_value, raw):
        # failed identity check — count it; same customer message as not_found.
        await ratelimit.hit(
            counter_key, limit=cap, window_seconds=TenantDefaults.VERIFY_LOCKOUT_SECONDS
        )
        return LookupRecordResponse(status=LookupStatus.UNVERIFIED)

    await ratelimit.reset(counter_key)  # clear the counter on a verified success
    fields = (*schema.returned_fields, *schema.optional_fields)
    record = {f: raw[f] for f in fields if f in raw}
    return LookupRecordResponse(status=LookupStatus.OK, record=record)


async def refetch_linked_record(
    session, *, tenant_id, industry: Industry, record_type: str, key: str
) -> LiveRecordResponse:
    """Phase 3: internal, already-verified STAFF read for the agent workspace, keyed by the
    ticket's linked-record pointer. NO customer verify + NO attempt counter (the staff member is
    authorized). A connector failure returns ``available=False`` ("live data unavailable — retry"),
    distinct from a record that no longer exists (``available=True, record=None``)."""
    schema = get_schema(industry, record_type)
    if schema is None:
        return LiveRecordResponse(available=True, record=None)
    resolver = await get_resolver(session, tenant_id, record_type)
    try:
        raw = await resolver.fetch(str(tenant_id), record_type, str(key))
    except ConnectorError:
        return LiveRecordResponse(available=False)
    if raw is NOT_FOUND:
        return LiveRecordResponse(available=True, record=None)
    fields = (*schema.returned_fields, *schema.optional_fields)
    return LiveRecordResponse(available=True, record={f: raw[f] for f in fields if f in raw})


# --- Upload dataset validation + atomic replacement ---------------------------------------

def _known_fields(schema: RecordSchema) -> set[str]:
    return {
        schema.key_field,
        *(v.field for v in schema.verify),
        *schema.returned_fields,
        *schema.optional_fields,
        *schema.alias_keys,
    }


def validate_dataset(
    schema: RecordSchema, record_type: str, data: bytes, *, content_type: str | None, filename: str | None
) -> tuple[list[dict], DatasetUploadReport]:
    """Parse CSV/JSON and validate against the schema. Returns (rows, report). ``rows`` is empty
    unless the report is ``ok``. Rules (§4.8): headers must match schema field names exactly, the
    key is required + unique, at least one verify field must be present; 50k cap (log-truncate)."""
    text = data.decode("utf-8", errors="replace")
    is_json = bool(content_type and "json" in content_type) or bool(
        filename and filename.lower().endswith(".json")
    )

    if is_json:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], DatasetUploadReport(
                ok=False, record_type=record_type, row_errors=[RowErrorOut(row=0, error=f"invalid JSON: {exc}")]
            )
        if not isinstance(parsed, list):
            return [], DatasetUploadReport(
                ok=False, record_type=record_type,
                row_errors=[RowErrorOut(row=0, error="JSON must be a list of record objects")],
            )
        records = [r for r in parsed if isinstance(r, dict)]
        header = set().union(*(r.keys() for r in records)) if records else set()
    else:
        reader = csv.DictReader(io.StringIO(text))
        header = set(reader.fieldnames or [])
        records = list(reader)

    required = {schema.key_field, *schema.returned_fields}
    missing = sorted(required - header)
    verify_fields = {v.field for v in schema.verify}
    if not (verify_fields & header):
        missing.append(f"verify field (one of: {', '.join(sorted(verify_fields))})")
    if missing:
        return [], DatasetUploadReport(ok=False, record_type=record_type, missing_headers=missing)

    known = _known_fields(schema)
    cap = TenantDefaults.MAX_ROWS_PER_RECORD_TYPE
    rows: list[dict] = []
    seen: set[str] = set()
    row_errors: list[RowErrorOut] = []
    duplicate_keys: set[str] = set()
    truncated = 0

    for i, rec in enumerate(records, start=1):
        if len(rows) >= cap:
            truncated += 1
            continue
        key_val = str(rec.get(schema.key_field, "") or "").strip()
        if not key_val:
            row_errors.append(RowErrorOut(row=i, error=f"missing {schema.key_field}"))
            continue
        if key_val in seen:
            duplicate_keys.add(key_val)
            continue
        seen.add(key_val)
        mapped = {f: rec[f] for f in known if f in rec and rec[f] not in (None, "")}
        rows.append({"key": key_val, "data": mapped})

    ok = not row_errors and not duplicate_keys
    return (rows if ok else []), DatasetUploadReport(
        ok=ok,
        record_type=record_type,
        inserted=len(rows) if ok else 0,
        truncated=truncated,
        duplicate_keys=sorted(duplicate_keys),
        row_errors=row_errors,
    )


async def replace_dataset(session, *, record_type: str, rows: list[dict]) -> None:
    """Full replacement in one transaction (MVCC keeps live lookups on old rows until commit,
    [IMP-DAT-4]). Caller owns the transaction; the tenant GUC must already be set."""
    await session.execute(delete(RecordRow).where(RecordRow.record_type == record_type))
    for row in rows:
        session.add(RecordRow(record_type=record_type, key=row["key"], data=row["data"]))
    dataset = (
        await session.execute(
            select(RecordDataset).where(RecordDataset.record_type == record_type)
        )
    ).scalar_one_or_none()
    if dataset is None:
        session.add(RecordDataset(record_type=record_type, row_count=len(rows)))
    else:
        dataset.row_count = len(rows)
