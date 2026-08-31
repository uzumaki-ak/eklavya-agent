"""Part 2: explicit user_id, the RunArtifact, tags, and a two-refinement cap.

Revision ID: 0002
Revises: 0001

Existing rows are preserved, not rewritten. `user_id` is backfilled from
`session_id` so old rows keep an owner and the column can be NOT NULL, and their
`run_artifact` stays null — those runs were produced under an older content
schema, and inventing an artifact for them would put a v6-shaped payload behind a
v7-shaped contract. `GET /history` returns rows with valid artifacts across
schema versions; these legacy rows are excluded because their artifact is null.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

OLD_STATUSES = (
    "queued", "processing", "completed_pass", "completed_fail",
    "generator_error", "reviewer_error", "moderation_blocked", "moderation_error",
)
NEW_STATUSES = (
    "queued", "processing", "completed_pass", "completed_fail",
    "generator_error", "reviewer_error", "tagger_error",
    "moderation_blocked", "moderation_error",
)


def upgrade() -> None:
    # --- Explicit owner. Nullable, backfilled, then locked down. ---
    op.add_column(
        "generation_runs", sa.Column("user_id", sa.String(128), nullable=True)
    )
    op.execute("UPDATE generation_runs SET user_id = session_id WHERE user_id IS NULL")
    op.alter_column("generation_runs", "user_id", nullable=False)
    # One composite index, not two. (user_id, created_at) already answers
    # "this user's runs, newest first"; a separate single-column index on
    # user_id would be dead weight on every write.
    op.create_index("ix_runs_user_history", "generation_runs", ["user_id", "created_at"])

    # --- The audit artifact and the approved-content tags. ---
    op.add_column(
        "generation_runs", sa.Column("run_artifact", postgresql.JSONB, nullable=True)
    )
    op.add_column("generation_runs", sa.Column("tags", postgresql.JSONB, nullable=True))

    # --- Provenance for the two new roles. ---
    op.add_column("generation_runs", sa.Column("tagger_model", sa.String(64), nullable=True))
    op.add_column(
        "generation_runs", sa.Column("refiner_prompt_version", sa.String(16), nullable=True)
    )
    op.add_column(
        "generation_runs", sa.Column("tagger_prompt_version", sa.String(16), nullable=True)
    )

    # --- Two refinements are now permitted. ---
    op.drop_constraint("ck_run_refinement_cap", "generation_runs", type_="check")
    op.create_check_constraint(
        "ck_run_refinement_cap", "generation_runs", "refinement_count BETWEEN 0 AND 2"
    )

    # --- A tagging failure is its own terminal status. ---
    op.drop_constraint("ck_run_status", "generation_runs", type_="check")
    op.create_check_constraint(
        "ck_run_status", "generation_runs", f"status IN {NEW_STATUSES}"
    )


def downgrade() -> None:
    # Any run that failed at tagging has no equivalent in the old vocabulary;
    # generator_error is the closest honest mapping.
    op.execute(
        "UPDATE generation_runs SET status = 'generator_error' WHERE status = 'tagger_error'"
    )
    op.drop_constraint("ck_run_status", "generation_runs", type_="check")
    op.create_check_constraint(
        "ck_run_status", "generation_runs", f"status IN {OLD_STATUSES}"
    )

    op.execute("UPDATE generation_runs SET refinement_count = 1 WHERE refinement_count > 1")
    op.drop_constraint("ck_run_refinement_cap", "generation_runs", type_="check")
    op.create_check_constraint(
        "ck_run_refinement_cap", "generation_runs", "refinement_count BETWEEN 0 AND 1"
    )

    op.drop_column("generation_runs", "tagger_prompt_version")
    op.drop_column("generation_runs", "refiner_prompt_version")
    op.drop_column("generation_runs", "tagger_model")
    op.drop_column("generation_runs", "tags")
    op.drop_column("generation_runs", "run_artifact")

    op.drop_index("ix_runs_user_history", table_name="generation_runs")
    op.drop_column("generation_runs", "user_id")
