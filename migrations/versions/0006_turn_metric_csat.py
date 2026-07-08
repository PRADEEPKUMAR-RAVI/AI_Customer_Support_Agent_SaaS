"""turn_metric.csat — thumbs up/down CSAT for §5.6 analytics.

The feedback endpoint records "up"/"down" onto the turn's metric row (M8 reads turn_metric, never
message.structured_out), so CSAT joins the same tenant-scoped, date-filterable fact table as the
other dashboard metrics.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (IF NOT EXISTS): on a FRESH DB, 0002's Base.metadata.create_all already builds
    # turn_metric from the current model (which now includes csat), so this no-ops there; on a
    # DB migrated before this column existed it genuinely adds it. No RLS change — the existing
    # turn_metric tenant_isolation policy (0002) already covers the whole row.
    op.execute("ALTER TABLE turn_metric ADD COLUMN IF NOT EXISTS csat varchar(4)")


def downgrade() -> None:
    op.execute("ALTER TABLE turn_metric DROP COLUMN IF EXISTS csat")
