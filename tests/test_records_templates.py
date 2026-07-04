"""M1 ``GET /records/templates/{record_type}`` — rendered from Person-2's frozen schema
registry (`app/domain/records/schemas.py`), not a parallel copy."""

from __future__ import annotations

import csv
import io

import pytest

from tests.helpers import auth_headers, client, signup_verified_admin

pytestmark = pytest.mark.rls


async def test_json_template_for_retail_order():
    _, _, _, admin_token = await signup_verified_admin(industry="retail")
    async with client() as c:
        res = await c.get(
            "/api/v1/records/templates/order", params={"format": "json"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["key_field"] == "order_id"
        assert "email" in body["verify_fields"]
        assert set(body["returned_fields"]) == {"status", "eta", "tracking_ref"}


async def test_csv_template_for_retail_warranty_includes_alias_key():
    _, _, _, admin_token = await signup_verified_admin(industry="retail")
    async with client() as c:
        res = await c.get(
            "/api/v1/records/templates/warranty", params={"format": "csv"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/csv")
        header = next(csv.reader(io.StringIO(res.text)))
        assert "serial_no" in header
        assert "order_id" in header  # [C2] alias key


async def test_unknown_record_type_for_this_tenants_industry_404s():
    _, _, _, admin_token = await signup_verified_admin(industry="retail")
    async with client() as c:
        # `shipment` is a Logistics record type, not Retail — must 404, not silently 500/leak.
        res = await c.get(
            "/api/v1/records/templates/shipment", params={"format": "json"},
            headers=auth_headers(admin_token),
        )
        assert res.status_code == 404
