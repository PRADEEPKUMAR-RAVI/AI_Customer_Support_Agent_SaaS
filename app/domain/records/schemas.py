"""The 5 industry record templates + identity-verification semantics (PRD §4.8, §4.8.2).

Frozen registry (audit [C1][C2][A7][A8]): M1 template downloads, M4 upload validation, and
M2's verify-in-code all import from here — one source of truth. A tenant belongs to exactly
one industry for the POC.

Identity verification is enforced in **code** here (never the model, never the resolver):
``verify_record`` implements the exact comparison rules from §4.8.2.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

from app.core.config import TenantDefaults


class Industry(str, enum.Enum):
    RETAIL = "retail"
    LOGISTICS = "logistics"
    TELECOM = "telecom"
    HEALTHCARE = "healthcare"
    TRAVEL = "travel"


class MatchRule(str, enum.Enum):
    EMAIL_CASEFOLD = "email_casefold"   # trim + casefold, exact
    PHONE_DIGITS = "phone_digits"       # strip all non-digits, exact
    NAME_CASEFOLD = "name_casefold"     # trim + casefold, exact
    DOB_EXACT = "dob_exact"             # exact string match


@dataclass(frozen=True)
class VerifyOption:
    """One acceptable verify field for a record type (§4.8: e.g. 'phone or email')."""

    field: str
    rule: MatchRule


@dataclass(frozen=True)
class RecordSchema:
    record_type: str
    key_field: str
    verify: tuple[VerifyOption, ...]
    returned_fields: tuple[str, ...]
    alias_keys: tuple[str, ...] = ()        # [C2] warranty accepts order_id as an alias key
    optional_fields: tuple[str, ...] = ()   # [A9] e.g. order.tracking_url
    enums: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def all_key_fields(self) -> tuple[str, ...]:
        return (self.key_field, *self.alias_keys)


# --- the five templates (exact PRD §4.8 table) --------------------------------------------

_RETAIL_ORDER = RecordSchema(
    record_type="order",
    key_field="order_id",
    verify=(VerifyOption("email", MatchRule.EMAIL_CASEFOLD),),
    returned_fields=("status", "eta", "tracking_ref"),
    optional_fields=("tracking_url",),  # [A9]
    enums={"status": ("placed", "processing", "shipped", "delivered", "cancelled")},  # [A8]
)
_RETAIL_WARRANTY = RecordSchema(
    record_type="warranty",
    key_field="serial_no",
    alias_keys=("order_id",),  # [C2] either resolves the same warranty
    verify=(VerifyOption("email", MatchRule.EMAIL_CASEFOLD),),
    returned_fields=("coverage", "expiry"),
    enums={"coverage": ("active", "expired", "void")},  # [A8]; void -> deterministic dispute [A1]
)
_LOGISTICS_SHIPMENT = RecordSchema(
    record_type="shipment",
    key_field="tracking_no",
    verify=(
        VerifyOption("phone", MatchRule.PHONE_DIGITS),
        VerifyOption("email", MatchRule.EMAIL_CASEFOLD),
    ),
    returned_fields=("current_location", "status", "eta"),
)
_TELECOM_SUBSCRIPTION = RecordSchema(
    record_type="subscription",
    key_field="account_id",
    verify=(VerifyOption("registered_mobile", MatchRule.PHONE_DIGITS),),
    returned_fields=("plan", "renewal_date", "balance_due"),
)
_TELECOM_BILLING = RecordSchema(
    record_type="billing",
    key_field="account_id",
    verify=(VerifyOption("registered_mobile", MatchRule.PHONE_DIGITS),),
    returned_fields=("plan", "renewal_date", "balance_due"),
)
_HEALTHCARE_APPOINTMENT = RecordSchema(
    record_type="appointment",
    key_field="booking_ref",
    verify=(
        VerifyOption("phone", MatchRule.PHONE_DIGITS),
        VerifyOption("dob", MatchRule.DOB_EXACT),
    ),
    returned_fields=("date_time", "provider", "prep_instructions"),
)
_TRAVEL_BOOKING = RecordSchema(
    record_type="booking",
    key_field="booking_ref",
    verify=(
        VerifyOption("email", MatchRule.EMAIL_CASEFOLD),
        VerifyOption("last_name", MatchRule.NAME_CASEFOLD),
    ),
    returned_fields=("status", "dates", "itinerary"),
)

INDUSTRY_SCHEMAS: dict[Industry, dict[str, RecordSchema]] = {
    Industry.RETAIL: {"order": _RETAIL_ORDER, "warranty": _RETAIL_WARRANTY},
    Industry.LOGISTICS: {"shipment": _LOGISTICS_SHIPMENT},
    Industry.TELECOM: {"subscription": _TELECOM_SUBSCRIPTION, "billing": _TELECOM_BILLING},
    Industry.HEALTHCARE: {"appointment": _HEALTHCARE_APPOINTMENT},
    Industry.TRAVEL: {"booking": _TRAVEL_BOOKING},
}


def record_types_for(industry: Industry) -> tuple[str, ...]:
    return tuple(INDUSTRY_SCHEMAS[industry].keys())


def get_schema(industry: Industry, record_type: str) -> RecordSchema | None:
    return INDUSTRY_SCHEMAS.get(industry, {}).get(record_type)


def max_verify_attempts(industry: Industry) -> int:
    """Healthcare = 1 (no retry); everyone else = 3 (§4.8.2)."""
    if industry is Industry.HEALTHCARE:
        return TenantDefaults.VERIFY_MAX_ATTEMPTS_HEALTHCARE
    return TenantDefaults.VERIFY_MAX_ATTEMPTS


# --- verification comparison (§4.8.2) — enforced in code -----------------------------------

_NON_DIGITS = re.compile(r"\D+")


def _matches(rule: MatchRule, provided: str, actual: str) -> bool:
    if provided is None or actual is None:
        return False
    if rule in (MatchRule.EMAIL_CASEFOLD, MatchRule.NAME_CASEFOLD):
        return provided.strip().casefold() == actual.strip().casefold()
    if rule is MatchRule.PHONE_DIGITS:
        return _NON_DIGITS.sub("", provided) == _NON_DIGITS.sub("", actual)
    if rule is MatchRule.DOB_EXACT:
        return provided.strip() == actual.strip()
    return False  # unknown rule -> fail closed


def verify_record(schema: RecordSchema, provided_value: str, record: dict) -> bool:
    """True iff ``provided_value`` matches the record's verify field under its rule.

    Accepts any of the schema's verify options (e.g. phone OR email). The comparison runs
    here in engine code — the model and the connector never decide "verified".
    """
    for opt in schema.verify:
        actual = record.get(opt.field)
        if actual is not None and _matches(opt.rule, str(provided_value), str(actual)):
            return True
    return False


def matches_key(schema: RecordSchema, requested_key: str, record: dict) -> bool:
    """True iff ``requested_key`` resolves this record via its primary or an alias key [C2]."""
    for kf in schema.all_key_fields:
        val = record.get(kf)
        if val is not None and str(val).strip() == str(requested_key).strip():
            return True
    return False
