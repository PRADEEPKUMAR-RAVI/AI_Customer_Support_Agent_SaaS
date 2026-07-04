"""M1 admin-surface DTOs (agent_settings read/patch, widget-key rotate, embed snippet)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AllowedDomainRequest(BaseModel):
    # A host suffix the widget's Origin is checked against (e.g. "example.com" or
    # "app.example.com"). Best-effort browser control, not the security boundary.
    domain: str = Field(min_length=1, max_length=255)


class AllowedDomainResponse(BaseModel):
    id: str
    domain: str


class AgentSettingsResponse(BaseModel):
    """The tenant's ``agent_settings.config`` blob, as-is. Kept as a passthrough dict (rather
    than a fully-typed model) because the config shape is still growing across phases and every
    field already has a documented default in
    ``domain.tenancy.defaults.default_agent_settings``."""

    config: dict


class AgentSettingsPatchRequest(BaseModel):
    """Shallow-merged into the existing config — callers send only the keys they're changing."""

    config: dict


class WidgetKeyResponse(BaseModel):
    widget_key: str


class EmbedSnippetResponse(BaseModel):
    widget_key: str
    snippet: str


class TenantResponse(BaseModel):
    """Enough for the FE onboarding wizard to know which industry (-> record types/templates)
    it's working with — nothing here is sensitive to any staff role."""

    name: str
    industry: str
    status: str
