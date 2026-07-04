"""kb_chunk.embedding nullable — parent chunks carry no embedding (M3).

The parent/child chunking design stores parent rows with a NULL embedding (only children are
embedded + retrieved; retrieval filters ``embedding IS NOT NULL``). The initial model inferred
NOT NULL from a non-Optional ``Mapped[list[float]]``; drop that constraint.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE kb_chunk ALTER COLUMN embedding DROP NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE kb_chunk ALTER COLUMN embedding SET NOT NULL")
