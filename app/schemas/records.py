"""The ``lookup_record`` tool contract (PRD §4.8.1) + the resolver seam types (§4.9).

The tool response status enum is the customer-facing contract; ``not_found`` and
``unverified`` deliberately map to the SAME customer message so keys can't be enumerated.
"""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class LookupStatus(str, enum.Enum):
    OK = "ok"
    NOT_FOUND = "not_found"        # key absent
    UNVERIFIED = "unverified"      # key exists but verify value mismatched
    INVALID_TYPE = "invalid_type"  # record_type not valid for this tenant
    RATE_LIMITED = "rate_limited"  # durable verify-attempt cap hit (§6, [IMP-SEC-6])


class VerifyInput(BaseModel):
    field: str
    value: str


class LookupRecordRequest(BaseModel):
    record_type: str
    key: str
    verify: VerifyInput


class LookupRecordResponse(BaseModel):
    status: LookupStatus
    # Present only on OK; contains ONLY the schema's returned fields (never the verify value).
    record: dict | None = None


# --- M4 admin API DTOs --------------------------------------------------------------------

class DatasetOut(BaseModel):
    record_type: str
    row_count: int
    updated_at: datetime


class RowErrorOut(BaseModel):
    row: int
    error: str


class DatasetUploadReport(BaseModel):
    """Backend is the single source of validation truth; the FE renders this verbatim."""

    ok: bool
    record_type: str
    inserted: int = 0
    truncated: int = 0
    missing_headers: list[str] = Field(default_factory=list)
    duplicate_keys: list[str] = Field(default_factory=list)
    row_errors: list[RowErrorOut] = Field(default_factory=list)


class RecordSchemaOut(BaseModel):
    """Resolved schema for the FE field-map / validation UI ([IMP-FE-8])."""

    record_type: str
    key: str
    alias_keys: list[str] = Field(default_factory=list)
    verify_fields: list[str] = Field(default_factory=list)
    returned_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)


class ConnectorIn(BaseModel):
    record_type: str
    source_type: str  # "db" | "api"
    # The ONE secret for this source: DB password/DSN, API-key value, Bearer token, Basic password,
    # or OAuth client_secret. Encrypted at rest. Empty for a no-auth API. Non-secret auth partners
    # (username, client_id, key name/location) and dialect/path/method live in ``config``.
    credentials: str = ""
    config: dict = Field(default_factory=dict)  # db: {dialect, host, port, database, query_template}
    #                                             api: {base_url, method, path_template, auth, response_path}
    field_map: dict[str, str] = Field(default_factory=dict)  # {source_field: schema_field}


class ConnectorOut(BaseModel):
    id: str
    record_type: str
    source_type: str
    version: int
    enabled: bool = True  # at most one enabled per (tenant, record_type); rest are paused
    # Additive, never-secret fields for the management UI (safe defaults keep the upsert call valid).
    has_credentials: bool = False
    config_summary: dict = Field(default_factory=dict)  # masked config (secrets never live here)
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_error: str | None = None
    updated_at: datetime | None = None


class ConnectorListItem(BaseModel):
    """One row of the connector management screen (no secrets)."""

    id: str
    record_type: str
    source_type: str  # "db" | "api"
    summary: str  # human display, e.g. "PostgreSQL · db.example.com:5432/production"
    version: int
    enabled: bool = True  # the one active source for its record_type (others paused)
    has_credentials: bool = False
    last_tested_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_error: str | None = None
    updated_at: datetime | None = None


class ConnectorDetail(ConnectorListItem):
    """List row + the masked config / field map for the edit form."""

    config: dict = Field(default_factory=dict)  # masked — secrets live only in encrypted_credentials
    field_map: dict[str, str] = Field(default_factory=dict)


class ConnectorTestIn(BaseModel):
    test_key: str = Field(min_length=1)


class ConnectorValidateIn(BaseModel):
    """Test-before-save: run one lookup against unsaved connector config without persisting."""

    record_type: str
    source_type: str
    credentials: str = ""
    config: dict = Field(default_factory=dict)
    field_map: dict[str, str] = Field(default_factory=dict)
    test_key: str = Field(min_length=1)


class ConnectorPatchIn(BaseModel):
    """Partial edit / secret rotation. ``None`` leaves a field unchanged; ``credentials=""`` clears
    the stored secret. Any change bumps ``version`` (invalidates the engine + OAuth token caches).
    ``enabled=True`` activates this connector and pauses its siblings for the same record_type;
    ``enabled=False`` pauses it (the record_type then falls back to its uploaded dataset)."""

    config: dict | None = None
    field_map: dict[str, str] | None = None
    credentials: str | None = None
    enabled: bool | None = None


class ConnectorTestReport(BaseModel):
    ok: bool
    found: bool = False
    has_verify_field: bool = False
    error: str | None = None


class LiveRecordResponse(BaseModel):
    """Agent-workspace live re-fetch (Phase 3). ``available=False`` = connector unavailable
    (retry); ``available=True, record=None`` = the record no longer exists."""

    available: bool
    record: dict | None = None
