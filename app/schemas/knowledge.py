"""M3 knowledge API DTOs (request/response). Constructed explicitly from ORM rows."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class SourceKind(str, enum.Enum):
    FILE = "file"
    PASTE = "paste"
    URL = "url"  # Phase 2


class SourceStatus(str, enum.Enum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class PasteSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)


class UrlSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    id: str
    kind: str
    name: str
    status: str
    error: str | None = None
    chunk_count: int
    bytes: int
    source_url: str | None = None
    created_at: datetime
