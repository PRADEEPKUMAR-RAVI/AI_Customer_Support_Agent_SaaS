"""M4 records tables + RLS: record_dataset, record_row, connector.

Backs the Upload/DB/API record sources. All three are tenant-scoped with hand-authored RLS
policies (Alembic can't diff pg_policies — a new tenant table must ship its policy, [IMP-DAT-2]).

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

from app.infra.db.base import Base
from app.infra.db.models.records import Connector, RecordDataset, RecordRow

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_TABLES = ["record_dataset", "record_row", "connector"]


def _policy_stmts(t: str) -> list[str]:
    return [
        f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY tenant_isolation ON {t} "
        "USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)",
    ]


def _grant(t: str) -> str:
    return f"""
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO cs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_bypass') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO cs_bypass;
    END IF;
END $$;
"""


def upgrade() -> None:
    Base.metadata.create_all(
        bind=op.get_bind(),
        tables=[RecordDataset.__table__, RecordRow.__table__, Connector.__table__],
    )
    for table in _TABLES:
        for stmt in _policy_stmts(table):
            op.execute(stmt)
        op.execute(_grant(table))


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
