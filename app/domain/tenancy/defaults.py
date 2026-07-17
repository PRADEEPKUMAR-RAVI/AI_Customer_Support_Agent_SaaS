"""Default ``agent_settings.config`` for a newly-onboarded tenant (§5.1 settings list).

Seeded from ``TenantDefaults`` (§11) at signup; the admin edits these afterwards. Every
customer-visible / behavioural knob the PRD lists lives here so nothing is hard-coded.
"""

from __future__ import annotations

from app.core.config import TenantDefaults as D
from app.domain.escalation.reasons import EscalationReason
from app.domain.records.schemas import Industry, max_verify_attempts


def default_agent_settings(industry: Industry | None) -> dict:
    """`industry` may be `None` at signup time now — it's chosen in onboarding step 1, not at
    signup — so every industry-dependent default here must tolerate that (only
    `verify_max_attempts` actually varies by industry, and `max_verify_attempts(None)` already
    falls through to the non-healthcare default)."""
    return {
        "persona": "A helpful, concise customer-support assistant.",
        "welcome_message": "Hi! How can I help you today?",  # [A6]
        "supported_languages": ["en", "es", "fr", "de", "hi"],  # English + 4 (§7)
        "default_language": "en",
        "active_triggers": [r.value for r in EscalationReason],
        "sensitive_intent_list": ["refund dispute", "complaint", "legal", "cancellation"],
        "relevance_threshold": D.RELEVANCE_THRESHOLD,  # eval-derived; None until calibrated
        "verify_max_attempts": max_verify_attempts(industry),  # healthcare = 1
        "resolve_after_idle_seconds": D.RESOLVE_AFTER_IDLE_SECONDS,
        "close_after_idle_seconds": D.CLOSE_AFTER_IDLE_SECONDS,
        "reopen_window_seconds": D.REOPEN_WINDOW_SECONDS,
        "session_id_ttl_seconds": D.SESSION_ID_TTL_SECONDS,
        "per_turn_timeout_seconds": D.PER_TURN_TIMEOUT_SECONDS,
        "max_tool_calls_per_turn": D.MAX_TOOL_CALLS_PER_TURN,
        "stall_retries": D.STALL_RETRIES,
        "escalate_on_timeout": D.ESCALATE_ON_TIMEOUT,
        "sla_followup_text": D.SLA_FOLLOWUP_TEXT,
        "carrier_url_template": None,  # [A9] optional
        "support_notification_email": None,  # [A15] where after-hours escalations notify
        "allowed_tags": [
            "order_status",
            "warranty_claim",
            "appointment_change",
            "billing",
            "complaint",
        ],
        "autonomy_enabled": D.AUTONOMY_ENABLED,
        "contextual_augmentation_enabled": D.CONTEXTUAL_AUGMENTATION_ENABLED,  # [T1] off
        "kb_total_bytes_limit": D.KB_TOTAL_BYTES_LIMIT,  # [A12]
    }
