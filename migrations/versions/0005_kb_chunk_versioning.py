"""kb_chunk serving-version pointer — delete-last reingest ([IMP-RAG-8]).

Reingest must be delete-*last*: build the new generation's chunks, atomically flip a serving
pointer, then delete the old generation. A failed reingest must leave the old version live. We
model the "serving pointer" as ``source.serving_version`` (the generation currently answered from)
and tag every ``kb_chunk`` with the ``version`` it belongs to; retrieval filters
``kb_chunk.version = source.serving_version``. Existing rows are generation 0.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (IF NOT EXISTS): on a FRESH DB, 0001's Base.metadata.create_all already builds
    # these from the current (post-P2) models, so this must no-op there; on a pre-P2 DB (0001 ran
    # before these columns existed) it genuinely adds them. Same for the index.
    op.execute("ALTER TABLE source ADD COLUMN IF NOT EXISTS serving_version integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE kb_chunk ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 0")
    # Retrieval and the delete-last sweep both filter by (source_id, version).
    op.execute("CREATE INDEX IF NOT EXISTS ix_kb_chunk_source_version ON kb_chunk (source_id, version)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_chunk_source_version")
    op.execute("ALTER TABLE kb_chunk DROP COLUMN version")
    op.execute("ALTER TABLE source DROP COLUMN serving_version")
