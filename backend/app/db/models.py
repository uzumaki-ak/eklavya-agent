"""SQLAlchemy models.

Two ideas are kept deliberately separate:
  - idempotency_key  -> "don't process one client's submission twice"
  - cache digest     -> "let different clients reuse produced content"
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STATUSES = (
    "queued",
    "processing",
    "completed_pass",
    "completed_fail",
    "generator_error",
    "reviewer_error",
    "moderation_blocked",
    "moderation_error",
)


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB}


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    grade: Mapped[int] = mapped_column(Integer)
    topic_original: Mapped[str] = mapped_column(String(200))
    topic_canonical: Mapped[str] = mapped_column(String(200))
    canonicalizer_version: Mapped[str] = mapped_column(String(16))
    cache_digest: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(32), default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Leasing: lease_epoch is a fencing token — it changes ONLY on takeover,
    # never on a normal stage write, so a superseded worker's writes are rejected.
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_epoch: Mapped[int] = mapped_column(Integer, default=0)

    cache_hit: Mapped[bool] = mapped_column(default=False)
    generator_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generator_prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewer_prompt_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(16), nullable=True)

    moderation_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Stage outputs — separate columns so the UI can always show draft vs refined.
    original_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    initial_review: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    refined_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_review: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    refinement_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    schema_repair_attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    transport_attempts_total: Mapped[int] = mapped_column(SmallInteger, default=0)
    logical_llm_calls: Mapped[int] = mapped_column(SmallInteger, default=0)

    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "idempotency_key", name="uq_run_session_idempotency"),
        CheckConstraint(f"status IN {STATUSES}", name="ck_run_status"),
        CheckConstraint("refinement_count BETWEEN 0 AND 1", name="ck_run_refinement_cap"),
        Index("ix_runs_history", "session_id", "created_at"),
        # Predicate must match the application query literally or the planner won't use it.
        Index(
            "ix_runs_topic",
            "grade",
            "topic_canonical",
            "created_at",
            postgresql_where=(status.in_(("completed_pass", "completed_fail"))),
        ),
    )


class ContentFlight(Base):
    """Single-flight coordination: one leader computes, everyone else waits and reuses."""

    __tablename__ = "content_flights"

    cache_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    leader_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    result_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('in_progress','done','failed')", name="ck_flight_status"),
    )
