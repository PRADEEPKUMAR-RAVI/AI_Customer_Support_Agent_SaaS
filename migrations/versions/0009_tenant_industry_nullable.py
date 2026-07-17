"""tenant.industry becomes nullable — industry is now chosen in onboarding step 1, not required
at signup. A brand-new tenant has no industry until the admin sets it (one-time, via the new
`PATCH /api/v1/admin/tenant/industry`); every industry-dependent read path (the AI engine, the
records API) now guards against `None` explicitly instead of assuming it's always set.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ALTER COLUMN industry DROP NOT NULL")


def downgrade() -> None:
    # Only safe if no tenant has actually been left without an industry — a real rollback would
    # need to backfill first. Deliberately not attempted here.
    op.execute("ALTER TABLE tenant ALTER COLUMN industry SET NOT NULL")
