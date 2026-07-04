"""The ``lookup_record`` tool contract (PRD §4.8.1) + the resolver seam types (§4.9).

The tool response status enum is the customer-facing contract; ``not_found`` and
``unverified`` deliberately map to the SAME customer message so keys can't be enumerated.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel


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
