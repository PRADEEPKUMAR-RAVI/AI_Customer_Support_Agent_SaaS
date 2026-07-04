"""Retrieval eval corpus + helpers (M3 Phase 1, on FakeEmbedder/FakeReranker).

The corpus is small and deterministic so the pipeline test and the threshold-calibration test
share one ground truth. Queries are content-word phrases (search-style) chosen so on-topic pairs
clearly overlap a doc and off-topic pairs share NO tokens with any doc — this cleanly exercises
the grounding gate under the *lexical* FakeReranker. Real natural-language calibration against
BGE is Phase 2 (the reranker score scale changes, so re-calibrate then).

Includes one Spanish doc + query so the 'simple' tsvector / cross-lingual path is exercised.
"""

from __future__ import annotations

import uuid

from app.infra.db.engine import SessionLocal
from app.infra.db.models.knowledge import FileBlob, Source
from app.infra.db.models.tenant import Tenant
from app.infra.db.session import with_tenant
from app.services.knowledge_service import run_ingest

DOCS: dict[str, str] = {
    "returns-policy": (
        "Our return policy lets customers return unused items within 30 days of delivery for a "
        "full refund. Returned items must be in original packaging."
    ),
    "shipping-info": (
        "Standard shipping takes three to five business days. Express shipping arrives next "
        "business day. International orders ship worldwide."
    ),
    "warranty-terms": (
        "Every laptop includes a two year manufacturer warranty covering hardware defects. "
        "Accidental damage and water damage are excluded."
    ),
    "devoluciones-es": (
        "La politica de devoluciones permite devolver productos sin usar en treinta dias desde "
        "la entrega."
    ),
    # CJK + RTL cases. Space-tokenized so the 'simple' FTS + FakeReranker separate them under
    # fakes; real multilingual-e5 handles natural (unspaced) text directly.
    "returns-zh": "退货 政策 允许 顾客 在 三十 天 内 退回 未 使用 的 商品 并 获得 全额 退款",
    "returns-ar": "سياسة الإرجاع تسمح للعملاء بإرجاع العناصر غير المستخدمة خلال ثلاثين يوما",
}

# (query, should_answer, expected_source_name | None)
EVAL_PAIRS: list[tuple[str, bool, str | None]] = [
    ("return unused items refund", True, "returns-policy"),
    ("standard express shipping business days", True, "shipping-info"),
    ("laptop warranty hardware defects", True, "warranty-terms"),
    ("devolver productos sin usar treinta dias", True, "devoluciones-es"),
    ("退货 政策 商品 退款", True, "returns-zh"),  # CJK
    ("سياسة الإرجاع العناصر", True, "returns-ar"),  # RTL
    ("quantum entanglement subatomic particles", False, None),
    ("volcano eruption lava magma", False, None),
    ("chocolate cake baking recipe", False, None),
]


async def make_tenant(name: str, industry: str = "retail") -> uuid.UUID:
    """Create an isolated tenant (root row; not itself tenant-scoped)."""
    async with SessionLocal() as session:
        async with session.begin():
            tenant = Tenant(name=f"{name}-{uuid.uuid4().hex[:8]}", industry=industry, status="active")
            session.add(tenant)
            await session.flush()
            return tenant.id


async def ingest_paste(tenant_id: uuid.UUID, name: str, content: str) -> uuid.UUID:
    """Create a paste Source (+FileBlob) and run ingest inline. Returns the source id."""
    data = content.encode("utf-8")
    async with with_tenant(tenant_id) as session:
        source = Source(kind="paste", name=name, status="queued", bytes=len(data), chunk_count=0)
        session.add(source)
        await session.flush()
        source_id = source.id
        session.add(
            FileBlob(id=source_id, filename=f"{name}.txt", content_type="text/plain", data=data)
        )
    await run_ingest(source_id=source_id, tenant_id=tenant_id)
    return source_id


async def ingest_corpus(tenant_id: uuid.UUID) -> None:
    for name, content in DOCS.items():
        await ingest_paste(tenant_id, name, content)
