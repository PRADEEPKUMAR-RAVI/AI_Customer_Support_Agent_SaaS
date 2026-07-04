"""M4 Records core — upload validation (unit) + lookup_record engine assembler (rls integration).

Proves the identity-verify seam: resolvers fetch, the engine verifies; `not_found`/`unverified`
are neutral; the durable counter locks out per (tenant, record_type, key); alias keys resolve;
retrieval is tenant-isolated.
"""

from __future__ import annotations

import pytest

from app.core import ratelimit
from app.domain.records.schemas import Industry, get_schema
from app.infra.db.session import with_tenant
from app.schemas.records import LookupStatus
from app.services.record_service import lookup_record, replace_dataset, validate_dataset
from tests.fixtures.kb_eval import make_tenant

# ---------------------------------------------------------------------------------------------
# Pure unit tests (no DB) — run under `make test`
# ---------------------------------------------------------------------------------------------

_ORDER = get_schema(Industry.RETAIL, "order")


def test_validate_csv_ok():
    csv = b"order_id,email,status,eta,tracking_ref\n1001,a@x.test,shipped,2026-07-10,TRK1\n"
    rows, report = validate_dataset(_ORDER, "order", csv, content_type="text/csv", filename="o.csv")
    assert report.ok and report.inserted == 1
    assert rows[0]["key"] == "1001"
    assert rows[0]["data"]["email"] == "a@x.test"


def test_validate_missing_headers():
    csv = b"order_id,status\n1001,shipped\n"  # no email (verify) and no eta/tracking_ref
    rows, report = validate_dataset(_ORDER, "order", csv, content_type="text/csv", filename="o.csv")
    assert not report.ok and not rows
    assert any("eta" in h for h in report.missing_headers)
    assert any("verify field" in h for h in report.missing_headers)


def test_validate_duplicate_keys_fail():
    csv = b"order_id,email,status,eta,tracking_ref\n1001,a@x.test,shipped,d,t\n1001,b@x.test,placed,d,t\n"
    rows, report = validate_dataset(_ORDER, "order", csv, content_type="text/csv", filename="o.csv")
    assert not report.ok and not rows
    assert report.duplicate_keys == ["1001"]


def test_validate_json_list():
    js = b'[{"order_id":"1001","email":"a@x.test","status":"shipped","eta":"d","tracking_ref":"t"}]'
    rows, report = validate_dataset(_ORDER, "order", js, content_type="application/json", filename="o.json")
    assert report.ok and rows[0]["key"] == "1001"


# ---------------------------------------------------------------------------------------------
# Integration (rls) — live Postgres + Redis
# ---------------------------------------------------------------------------------------------

pytestmark_rls = pytest.mark.rls


@pytest.fixture(autouse=True)
async def _dispose_engine_between_tests():
    # Both the async DB engine and the cached async Redis client bind to the loop they're created
    # on; pytest-asyncio gives each test a fresh loop, so reset both around every test.
    from app.infra.cache.redis import get_redis
    from app.infra.db.engine import engine

    await engine.dispose()
    get_redis.cache_clear()  # next get_redis() builds a client on THIS test's loop
    yield
    await engine.dispose()
    try:
        await get_redis().aclose()
    except Exception:  # noqa: BLE001 — best-effort teardown
        pass
    get_redis.cache_clear()


async def _seed(tenant_id, record_type, rows):
    async with with_tenant(tenant_id) as session:
        await replace_dataset(session, record_type=record_type, rows=rows)


def _order_row(order_id, email, status="shipped"):
    return {"key": order_id, "data": {"order_id": order_id, "email": email, "status": status,
                                      "eta": "2026-07-10", "tracking_ref": "TRK-" + order_id}}


@pytest.mark.rls
async def test_lookup_ok_returns_only_returned_fields():
    t = await make_tenant("m4-ok", industry="retail")
    await _seed(t, "order", [_order_row("1001", "alice@x.test")])
    async with with_tenant(t) as s:
        r = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="order",
                                key="1001", verify_value="ALICE@x.test")  # casefold match
        assert r.status == LookupStatus.OK
        assert r.record == {"status": "shipped", "eta": "2026-07-10", "tracking_ref": "TRK-1001"}
        assert "email" not in r.record  # verify value never disclosed


@pytest.mark.rls
async def test_not_found_and_unverified_are_neutral():
    t = await make_tenant("m4-neutral", industry="retail")
    await _seed(t, "order", [_order_row("1001", "alice@x.test")])
    async with with_tenant(t) as s:
        nf = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="order",
                                 key="9999", verify_value="alice@x.test")
        uv = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="order",
                                 key="1001", verify_value="wrong@x.test")
        assert nf.status == LookupStatus.NOT_FOUND
        assert uv.status == LookupStatus.UNVERIFIED
        assert nf.record is None and uv.record is None  # same shape to the customer


@pytest.mark.rls
async def test_invalid_record_type():
    t = await make_tenant("m4-invalid", industry="retail")
    async with with_tenant(t) as s:
        r = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="booking",
                                key="x", verify_value="y")  # booking is travel, not retail
        assert r.status == LookupStatus.INVALID_TYPE


@pytest.mark.rls
async def test_alias_key_resolves_warranty_by_order_id():
    t = await make_tenant("m4-alias", industry="retail")
    await _seed(t, "warranty", [{"key": "SN-1", "data": {"serial_no": "SN-1", "order_id": "1001",
                                                          "email": "a@x.test", "coverage": "active",
                                                          "expiry": "2027-01-01"}}])
    async with with_tenant(t) as s:
        r = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="warranty",
                                key="1001", verify_value="a@x.test")  # order_id alias, not serial
        assert r.status == LookupStatus.OK
        assert r.record["coverage"] == "active"


@pytest.mark.rls
async def test_retail_rate_limits_after_three_failed_verifies():
    t = await make_tenant("m4-rl", industry="retail")
    await _seed(t, "order", [_order_row("1001", "alice@x.test")])
    async with with_tenant(t) as s:
        for _ in range(3):
            r = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="order",
                                    key="1001", verify_value="bad@x.test")
            assert r.status == LookupStatus.UNVERIFIED
        locked = await lookup_record(s, tenant_id=t, industry=Industry.RETAIL, record_type="order",
                                     key="1001", verify_value="alice@x.test")  # even correct now blocked
        assert locked.status == LookupStatus.RATE_LIMITED
    await ratelimit.reset(f"verify:{t}:order:1001")  # cleanup


@pytest.mark.rls
async def test_healthcare_locks_after_one_failed_verify():
    t = await make_tenant("m4-hc", industry="healthcare")
    await _seed(t, "appointment", [{"key": "BK-1", "data": {"booking_ref": "BK-1", "phone": "5551234567",
                                                            "date_time": "2026-07-08", "provider": "Dr Lee",
                                                            "prep_instructions": "fast 8h"}}])
    async with with_tenant(t) as s:
        r1 = await lookup_record(s, tenant_id=t, industry=Industry.HEALTHCARE, record_type="appointment",
                                 key="BK-1", verify_value="0000000000")
        assert r1.status == LookupStatus.UNVERIFIED  # first failure
        r2 = await lookup_record(s, tenant_id=t, industry=Industry.HEALTHCARE, record_type="appointment",
                                 key="BK-1", verify_value="5551234567")  # correct, but N=1 already spent
        assert r2.status == LookupStatus.RATE_LIMITED
    await ratelimit.reset(f"verify:{t}:appointment:BK-1")


@pytest.mark.rls
async def test_colliding_key_is_tenant_isolated():
    a = await make_tenant("m4-iso-a", industry="retail")
    b = await make_tenant("m4-iso-b", industry="retail")
    await _seed(a, "order", [_order_row("1001", "alice@a.test")])
    await _seed(b, "order", [_order_row("1001", "bob@b.test")])
    async with with_tenant(a) as s:
        # A's own email verifies against A's row (not B's).
        ok = await lookup_record(s, tenant_id=a, industry=Industry.RETAIL, record_type="order",
                                 key="1001", verify_value="alice@a.test")
        assert ok.status == LookupStatus.OK
        # B's email must NOT verify under A (RLS scopes to A's colliding row).
        cross = await lookup_record(s, tenant_id=a, industry=Industry.RETAIL, record_type="order",
                                    key="1001", verify_value="bob@b.test")
        assert cross.status == LookupStatus.UNVERIFIED
