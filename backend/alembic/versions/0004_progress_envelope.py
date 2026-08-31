"""Persist the complete in-progress attempt trail for failure recovery.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("progress_envelope", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_runs", "progress_envelope")
