"""RunArtifact — the complete, auditable record of one generation run.

This is the Part 2 core requirement: a single object capturing the whole
lifecycle from first draft to final decision. It is the source of truth. The
operational columns on `generation_runs` remain, but they are a summary for
queue state, indexing and live progress — never a second, independently
constructed version of this. Both come from one derivation in
`app.pipeline.artifact`.

Structural invariants are enforced here rather than trusted from the pipeline,
so a malformed audit trail cannot be persisted and later read back as fact.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.content import GeneratorOutput
from app.schemas.moderation import ModerationResult
from app.schemas.review import ReviewerOutput
from app.schemas.tags import ContentTags

# Draft, plus at most two refinements, each of which is reviewed in turn.
MAX_ATTEMPTS = 3

FinalStatus = Literal["approved", "rejected"]


class RunInput(BaseModel):
    """The request that started the run."""

    model_config = ConfigDict(extra="forbid")

    grade: int = Field(ge=1, le=12)
    topic: str = Field(min_length=1, max_length=200)


class Attempt(BaseModel):
    """One cycle. Cleared content forms a verified draft/refinement chain;
    moderation-stopped content is represented only by `content_withheld`."""

    model_config = ConfigDict(extra="forbid")

    attempt: int = Field(ge=1, le=MAX_ATTEMPTS)
    draft: GeneratorOutput | None = None
    review: ReviewerOutput | None = None
    refined: GeneratorOutput | None = None
    content_withheld: bool = False

    @model_validator(mode="after")
    def withheld_content_is_never_stored(self):
        if self.content_withheld:
            if self.draft is not None or self.review is not None or self.refined is not None:
                raise ValueError("a withheld attempt must not carry content or a review")
        elif self.draft is None:
            raise ValueError("a visible attempt must carry its draft")
        return self


class FinalDecision(BaseModel):
    """The verdict, plus enough detail to explain a technical failure.

    `status` is the spec's approved/rejected. `pipeline_status` keeps the precise
    internal outcome (`completed_fail`, `moderation_blocked`, `reviewer_error`)
    because "rejected" alone cannot distinguish "the content was not good enough"
    from "the reviewer was unreachable" — and those need different responses.
    """

    model_config = ConfigDict(extra="forbid")

    status: FinalStatus
    content: GeneratorOutput | None = None
    tags: ContentTags | None = None
    pipeline_status: str
    reason_code: str | None = None

    @model_validator(mode="after")
    def approved_content_is_complete(self):
        if self.status == "approved":
            if self.content is None:
                raise ValueError("an approved run must carry its final content")
            if self.tags is None:
                raise ValueError("an approved run must carry tags")
        elif self.tags is not None:
            # Tags on a rejected run would violate the Tagger's approved-only gate.
            raise ValueError("a rejected run must not carry tags")
        return self


class RunTimestamps(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    finished_at: datetime | None = None


class RunProvenance(BaseModel):
    """Models and prompt versions, fixed per run for historical accuracy."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    generator_model: str | None = None
    reviewer_model: str | None = None
    tagger_model: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    schema_version: str | None = None
    cache_hit: bool = False
    refinement_count: int = Field(default=0, ge=0, le=MAX_ATTEMPTS - 1)
    logical_llm_calls: int = Field(default=0, ge=0)
    schema_repair_attempts: int = Field(default=0, ge=0)
    transport_attempts_total: int = Field(default=0, ge=0)


class RunArtifact(BaseModel):
    """The complete lifecycle record for one run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    user_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:@-]+$",
    )
    input: RunInput
    attempts: list[Attempt] = Field(max_length=MAX_ATTEMPTS)
    moderation_results: dict[str, ModerationResult] = Field(default_factory=dict)
    final: FinalDecision
    timestamps: RunTimestamps
    provenance: RunProvenance | None = None

    @model_validator(mode="after")
    def check_chain(self):
        """Attempts must be consecutive from 1, and each refinement must be the
        next attempt's draft. A broken chain is a broken audit trail."""
        expected = list(range(1, len(self.attempts) + 1))
        if [a.attempt for a in self.attempts] != expected:
            raise ValueError(f"attempts must be numbered {expected}")

        for earlier, later in zip(self.attempts, self.attempts[1:]):
            if earlier.review is None:
                raise ValueError(
                    f"attempt {earlier.attempt} has no review but a later attempt follows it"
                )
            if later.content_withheld:
                if earlier.review.passed or earlier.refined is not None:
                    raise ValueError("withheld refinement must follow a failing review")
                continue
            if earlier.refined is None:
                raise ValueError(
                    f"attempt {earlier.attempt} has no refinement but attempt "
                    f"{later.attempt} follows it"
                )
            if earlier.refined != later.draft:
                raise ValueError(
                    f"attempt {later.attempt} does not review the content produced "
                    f"by attempt {earlier.attempt}"
                )

        if (
            self.attempts
            and self.attempts[-1].review is not None
            and self.attempts[-1].review.passed
        ):
            if self.attempts[-1].refined is not None:
                raise ValueError("a passing review must not be followed by a refinement")

        if self.final.status == "approved":
            if self.final.pipeline_status != "completed_pass":
                raise ValueError("an approved artifact must have completed_pass status")
            if not self.attempts or self.attempts[-1].review is None:
                raise ValueError("an approved artifact must end with a completed review")
            if not self.attempts[-1].review.passed:
                raise ValueError("an approved artifact must end with a passing review")
            if self.final.content != self.attempts[-1].draft:
                raise ValueError("final approved content must equal the last reviewed draft")
        elif self.final.pipeline_status == "completed_pass":
            raise ValueError("completed_pass cannot be represented as rejected")

        if self.provenance is not None:
            expected_refinements = max(0, len(self.attempts) - 1)
            if self.provenance.refinement_count != expected_refinements:
                raise ValueError(
                    "provenance refinement_count must match the attempt chain"
                )

        if (
            self.timestamps.finished_at is not None
            and self.timestamps.finished_at < self.timestamps.started_at
        ):
            raise ValueError("finished_at must not precede started_at")
        return self
