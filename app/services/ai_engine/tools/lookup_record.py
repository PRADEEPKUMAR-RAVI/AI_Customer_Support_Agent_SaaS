"""lookup_record tool — the identity-verification-in-code call site (non-negotiable, §4.8.2).

The resolver ONLY fetches (fetch → RawRecord | NOT_FOUND | raise ConnectorError). Verification
and status assembly happen HERE, in engine code — never in the resolver or the model. `not_found`
and `unverified` return the SAME neutral status so keys can't be enumerated; the customer-facing
message for both is identical (chosen by the engine).

Two safety behaviours also live here (post-fetch, code-decided):
  * [IMP-SEC-6] a durable per-(tenant, record_type, key) verify-attempt counter (Redis) locks
    further attempts after the industry cap (healthcare = 1, others = 3); a locked key returns
    ``rate_limited`` — indistinguishable across not_found/unverified so it leaks nothing.
  * [A1] a deterministic record-state ``dispute`` flag (void warranty / delivered-but-not-received
    / cancelled-order refund) the engine turns into a code-driven escalation.
"""

from __future__ import annotations

from app.core import ratelimit
from app.core.config import TenantDefaults
from app.domain.records.schemas import Industry, get_schema, max_verify_attempts, verify_record
from app.infra.connectors.base import NOT_FOUND, ConnectorError
from app.schemas.records import LookupStatus
from app.services.record_service import get_resolver

# Intent phrases for the two intent-coupled disputes ([A1]). The record STATE is authoritative;
# these only qualify which disputed intent the customer is raising. Kept deliberately small.
_NON_RECEIPT = (
    "not received", "didn't arrive", "did not arrive", "never arrived", "never got",
    "hasn't arrived", "has not arrived", "not arrived", "not delivered", "didn't get",
    "where is my order", "where's my order", "no package", "missing",
)
_REFUND = ("refund", "money back", "chargeback", "charge back", "reimburse", "my money", "charged")


def _verify_counter_key(tenant_id: str, record_type: str, key: str) -> str:
    return f"verifyattempt:{tenant_id}:{record_type}:{key}"


def detect_dispute(record_type: str, record: dict, user_text: str) -> str | None:
    """Deterministic record-state dispute reason, or None ([A1]). Pure — no I/O.

    void warranty is a record-state dispute on its own; delivered-but-not-received and
    cancelled-order refund additionally require the customer to be raising that intent.
    """
    text = (user_text or "").lower()
    if record_type == "warranty" and str(record.get("coverage", "")).lower() == "void":
        return "void_warranty"
    if record_type == "order":
        status = str(record.get("status", "")).lower()
        if status == "delivered" and any(k in text for k in _NON_RECEIPT):
            return "delivered_not_received"
        if status == "cancelled" and any(k in text for k in _REFUND):
            return "cancelled_refund"
    return None


async def lookup_record_tool(
    session, args: dict, *, industry: str, tenant_id: str = "", user_text: str = "", resolver=None
) -> dict:
    record_type = (args or {}).get("record_type", "")
    key = (args or {}).get("key", "")
    verify_value = (args or {}).get("verify_value", "")

    try:
        ind = Industry(industry)
    except ValueError:
        return {"status": LookupStatus.INVALID_TYPE.value}
    schema = get_schema(ind, record_type)
    if schema is None:
        return {"status": LookupStatus.INVALID_TYPE.value}

    # [IMP-SEC-6] durable lockout. Only enforced when a real tenant context is present (the pure
    # unit tests pass tenant_id="" and stay Redis-free). not_found and unverified BOTH consume an
    # attempt and BOTH surface `rate_limited` once capped, so the lockout leaks no key existence.
    counter_key = _verify_counter_key(tenant_id, record_type, key) if tenant_id else ""
    max_attempts = max_verify_attempts(ind)
    if counter_key and await ratelimit.current(counter_key) >= max_attempts:
        return {"status": LookupStatus.RATE_LIMITED.value}

    async def _register_failure() -> None:
        if counter_key:
            await ratelimit.hit(counter_key, limit=max_attempts,
                                window_seconds=TenantDefaults.VERIFY_LOCKOUT_SECONDS)

    # Resolver dispatch is M4's (person-2): get_resolver is async + session-scoped and returns the
    # Upload/DB/API resolver for this record_type. The resolver is FETCH-ONLY ([IMP-DEL-3]); the
    # verify assembly below stays here in M2. Tests may inject a fake `resolver=` to stay DB-free.
    resolver = resolver or await get_resolver(session, tenant_id, record_type)
    try:
        raw = await resolver.fetch(str(tenant_id), record_type, str(key))
    except ConnectorError:
        # Normalised tool failure — the engine routes this to fallback/escalation (§4.9/§4.1).
        return {"status": "connector_error"}

    if raw is NOT_FOUND:
        await _register_failure()
        return {"status": LookupStatus.NOT_FOUND.value}

    # Verify in code. not_found and unverified are indistinguishable to the customer.
    if not verify_record(schema, verify_value, raw):
        await _register_failure()
        return {"status": LookupStatus.UNVERIFIED.value}

    # Verified — clear the failure counter so an honest customer isn't punished for earlier typos.
    if counter_key:
        await ratelimit.reset(counter_key)

    # OK — return ONLY the schema's returned fields (never the verify value or extra columns).
    record = {f: raw.get(f) for f in schema.returned_fields if f in raw}
    for opt_field in schema.optional_fields:
        if opt_field in raw:
            record[opt_field] = raw.get(opt_field)
    return {"status": LookupStatus.OK.value, "record": record,
            "dispute": detect_dispute(record_type, record, user_text)}
