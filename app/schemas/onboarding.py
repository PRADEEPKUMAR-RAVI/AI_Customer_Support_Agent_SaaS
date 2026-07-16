"""Onboarding-status DTO — see `app/api/v1/onboarding.py` for how `completed` is derived."""

from __future__ import annotations

from pydantic import BaseModel


class OnboardingStatusResponse(BaseModel):
    completed: bool
