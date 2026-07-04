"""Identity-verification semantics (§4.8.2) + record-schema registry integrity (CI gate)."""

from __future__ import annotations

from app.domain.records.schemas import (
    INDUSTRY_SCHEMAS,
    Industry,
    get_schema,
    matches_key,
    max_verify_attempts,
    verify_record,
)


def test_email_verify_is_casefold_and_trimmed():
    schema = get_schema(Industry.RETAIL, "order")
    record = {"email": "Alice@Example.com", "status": "shipped"}
    assert verify_record(schema, "  alice@example.COM ", record) is True
    assert verify_record(schema, "bob@example.com", record) is False


def test_phone_verify_is_digits_only():
    # §4.8.2: phone = strip non-digits then EXACT match (no country-code normalisation).
    schema = get_schema(Industry.LOGISTICS, "shipment")
    record = {"phone": "(555) 123-4567", "status": "in_transit"}
    assert verify_record(schema, "5551234567", record) is True
    assert verify_record(schema, "555-123-4567", record) is True
    assert verify_record(schema, "5559999999", record) is False
    # A differing country code is a different digit string -> no match (documented POC limit).
    assert verify_record(schema, "15551234567", record) is False


def test_shipment_accepts_phone_or_email():
    schema = get_schema(Industry.LOGISTICS, "shipment")
    record = {"phone": "5551234567", "email": "x@y.com"}
    assert verify_record(schema, "x@y.com", record) is True   # email option
    assert verify_record(schema, "5551234567", record) is True  # phone option


def test_dob_is_exact():
    schema = get_schema(Industry.HEALTHCARE, "appointment")
    record = {"dob": "1990-01-15", "provider": "Dr. Lee"}
    assert verify_record(schema, "1990-01-15", record) is True
    assert verify_record(schema, "1990-1-15", record) is False


def test_warranty_alias_key_resolves_both():
    schema = get_schema(Industry.RETAIL, "warranty")
    assert schema.key_field == "serial_no"
    assert "order_id" in schema.alias_keys
    record = {"serial_no": "SN-1", "order_id": "ORD-9", "coverage": "active"}
    assert matches_key(schema, "SN-1", record) is True
    assert matches_key(schema, "ORD-9", record) is True   # alias
    assert matches_key(schema, "NOPE", record) is False


def test_healthcare_gets_one_attempt_others_three():
    assert max_verify_attempts(Industry.HEALTHCARE) == 1
    assert max_verify_attempts(Industry.RETAIL) == 3


def test_registry_matches_prd_table():
    assert set(INDUSTRY_SCHEMAS[Industry.RETAIL]) == {"order", "warranty"}  # [C1]
    assert INDUSTRY_SCHEMAS[Industry.RETAIL]["order"].enums["status"] == (
        "placed", "processing", "shipped", "delivered", "cancelled",
    )
    assert INDUSTRY_SCHEMAS[Industry.RETAIL]["warranty"].enums["coverage"] == (
        "active", "expired", "void",
    )
