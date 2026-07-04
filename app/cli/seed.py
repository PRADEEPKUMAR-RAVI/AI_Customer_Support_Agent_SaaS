"""Seed CLI — ≥2 tenants across ≥2 industries so the stack is demoable offline and the RLS
leak test has real cross-tenant data ([IMP-DEL-4]).

Tenant-scoped rows are inserted through ``with_tenant`` so ``tenant_id`` auto-fills from the
GUC and RLS ``WITH CHECK`` is satisfied. (M4 record datasets with deliberately colliding keys
like ``order_id=1001`` across tenants are added when P2 builds M4 — noted, not silently
skipped.)
"""

from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.core.security import hash_password
from app.domain.records.schemas import Industry
from app.domain.tenancy.defaults import default_agent_settings
from app.infra.db.engine import SessionLocal
from app.infra.db.models.knowledge import KbChunk, Source
from app.infra.db.models.tenant import AgentSettings, Staff, Tenant, WidgetKey
from app.infra.db.session import with_tenant
from app.infra.embeddings.router import get_embedder

_TENANTS = [
    ("Acme Retail", Industry.RETAIL, "admin@acme.test", "wk_seed_retail"),
    ("Wellness Clinic", Industry.HEALTHCARE, "admin@wellness.test", "wk_seed_healthcare"),
]
_PASSWORD = "password123"
_SEED_DOC = "Our return policy allows returns within 30 days of delivery."


async def _seed() -> None:
    settings = get_settings()
    # Use the configured embedder so seeded chunks match the running stack (fake in dev/CI, real
    # when USE_FAKE_EMBEDDINGS=false) — avoids mixing fake + real vector spaces at retrieval time.
    embedder = get_embedder()
    embedder_id = "fake" if settings.use_fake_embeddings else settings.embed_model

    async with SessionLocal() as session:
        async with session.begin():
            tenants = [Tenant(name=n, industry=ind.value, status="active") for n, ind, _, _ in _TENANTS]
            session.add_all(tenants)
            await session.flush()
            ids = [t.id for t in tenants]

    vector = (await embedder.embed([_SEED_DOC]))[0]
    for (name, industry, email, wk), tenant_id in zip(_TENANTS, ids):
        async with with_tenant(tenant_id) as session:
            session.add(
                Staff(
                    email=email,
                    password_hash=hash_password(_PASSWORD),
                    role="admin",
                    email_verified=True,
                )
            )
            session.add(AgentSettings(config=default_agent_settings(industry)))
            session.add(WidgetKey(key=wk))
            source = Source(kind="paste", name="Return Policy", status="ready", chunk_count=1,
                            bytes=len(_SEED_DOC))
            session.add(source)
            await session.flush()
            session.add(
                KbChunk(
                    source_id=source.id,
                    content=_SEED_DOC,
                    content_hash="seed-return-policy",
                    embedding=vector,
                    embedder_id=embedder_id,
                    dim=settings.embed_dim,
                    language="en",
                )
            )
        print(f"seeded tenant {name} ({industry.value})  id={tenant_id}  widget_key={wk}  admin={email}")

    print(f"\nDone. Login with any admin above / password '{_PASSWORD}'.")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
