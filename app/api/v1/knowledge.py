"""M3 Knowledge API — source ingestion + status (admin-only, gated by ``kb:manage``).

Upload is two sub-routes because one endpoint can't cleanly accept multipart OR JSON:
``POST /knowledge/sources/file`` (multipart) and ``POST /knowledge/sources/paste`` (JSON). Each
creates a ``Source`` (``queued``) + a ``FileBlob`` (shared id = 1:1 raw-bytes store), commits,
then dispatches ingestion — via the Celery ``batch`` worker, or inline when ``INGEST_INLINE`` is
set (broker-less dev/test). The client polls ``GET /knowledge/sources/{id}`` until ready|failed.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_staff, get_db, require_permission
from app.api.errors import AppError
from app.core.config import TenantDefaults, get_settings
from app.infra.db.engine import SessionLocal
from app.infra.db.models.knowledge import FileBlob, Source
from app.infra.db.session import set_tenant_guc
from app.infra.parsers import UnsupportedFormat, get_parser
from app.schemas.auth import StaffContext
from app.schemas.common import Page
from app.schemas.knowledge import PasteSourceIn, SourceOut, UrlSourceIn
from app.services.knowledge_service import delete_source, reingest_source, run_ingest
from app.workers.ingestion import ingest_source_task, reingest_source_task

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_permission("kb:manage"))],
)


def _to_out(source: Source) -> SourceOut:
    return SourceOut(
        id=str(source.id),
        kind=source.kind,
        name=source.name,
        status=source.status,
        error=source.error,
        chunk_count=source.chunk_count,
        bytes=source.bytes,
        source_url=source.source_url,
        created_at=source.created_at,
    )


async def _create_and_dispatch(
    tenant_id: str,
    *,
    kind: str,
    name: str,
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> SourceOut:
    """Validate → persist Source(queued)+FileBlob (committed) → dispatch ingest. Enqueue AFTER
    commit so the worker's own transaction can see the row."""
    settings = get_settings()
    size = len(data)
    if size > TenantDefaults.MAX_FILE_BYTES:
        raise AppError(
            status_code=413,
            title="File too large",
            code="file_too_large",
            detail=f"max {TenantDefaults.MAX_FILE_BYTES} bytes",
        )
    # Fail at 415 before creating anything if no Phase-1 parser handles this source.
    try:
        get_parser(kind, filename, content_type)
    except UnsupportedFormat as exc:
        raise AppError(
            status_code=415, title="Unsupported format", code="unsupported_format", detail=exc.detail
        ) from exc

    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, tenant_id)
            used = await session.scalar(select(func.coalesce(func.sum(Source.bytes), 0)))
            if (used or 0) + size > TenantDefaults.KB_TOTAL_BYTES_LIMIT:
                raise AppError(
                    status_code=413,
                    title="Knowledge-base quota exceeded",
                    code="kb_quota_exceeded",
                    detail=f"per-tenant limit {TenantDefaults.KB_TOTAL_BYTES_LIMIT} bytes",
                )
            source = Source(kind=kind, name=name, status="queued", bytes=size, chunk_count=0)
            session.add(source)
            await session.flush()
            await session.refresh(source)  # load server-default created_at
            source_id = source.id
            session.add(
                FileBlob(
                    id=source_id,
                    filename=filename or name,
                    content_type=content_type or "text/plain",
                    data=data,
                )
            )
            out = _to_out(source)

    # Committed. Dispatch ingestion.
    if settings.ingest_inline:
        await run_ingest(source_id=source_id, tenant_id=uuid.UUID(tenant_id))
        async with SessionLocal() as session:
            async with session.begin():
                await set_tenant_guc(session, tenant_id)
                refreshed = await session.get(Source, source_id)
                out = _to_out(refreshed) if refreshed is not None else out
    else:
        ingest_source_task.delay(str(source_id), tenant_id)
    return out


@router.post("/sources/file", response_model=SourceOut, status_code=201)
async def upload_file_source(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    staff: StaffContext = Depends(get_current_staff),
) -> SourceOut:
    data = await file.read()
    return await _create_and_dispatch(
        staff.tenant_id,
        kind="file",
        name=name or file.filename or "upload",
        filename=file.filename,
        content_type=file.content_type,
        data=data,
    )


@router.post("/sources/paste", response_model=SourceOut, status_code=201)
async def create_paste_source(
    body: PasteSourceIn,
    staff: StaffContext = Depends(get_current_staff),
) -> SourceOut:
    return await _create_and_dispatch(
        staff.tenant_id,
        kind="paste",
        name=body.name,
        filename=f"{body.name}.txt",
        content_type="text/plain",
        data=body.content.encode("utf-8"),
    )


@router.post("/sources/url", response_model=SourceOut, status_code=201)
async def create_url_source(
    body: UrlSourceIn,
    staff: StaffContext = Depends(get_current_staff),
) -> SourceOut:
    """Create a URL source (no FileBlob — the crawler fetches at ingest time)."""
    settings = get_settings()
    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, staff.tenant_id)
            source = Source(
                kind="url", name=body.name, status="queued", bytes=0, chunk_count=0,
                source_url=body.url,
            )
            session.add(source)
            await session.flush()
            source_id = source.id
            out = _to_out(source)

    if settings.ingest_inline:
        await run_ingest(source_id=source_id, tenant_id=uuid.UUID(staff.tenant_id))
        async with SessionLocal() as session:
            async with session.begin():
                await set_tenant_guc(session, staff.tenant_id)
                refreshed = await session.get(Source, source_id)
                out = _to_out(refreshed) if refreshed is not None else out
    else:
        ingest_source_task.delay(str(source_id), staff.tenant_id)
    return out


@router.get("/sources", response_model=Page[SourceOut])
async def list_sources(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_db),
) -> Page[SourceOut]:
    total = await session.scalar(select(func.count()).select_from(Source))
    rows = (
        await session.execute(
            select(Source).order_by(Source.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return Page[SourceOut](
        items=[_to_out(s) for s in rows], total=total or 0, limit=limit, offset=offset
    )


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> SourceOut:
    source = await session.get(Source, source_id)
    if source is None:
        raise AppError(status_code=404, title="Source not found", code="source_not_found")
    return _to_out(source)


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source_endpoint(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    source = await session.get(Source, source_id)
    if source is None:
        raise AppError(status_code=404, title="Source not found", code="source_not_found")
    if source.status in ("ingesting", "reingesting"):
        raise AppError(
            status_code=409, title="Source is currently ingesting", code="source_busy"
        )
    await delete_source(session, source_id=source_id)


@router.post("/sources/{source_id}/reingest", response_model=SourceOut)
async def reingest_source_endpoint(
    source_id: uuid.UUID,
    staff: StaffContext = Depends(get_current_staff),
) -> SourceOut:
    """Delete-last reingest ([IMP-RAG-8]): the current generation keeps answering while the new one
    is built; the serving pointer flips atomically; the old generation is deleted last. A failed
    reingest leaves the old version live. We do NOT flip the source to ``queued`` here (that would
    drop it from serving) — ``reingest_source`` owns the ``reingesting`` FSM."""
    settings = get_settings()
    async with SessionLocal() as session:
        async with session.begin():
            await set_tenant_guc(session, staff.tenant_id)
            source = await session.get(Source, source_id)
            if source is None:
                raise AppError(status_code=404, title="Source not found", code="source_not_found")
            if source.status in ("ingesting", "reingesting"):
                raise AppError(
                    status_code=409, title="Source is currently ingesting", code="source_busy"
                )
            out = _to_out(source)

    if settings.ingest_inline:
        await reingest_source(source_id=source_id, tenant_id=uuid.UUID(staff.tenant_id))
        async with SessionLocal() as session:
            async with session.begin():
                await set_tenant_guc(session, staff.tenant_id)
                refreshed = await session.get(Source, source_id)
                out = _to_out(refreshed) if refreshed is not None else out
    else:
        reingest_source_task.delay(str(source_id), staff.tenant_id)
    return out
