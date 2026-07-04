"""M4 Records API — dataset upload/list/delete + resolved-schema lookup (admin-only).

Upload validation is fully server-side; the FE renders the returned ``DatasetUploadReport``
verbatim. All endpoints are tenant-scoped via ``get_db`` and gated by ``records:manage``.
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_staff, get_db, require_permission
from app.api.errors import AppError
from app.core.security import encrypt_credential
from app.domain.records.schemas import Industry, RecordSchema, get_schema, record_types_for
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.infra.db.models.records import Connector, RecordDataset
from app.infra.db.models.tenant import Tenant
from app.schemas.auth import StaffContext
from app.schemas.records import (
    ConnectorIn,
    ConnectorOut,
    ConnectorTestIn,
    ConnectorTestReport,
    DatasetOut,
    DatasetUploadReport,
    LiveRecordResponse,
    RecordSchemaOut,
)
from app.services.record_service import (
    get_resolver,
    refetch_linked_record,
    replace_dataset,
    validate_dataset,
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


@router.post("/connectors", response_model=ConnectorOut, status_code=201)
async def upsert_connector(
    body: ConnectorIn,
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> ConnectorOut:
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

    connector = (
        await session.execute(select(Connector).where(Connector.record_type == body.record_type))
    ).scalar_one_or_none()
    if connector is None:
        connector = Connector(
            record_type=body.record_type,
            source_type=body.source_type,
            version=1,
            encrypted_credentials="",
            config=body.config,
            field_map=body.field_map,
        )
        session.add(connector)
        await session.flush()  # obtain id for the AAD binding
    else:
        connector.source_type = body.source_type
        connector.config = body.config
        connector.field_map = body.field_map
        connector.version += 1  # invalidate any cached engine/client
    connector.encrypted_credentials = encrypt_credential(
        body.credentials, tenant_id=staff.tenant_id, connector_id=str(connector.id)
    )
    await session.flush()
    return ConnectorOut(
        id=str(connector.id),
        record_type=connector.record_type,
        source_type=connector.source_type,
        version=connector.version,
    )


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
        return ConnectorTestReport(ok=False, error=f"{exc.kind}: {exc.detail}")

    if raw is NOT_FOUND:
        return ConnectorTestReport(ok=True, found=False)  # connectivity OK, key just not present
    has_verify = any(vf in raw for vf in verify_fields)
    return ConnectorTestReport(
        ok=has_verify,
        found=True,
        has_verify_field=has_verify,
        error=None if has_verify else "field mapping did not produce the verify field",
    )


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
