"""Initial schema: generation_runs + content_flights.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

STATUSES = (
    "queued", "processing", "completed_pass", "completed_fail",
    "generator_error", "reviewer_error", "moderation_blocked", "moderation_error",
)


def upgrade() -> None:
    op.create_table(
        "generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=True),
        sa.Column("grade", sa.Integer, nullable=False),
        sa.Column("topic_original", sa.String(200), nullable=False),
        sa.Column("topic_canonical", sa.String(200), nullable=False),
        sa.Column("canonicalizer_version", sa.String(16), nullable=False),
        sa.Column("cache_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("current_stage", sa.String(64), nullable=True),
        # Leasing / fencing
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_epoch", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("generator_model", sa.String(64), nullable=True),
        sa.Column("reviewer_model", sa.String(64), nullable=True),
        sa.Column("generator_prompt_version", sa.String(16), nullable=True),
        sa.Column("reviewer_prompt_version", sa.String(16), nullable=True),
        sa.Column("schema_version", sa.String(16), nullable=True),
        sa.Column("moderation_results", postgresql.JSONB, nullable=True),
        # Stage outputs kept separate so the UI can show draft vs refined
        sa.Column("original_output", postgresql.JSONB, nullable=True),
        sa.Column("initial_review", postgresql.JSONB, nullable=True),
        sa.Column("refined_output", postgresql.JSONB, nullable=True),
        sa.Column("final_review", postgresql.JSONB, nullable=True),
        sa.Column("refinement_count", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("schema_repair_attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("transport_attempts_total", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("logical_llm_calls", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("token_usage", postgresql.JSONB, nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_run_status"),
        sa.CheckConstraint("refinement_count BETWEEN 0 AND 1", name="ck_run_refinement_cap"),
        # Uniqueness is on the idempotency key ONLY — never on (grade, topic),
        # which would block storing repeat runs of the same lesson.
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_run_session_idempotency"),
    )

    op.create_index("ix_runs_history", "generation_runs", ["session_id", "created_at"])
    op.create_index("ix_runs_digest", "generation_runs", ["cache_digest"])
    # Partial index — application queries must use this exact predicate form
    # or the planner cannot prove implication and will ignore it.
    op.create_index(
        "ix_runs_topic",
        "generation_runs",
        ["grade", "topic_canonical", "created_at"],
        postgresql_where=sa.text("status IN ('completed_pass', 'completed_fail')"),
    )

    op.create_table(
        "content_flights",
        sa.Column("cache_digest", sa.String(64), primary_key=True),
        sa.Column("leader_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="in_progress"),
        sa.Column("result_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress','done','failed')", name="ck_flight_status"
        ),
    )


def downgrade() -> None:
    op.drop_table("content_flights")
    op.drop_index("ix_runs_topic", table_name="generation_runs")
    op.drop_index("ix_runs_digest", table_name="generation_runs")
    op.drop_index("ix_runs_history", table_name="generation_runs")
    op.drop_table("generation_runs")
