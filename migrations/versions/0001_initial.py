"""initial schema: tables + RLS policies + pgvector/HNSW + FTS + role grants.

The RLS policies, the pgvector extension/HNSW opclass index, the FTS GIN index, and the role
grants are hand-authored here (never left to autogenerate) — Alembic can't diff pg_policies,
extensions, or index opclasses, so a new tenant table must not ship without its policy
([IMP-DAT-2]).

Revision ID: 0001
Revises:
Create Date: 2026-07-04
"""

from __future__ import annotations

from alembic import op

from app.infra.db.base import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Tenant-scoped tables get standard RLS. NOT listed: `tenant` (root registry) and
# `platform_audit_log` (cross-tenant, append-only) — both intentionally RLS-free.
TENANT_SCOPED = [
    "staff",
    "allowed_domain",
    "agent_settings",
    "conversation",
    "message",
    "ticket",
    "ticket_event",
    "resolution_summary",
    "tag_def",
    "ticket_tag",
    "internal_note",
    "outbox",
    "email_log",
    "source",
    "kb_chunk",
    "file_blob",
]

# nullif(..., '') is load-bearing: an unset GUC returns NULL and an empty-string GUC ('')
# becomes NULL too, so both fail closed (0 rows) instead of throwing ''::uuid cast errors.
_TENANT_FILTER = (
    "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
)


def _apply_tenant_policy(table: str) -> None:
    # asyncpg's prepared-statement protocol rejects multiple SQL commands passed to one
    # `execute()` call ("cannot insert multiple commands into a prepared statement"), so each
    # DDL statement is issued separately rather than as one semicolon-joined string.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({_TENANT_FILTER}) WITH CHECK ({_TENANT_FILTER})"
    )


def _apply_widget_key_policy() -> None:
    # widget_key is a PUBLIC identifier — permissive SELECT (pre-tenant bootstrap lookup),
    # tenant-scoped writes.
    op.execute("ALTER TABLE widget_key ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE widget_key FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY widget_key_public_read ON widget_key FOR SELECT USING (true)")
    op.execute(
        "CREATE POLICY widget_key_tenant_write ON widget_key FOR ALL "
        f"USING ({_TENANT_FILTER}) WITH CHECK ({_TENANT_FILTER})"
    )

# Grants are guarded so the migration also runs on a single-role dev DB.
_GRANTS = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_app') THEN
        GRANT USAGE ON SCHEMA public TO cs_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cs_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cs_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cs_bypass') THEN
        GRANT USAGE ON SCHEMA public TO cs_bypass;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cs_bypass;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cs_bypass;
    END IF;
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()

    # pgvector must exist before create_all (kb_chunk.embedding is a vector column).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create every table from the models (single source of truth for columns).
    Base.metadata.create_all(bind=bind)

    # RLS policies.
    for table in TENANT_SCOPED:
        _apply_tenant_policy(table)
    _apply_widget_key_policy()

    # Global-unique staff email (POC: one tenant per person; enables pre-tenant login lookup).
    op.execute("CREATE UNIQUE INDEX uq_staff_email_global ON staff (email)")

    # Vector (HNSW, cosine) + sparse FTS (GIN) indexes for hybrid retrieval.
    op.execute(
        "CREATE INDEX ix_kb_chunk_embedding_hnsw ON kb_chunk "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )
    op.execute("CREATE INDEX ix_kb_chunk_ts ON kb_chunk USING gin (ts)")

    # Outbox drain hot-path index (pending rows by age).
    op.execute(
        "CREATE INDEX ix_outbox_pending ON outbox (next_attempt_at) WHERE status = 'pending'"
    )

    op.execute(_GRANTS)


def downgrade() -> None:
    for table in [*TENANT_SCOPED, "widget_key"]:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    Base.metadata.drop_all(bind=op.get_bind())
