"""multi-connector per record_type — `enabled` flag + one-active-per-type partial unique index.

Many connectors may now back a single (tenant, record_type); a partial unique index guarantees at
most one is ENABLED at a time (the single source of truth the engine grounds/verifies against).
Replaces the old ``uq_connector_tenant_type`` "one connector per type" constraint. When every
connector for a record_type is disabled, that record_type falls back to its uploaded dataset.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (IF (NOT) EXISTS): on a FRESH DB, 0004's Base.metadata.create_all already builds
    # `connector` from the current model (the `enabled` column + the partial index, and no unique
    # constraint), so these no-op there; on a DB migrated before this change they genuinely apply.
    # No RLS change — `tenant_id` is in the index key, so uniqueness is per-tenant even though a
    # unique index is enforced regardless of RLS.
    op.execute("ALTER TABLE connector ADD COLUMN IF NOT EXISTS enabled boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE connector DROP CONSTRAINT IF EXISTS uq_connector_tenant_type")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_connector_active_per_type "
        "ON connector (tenant_id, record_type) WHERE enabled"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_connector_active_per_type")
    op.execute("ALTER TABLE connector DROP COLUMN IF EXISTS enabled")
    # Deliberately does NOT restore uq_connector_tenant_type: by now multiple connectors may share a
    # record_type, which would make re-adding the "one per type" constraint fail.
