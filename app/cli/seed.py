"""Seed CLI — ≥2 tenants across ≥2 industries so the stack is demoable offline and the RLS
leak test has real cross-tenant data ([IMP-DEL-4]).

Idempotent: re-running skips tenants already seeded (keyed on the globally-unique widget_key,
which has a public SELECT policy so it is readable without a tenant context). Each tenant is
created together with its rows in ONE transaction, so a mid-way failure never leaves an orphan
tenant behind.

Admin emails use a normal TLD (not the reserved ``.test``): the login/signup DTOs validate
``email`` as an ``EmailStr``, which rejects RFC-6761 special-use TLDs, so ``admin@acme.test``
could never actually log in. Seeded admins are the documented "admin logs into the seeded
tenant" checkpoint, so they must be loginable.

Tenant-scoped rows auto-fill ``tenant_id`` from the GUC (set via ``set_tenant_guc``) and satisfy
RLS ``WITH CHECK``. (M4 record datasets with deliberately colliding keys like ``order_id=1001``
across tenants are added when P2 builds M4 — noted, not silently skipped.)
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.domain.records.schemas import Industry
from app.domain.tenancy.defaults import default_agent_settings
from app.infra.db.engine import SessionLocal
from app.infra.db.models.knowledge import KbChunk, Source
from app.infra.db.models.tenant import AgentSettings, Staff, Tenant, WidgetKey
from app.infra.db.session import set_tenant_guc
from app.infra.embeddings.fake import FakeEmbedder

_TENANTS = [
    ("Acme Retail", Industry.RETAIL, "admin@acme-retail.com", "wk_seed_retail"),
    ("Wellness Clinic", Industry.HEALTHCARE, "admin@wellness-clinic.com", "wk_seed_healthcare"),
]
_PASSWORD = "password123"
_SEED_DOC = "Our return policy allows returns within 30 days of delivery."


async def _seed() -> None:
    settings = get_settings()
    embedder = FakeEmbedder(dim=settings.embed_dim)
    vector = (await embedder.embed([_SEED_DOC]))[0]

    # Idempotency: skip tenants whose widget_key already exists. widget_key has a public SELECT
    # policy (widget_key_public_read), so existing keys are readable without a tenant context —
    # re-running the seed must not create orphan duplicate tenants.
    async with SessionLocal() as session:
        existing = set((await session.execute(select(WidgetKey.key))).scalars().all())
    todo = [t for t in _TENANTS if t[3] not in existing]
    if not todo:
        print("Seed already applied (all widget keys present); nothing to do.")
        return

    for name, industry, email, wk in todo:
        # One transaction per tenant: create the tenant, set the GUC, insert its rows together,
        # so a failure rolls back the tenant too and never leaves an orphan. Mirrors the signup
        # flow in app/api/v1/auth.py.
        async with SessionLocal() as session:
            async with session.begin():
                tenant = Tenant(name=name, industry=industry.value, status="active")
                session.add(tenant)
                await session.flush()  # obtain tenant.id
                await set_tenant_guc(session, tenant.id)  # subsequent inserts auto-scope
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
                await session.flush()  # obtain source.id
                session.add(
                    KbChunk(
                        source_id=source.id,
                        content=_SEED_DOC,
                        content_hash="seed-return-policy",
                        embedding=vector,
                        embedder_id="fake",
                        dim=settings.embed_dim,
                        language="en",
                    )
                )
                tenant_id = tenant.id
        print(f"seeded tenant {name} ({industry.value})  id={tenant_id}  widget_key={wk}  admin={email}")

    print(f"\nDone. Login with any admin above / password '{_PASSWORD}'.")


def main() -> None:
    asyncio.run(_seed())


if __name__ == "__main__":
    main()
