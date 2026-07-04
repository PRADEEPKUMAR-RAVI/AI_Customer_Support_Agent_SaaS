"""turn_metric table + its RLS policy (M2 writes per-turn metrics; M8 reads them).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

from app.infra.db.base import Base
from app.infra.db.models.metrics import TurnMetric

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# One statement per execute (asyncpg forbids multi-command statements).
_STMTS = [
    "ALTER TABLE turn_metric ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE turn_metric FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation ON turn_metric "
    "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
    "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)",
]

_GRANT = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON turn_metric TO cs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_bypass') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON turn_metric TO cs_bypass;
    END IF;
END $$;
"""


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), tables=[TurnMetric.__table__])
    for stmt in _STMTS:
        op.execute(stmt)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("ALTER TABLE turn_metric DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS turn_metric")
