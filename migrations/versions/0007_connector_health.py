"""connector on-demand health columns — last_tested_at / last_test_ok / last_test_error.

The connector management UI shows per-connector health (last test result + timestamp). These are
written only by the test/validate endpoints (on-demand), never by the customer read path, so the
live lookup flow is unchanged.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (IF NOT EXISTS): on a FRESH DB, 0004's Base.metadata.create_all already builds
    # connector from the current model (which now includes these columns), so this no-ops there; on
    # a DB migrated before they existed it genuinely adds them. No RLS change — the existing
    # connector tenant_isolation policy (0004) already covers the whole row, new columns included.
    op.execute("ALTER TABLE connector ADD COLUMN IF NOT EXISTS last_tested_at timestamptz")
    op.execute("ALTER TABLE connector ADD COLUMN IF NOT EXISTS last_test_ok boolean")
    op.execute("ALTER TABLE connector ADD COLUMN IF NOT EXISTS last_test_error varchar(300)")


def downgrade() -> None:
    op.execute("ALTER TABLE connector DROP COLUMN IF EXISTS last_test_error")
    op.execute("ALTER TABLE connector DROP COLUMN IF EXISTS last_test_ok")
    op.execute("ALTER TABLE connector DROP COLUMN IF EXISTS last_tested_at")
