"""Make the run creation timestamp match the model contract.

Revision ID: 0003
Revises: 0002

Migration 0001 gave ``created_at`` a server default but accidentally left the
column nullable. Existing nulls are repaired before the constraint is added so
upgrading an older deployment is safe.
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE generation_runs SET created_at = now() WHERE created_at IS NULL"
    )
    op.alter_column(
        "generation_runs",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "generation_runs",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
