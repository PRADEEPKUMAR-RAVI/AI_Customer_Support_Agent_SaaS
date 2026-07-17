"""Onboarding-status API — no stored "onboarding done" flag. Completion is derived from the same
resource state `frontend/src/features/onboarding/OnboardingPage.tsx` already checks per-step, so
the FE console guard (force new tenants through /onboarding until this is true) and the wizard's
own step checklist can never drift apart.

Required-to-unlock steps: industry, knowledge source, customer-record dataset, agent config
(persona or welcome message), and an allowed domain. Industry used to be set at signup (always
true), but is now chosen in onboarding step 1, so it's checked here like everything else;
inviting a teammate stays optional (solo admins shouldn't be blocked on it).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_staff, get_db
from app.infra.db.models.knowledge import Source
from app.infra.db.models.records import RecordDataset
from app.infra.db.models.tenant import AgentSettings, AllowedDomain, Tenant
from app.schemas.auth import StaffContext
from app.schemas.onboarding import OnboardingStatusResponse

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.get("/status", response_model=OnboardingStatusResponse)
async def get_onboarding_status(
    session: AsyncSession = Depends(get_db),
    staff: StaffContext = Depends(get_current_staff),
) -> OnboardingStatusResponse:
    tenant_industry = (
        await session.execute(select(Tenant.industry).where(Tenant.id == uuid.UUID(staff.tenant_id)))
    ).scalar_one_or_none()
    has_industry = tenant_industry is not None
    has_source = (await session.execute(select(Source.id).limit(1))).first() is not None
    has_dataset = (await session.execute(select(RecordDataset.id).limit(1))).first() is not None
    has_domain = (await session.execute(select(AllowedDomain.id).limit(1))).first() is not None
    settings_row = (await session.execute(select(AgentSettings))).scalar_one_or_none()
    cfg = settings_row.config if settings_row is not None else {}
    has_config = bool(cfg.get("persona") or cfg.get("welcome_message"))
    completed = has_industry and has_source and has_dataset and has_domain and has_config
    return OnboardingStatusResponse(completed=completed)
