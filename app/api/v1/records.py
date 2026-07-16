"""M4 Records API — dataset upload/list/delete + resolved-schema lookup (admin-only).

Upload validation is fully server-side; the FE renders the returned ``DatasetUploadReport``
verbatim. All endpoints are tenant-scoped via ``get_db`` and gated by ``records:manage``.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_staff, get_db, require_permission
from app.api.errors import AppError
from app.core.security import encrypt_credential
from app.domain.records.schemas import Industry, RecordSchema, get_schema, record_types_for
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.connectors.db_resolver import dispose_engine
from app.infra.connectors.oauth import clear_cached_token
from app.infra.db.models.records import Connector, RecordDataset
from app.infra.db.models.tenant import Tenant
from app.schemas.auth import StaffContext
from app.schemas.records import (
    ConnectorDetail,
    ConnectorIn,
    ConnectorListItem,
    ConnectorOut,
    ConnectorPatchIn,
    ConnectorTestIn,
    ConnectorTestReport,
    ConnectorValidateIn,
    DatasetOut,
    DatasetUploadReport,
    LiveRecordResponse,
    RecordSchemaOut,
)
from app.services.record_service import (
    build_resolver,
    get_resolver,
    refetch_linked_record,
    replace_dataset,
    validate_dataset,
)

_DIALECT_LABELS = {
    "postgresql": "PostgreSQL",
    "mysql": "MySQL / MariaDB",
    "mssql": "SQL Server",
    "oracle": "Oracle",
    "sqlite": "SQLite",
}

_SECRETISH_KEYS = {"secret", "password", "client_secret", "credentials", "token", "value", "dsn"}


def _mask_config(config: dict | None) -> dict:
    """Defense-in-depth: never echo a secret-looking value. Secrets are stored in
    ``encrypted_credentials`` and only ever merged into config in-memory, but scrub anyway."""

    def scrub(node: dict) -> dict:
        out: dict = {}
        for key, val in node.items():
            if key.lower() in _SECRETISH_KEYS:
                out[key] = "••••"
            elif isinstance(val, dict):
                out[key] = scrub(val)
            else:
                out[key] = val
        return out

    return scrub(config or {})


def _connector_summary(c: Connector) -> str:
    cfg = c.config or {}
    if c.source_type == "db":
        label = _DIALECT_LABELS.get(cfg.get("dialect", "postgresql"), cfg.get("dialect", "database"))
        if cfg.get("host"):
            return f"{label} · {cfg['host']}:{cfg.get('port', 5432)}/{cfg.get('database', '')}"
        return f"{label} · connection string"
    auth = (cfg.get("auth") or {}).get("type") or ("api key" if cfg.get("auth_header") else "no auth")
    return f"{auth.replace('_', ' ')} · {cfg.get('base_url', '')}"


def _connector_out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=str(c.id),
        record_type=c.record_type,
        source_type=c.source_type,
        version=c.version,
        enabled=c.enabled,
        has_credentials=bool(c.encrypted_credentials),
        config_summary=_mask_config(c.config),
        last_tested_at=c.last_tested_at,
        last_test_ok=c.last_test_ok,
        last_test_error=c.last_test_error,
        updated_at=c.updated_at,
    )


def _connector_list_item(c: Connector) -> ConnectorListItem:
    return ConnectorListItem(
        id=str(c.id),
        record_type=c.record_type,
        source_type=c.source_type,
        summary=_connector_summary(c),
        version=c.version,
        enabled=c.enabled,
        has_credentials=bool(c.encrypted_credentials),
        last_tested_at=c.last_tested_at,
        last_test_ok=c.last_test_ok,
        last_test_error=c.last_test_error,
        updated_at=c.updated_at,
    )

router = APIRouter(
    prefix="/records",
    tags=["records"],
    dependencies=[Depends(require_permission("records:manage"))],
)


async def _industry(session: AsyncSession, tenant_id: str) -> Industry:
    tenant = await session.get(Tenant, uuid.UUID(tenant_id))
    if tenant is None:
        raise AppError(status_code=404, title="Tenant not found", code="tenant_not_found")
    return Industry(tenant.industry)


# --- M1 upload template (person-3): rendered from the frozen schema registry, never copied ----


def _template_columns(schema: RecordSchema) -> list[str]:
    """Key + alias keys + every verify field + returned/optional fields, de-duplicated in order —
    the columns a tenant fills with their own customer records."""
    seen: list[str] = []
    for col in (
        schema.key_field,
        *schema.alias_keys,
        *(v.field for v in schema.verify),
        *schema.returned_fields,
        *schema.optional_fields,
    ):
        if col not in seen:
            seen.append(col)
    return seen


@router.get("/templates/{record_type}")
async def get_record_template(
    record_type: str,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
):
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, record_type)
    if schema is None:
        raise AppError(
            status_code=404,
            title="Unknown record type for this tenant's industry",
            code="invalid_record_type",
        )
    columns = _template_columns(schema)
    if format == "json":
        return {
            "record_type": schema.record_type,
            "key_field": schema.key_field,
            "alias_keys": list(schema.alias_keys),
            "verify_fields": [v.field for v in schema.verify],
            "returned_fields": list(schema.returned_fields),
            "optional_fields": list(schema.optional_fields),
            "columns": columns,
        }
    buf = io.StringIO()
    csv.writer(buf).writerow(columns)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"content-disposition": f'attachment; filename="{record_type}_template.csv"'},
    )


@router.get("/schema", response_model=list[RecordSchemaOut])
async def get_records_schema(
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> list[RecordSchemaOut]:
    industry = await _industry(session, staff.tenant_id)
    out: list[RecordSchemaOut] = []
    for record_type in record_types_for(industry):
        schema = get_schema(industry, record_type)
        out.append(
            RecordSchemaOut(
                record_type=record_type,
                key=schema.key_field,
                alias_keys=list(schema.alias_keys),
                verify_fields=[v.field for v in schema.verify],
                returned_fields=list(schema.returned_fields),
                optional_fields=list(schema.optional_fields),
            )
        )
    return out


@router.post("/datasets", response_model=DatasetUploadReport)
async def upload_dataset(
    record_type: str = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> DatasetUploadReport:
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, record_type)
    if schema is None or record_type not in record_types_for(industry):
        raise AppError(
            status_code=422,
            title="Invalid record type for this industry",
            code="invalid_record_type",
            detail=f"{record_type!r} not in {record_types_for(industry)}",
        )
    data = await file.read()
    rows, report = validate_dataset(
        schema, record_type, data, content_type=file.content_type, filename=file.filename
    )
    if report.ok:
        await replace_dataset(session, record_type=record_type, rows=rows)
    return report


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(session: AsyncSession = Depends(get_db)) -> list[DatasetOut]:
    rows = (
        await session.execute(select(RecordDataset).order_by(RecordDataset.record_type))
    ).scalars().all()
    return [
        DatasetOut(record_type=d.record_type, row_count=d.row_count, updated_at=d.updated_at)
        for d in rows
    ]


@router.delete("/datasets/{record_type}", status_code=204)
async def delete_dataset(
    record_type: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    dataset = (
        await session.execute(
            select(RecordDataset).where(RecordDataset.record_type == record_type)
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise AppError(status_code=404, title="Dataset not found", code="dataset_not_found")
    # Rows go via a full replace with an empty set (keeps the atomic-swap path in one place).
    await replace_dataset(session, record_type=record_type, rows=[])
    await session.delete(dataset)


async def _pause_active_siblings(session: AsyncSession, *, record_type: str, keep_id) -> None:
    """Disable every OTHER connector of this record_type so exactly one stays active — for real via
    the uq_connector_active_per_type partial unique index. Run (and flush) BEFORE enabling the
    target, since a partial unique index is not deferrable: two rows must never be enabled at once.
    No version bump / engine dispose here — a paused sibling keeps its small cached engine until its
    next edit/delete. ponytail: dispose paused siblings only if idle-connection pressure shows up."""
    await session.execute(
        update(Connector)
        .where(
            Connector.record_type == record_type,
            Connector.id != keep_id,
            Connector.enabled.is_(True),
        )
        .values(enabled=False)
    )
    await session.flush()


@router.post("/connectors", response_model=ConnectorOut, status_code=201)
async def create_connector(
    body: ConnectorIn,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> ConnectorOut:
    """Add a connector for a record_type. A record_type may have many; this one goes live only if
    the slot is free (no sibling is currently enabled), so adding a second source never silently
    hijacks the active one — you activate it deliberately via PATCH (which pauses the others)."""
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, body.record_type)
    if schema is None or body.record_type not in record_types_for(industry):
        raise AppError(status_code=422, title="Invalid record type", code="invalid_record_type")
    if body.source_type not in ("db", "api"):
        raise AppError(status_code=422, title="source_type must be 'db' or 'api'", code="invalid_source_type")
    # [A10]: a source that can't surface the verify field cannot back a verified record_type.
    verify_fields = {v.field for v in schema.verify}
    if not (verify_fields & set(body.field_map.values())):
        raise AppError(
            status_code=422,
            title="Field mapping must produce the verify field",
            code="missing_verify_mapping",
            detail=f"map a source field to one of: {sorted(verify_fields)}",
        )

    active_exists = (
        await session.execute(
            select(Connector.id).where(
                Connector.record_type == body.record_type, Connector.enabled.is_(True)
            )
        )
    ).first() is not None
    connector = Connector(
        record_type=body.record_type,
        source_type=body.source_type,
        version=1,
        encrypted_credentials="",
        config=body.config,
        field_map=body.field_map,
        enabled=not active_exists,  # first source for a type goes live; extras start paused
    )
    session.add(connector)
    await session.flush()  # obtain id for the AAD binding
    connector.encrypted_credentials = encrypt_credential(
        body.credentials, tenant_id=staff.tenant_id, connector_id=str(connector.id)
    )
    await session.flush()
    await session.refresh(connector)  # load server-generated updated_at before serializing (async)
    return _connector_out(connector)


@router.post("/connectors/{connector_id}/test", response_model=ConnectorTestReport)
async def test_connector(
    connector_id: uuid.UUID,
    body: ConnectorTestIn,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> ConnectorTestReport:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise AppError(status_code=404, title="Connector not found", code="connector_not_found")
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, connector.record_type)
    verify_fields = {v.field for v in schema.verify}

    resolver = await get_resolver(session, staff.tenant_id, connector.record_type)
    try:
        raw = await resolver.fetch(staff.tenant_id, connector.record_type, body.test_key)
    except ConnectorError as exc:
        report = ConnectorTestReport(ok=False, error=f"{exc.kind}: {exc.detail}")
    else:
        if raw is NOT_FOUND:  # connectivity OK, key just not present
            report = ConnectorTestReport(ok=True, found=False)
        else:
            has_verify = any(vf in raw for vf in verify_fields)
            report = ConnectorTestReport(
                ok=has_verify,
                found=True,
                has_verify_field=has_verify,
                error=None if has_verify else "field mapping did not produce the verify field",
            )
    _record_health(connector, report)
    return report


def _record_health(connector: Connector, report: ConnectorTestReport) -> None:
    """Persist the on-demand health of a test on the connector row (never on the read path)."""
    connector.last_tested_at = datetime.now(timezone.utc)
    connector.last_test_ok = report.ok
    connector.last_test_error = (report.error or "")[:300] or None


@router.get("/connectors", response_model=list[ConnectorListItem])
async def list_connectors(session: AsyncSession = Depends(get_db)) -> list[ConnectorListItem]:
    rows = (
        await session.execute(select(Connector).order_by(Connector.record_type))
    ).scalars().all()
    return [_connector_list_item(c) for c in rows]


@router.post("/connectors/validate", response_model=ConnectorTestReport)
async def validate_connector(
    body: ConnectorValidateIn,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> ConnectorTestReport:
    """Test-before-save: build an ephemeral resolver from unsaved config + secret, run one lookup,
    persist nothing. Lets the admin confirm a connector works before committing it."""
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, body.record_type)
    if schema is None or body.record_type not in record_types_for(industry):
        raise AppError(status_code=422, title="Invalid record type", code="invalid_record_type")
    if body.source_type not in ("db", "api"):
        raise AppError(status_code=422, title="source_type must be 'db' or 'api'",
                       code="invalid_source_type")
    verify_fields = {v.field for v in schema.verify}
    ephemeral_id = str(uuid.uuid4())  # unique cache key; disposed below for db
    resolver = build_resolver(
        source_type=body.source_type,
        config=body.config,
        field_map=body.field_map,
        secret=body.credentials,
        connector_id=ephemeral_id,
        version=1,
    )
    try:
        raw = await resolver.fetch(staff.tenant_id, body.record_type, body.test_key)
    except ConnectorError as exc:
        return ConnectorTestReport(ok=False, error=f"{exc.kind}: {exc.detail}")
    finally:
        if body.source_type == "db":
            await dispose_engine(ephemeral_id)
    if raw is NOT_FOUND:
        return ConnectorTestReport(ok=True, found=False)
    has_verify = any(vf in raw for vf in verify_fields)
    return ConnectorTestReport(
        ok=has_verify,
        found=True,
        has_verify_field=has_verify,
        error=None if has_verify else "field mapping did not produce the verify field",
    )


@router.get("/connectors/{connector_id}", response_model=ConnectorDetail)
async def get_connector(
    connector_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> ConnectorDetail:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise AppError(status_code=404, title="Connector not found", code="connector_not_found")
    item = _connector_list_item(connector)
    return ConnectorDetail(
        **item.model_dump(),
        config=_mask_config(connector.config),
        field_map=connector.field_map,
    )


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
async def patch_connector(
    connector_id: uuid.UUID,
    body: ConnectorPatchIn,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> ConnectorOut:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise AppError(status_code=404, title="Connector not found", code="connector_not_found")
    if body.enabled is not None:
        if body.enabled:
            # Activating: pause siblings FIRST (the partial unique index is not deferrable), then
            # enable this one — so this record_type's single source of truth switches atomically.
            await _pause_active_siblings(
                session, record_type=connector.record_type, keep_id=connector.id
            )
        connector.enabled = body.enabled
    if body.field_map is not None:
        connector.field_map = body.field_map
    if body.config is not None:
        connector.config = body.config
    # [A10]: the resulting field map must still produce a verify field.
    industry = await _industry(session, staff.tenant_id)
    schema = get_schema(industry, connector.record_type)
    verify_fields = {v.field for v in schema.verify}
    if not (verify_fields & set(connector.field_map.values())):
        raise AppError(
            status_code=422,
            title="Field mapping must produce the verify field",
            code="missing_verify_mapping",
            detail=f"map a source field to one of: {sorted(verify_fields)}",
        )
    if body.credentials is not None:
        connector.encrypted_credentials = encrypt_credential(
            body.credentials, tenant_id=staff.tenant_id, connector_id=str(connector.id)
        )
    prev_version = connector.version
    connector.version += 1  # invalidate cached engine + OAuth token
    await session.flush()
    await session.refresh(connector)  # load server-generated updated_at before serializing (async)
    await dispose_engine(str(connector.id))
    await clear_cached_token(str(connector.id), prev_version)
    return _connector_out(connector)


@router.delete("/connectors/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise AppError(status_code=404, title="Connector not found", code="connector_not_found")
    cid, version = str(connector.id), connector.version
    await session.delete(connector)
    await session.flush()
    await dispose_engine(cid)  # free the pool; record_type now falls back to its upload dataset
    await clear_cached_token(cid, version)


# Live re-fetch (Phase 3) — any authenticated staff (admins AND agents), NOT gated by
# `records:manage`, so the agent workspace can pull a ticket's live linked record.
live_router = APIRouter(prefix="/records", tags=["records"])


@live_router.get("/live/{record_type}/{key}", response_model=LiveRecordResponse)
async def refetch_live_record(
    record_type: str,
    key: str,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> LiveRecordResponse:
    industry = await _industry(session, staff.tenant_id)
    return await refetch_linked_record(
        session, tenant_id=staff.tenant_id, industry=industry, record_type=record_type, key=key
    )
