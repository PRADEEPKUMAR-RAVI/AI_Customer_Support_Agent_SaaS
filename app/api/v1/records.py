"""``GET /records/templates/{record_type}`` — per-industry CSV/JSON upload template, rendered
from Person-2's frozen record-schema registry (`app/domain/records/schemas.py`). One source of
truth: this endpoint never copies field/key/verify definitions — it only reads them.

Person-2's M4 (dataset upload, connectors) adds more routes to this file later; this endpoint
is the M1 piece of the `/records` surface.
"""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.errors import AppError
from app.domain.records.schemas import Industry, RecordSchema, get_schema
from app.infra.db.models.tenant import Tenant
from app.schemas.auth import StaffContext

router = APIRouter(prefix="/records", tags=["records"])


def _template_columns(schema: RecordSchema) -> list[str]:
    """Key + alias keys + every verify field + returned/optional fields, de-duplicated in
    order — the columns a tenant fills in with their own customer records."""
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
    staff: StaffContext = Depends(require_permission("records:manage")),
):
    tenant = (
        await session.execute(select(Tenant).where(Tenant.id == uuid.UUID(staff.tenant_id)))
    ).scalar_one()
    industry = Industry(tenant.industry)
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
        headers={
            "content-disposition": f'attachment; filename="{record_type}_template.csv"'
        },
    )
