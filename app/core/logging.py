"""Structured logging + a redaction filter (audit [IMP-SEC-7]).

Non-negotiable: logs/traces never carry raw message bodies, verify values (DOB/phone/email/
last_name), record-field contents, or bound connector params — only IDs and hashes. This
filter masks known-sensitive ``key=value`` / ``key: value`` pairs and bare emails as a
backstop; callers should still log IDs, not payloads.
"""

from __future__ import annotations

import logging
import re

from app.core.config import get_settings

# Matches a sensitive key followed by = or : and a value; captures the key so we keep it.
_SENSITIVE_KV = re.compile(
    r"(?i)\b(password|passwd|secret|token|authorization|api[_-]?key|credential|"
    r"email|phone|dob|last_name|verify|content|message_body)\b(\s*[=:]\s*)(\S+)"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _mask_kv(m: re.Match) -> str:
    key, sep, _value = m.group(1), m.group(2), m.group(3)
    return f"{key}{sep}***"


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        redacted = _SENSITIVE_KV.sub(_mask_kv, msg)
        redacted = _EMAIL.sub("***@***", redacted)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging() -> None:
    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactionFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
