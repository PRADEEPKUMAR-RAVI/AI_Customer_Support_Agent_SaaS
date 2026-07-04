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
    credentials: str = Field(min_length=1)  # DSN (db) or auth secret (api); encrypted at rest
    config: dict = Field(default_factory=dict)  # db: {query_template}; api: {base_url, path_template,...}
    field_map: dict[str, str] = Field(default_factory=dict)  # {source_field: schema_field}


class ConnectorOut(BaseModel):
    id: str
    record_type: str
    source_type: str
    version: int


class ConnectorTestIn(BaseModel):
    test_key: str = Field(min_length=1)


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
