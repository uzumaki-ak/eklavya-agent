"""Pipeline state.

Drafts and reviews are parallel, append-only lists rather than fixed fields.
Part 1 had four named slots because there was exactly one refinement; two
refinements produce six artifacts, and naming them `refined_output_2` would make
the audit trail a function of how many slots someone remembered to add.

The lists hold content that cleared moderation:

    drafts[i]   the content reviewed on attempt i+1
    reviews[i]  the review of drafts[i]

so attempt N's `refined` is simply `drafts[N]` when it exists. A node never
rewrites an earlier entry — it returns the previous list plus one item, which is
what keeps cleared content append-only. Safety-blocked content is not stored;
`moderation_results` records that the attempt happened and the artifact marks
its content as withheld. Every attempt is accounted for without returning
harmful text from history.
"""

from datetime import datetime, timezone
from typing import Literal, TypedDict

FailureStage = Literal[
    "generator_error",
    "reviewer_error",
    "tagger_error",
    "moderation_blocked",
    "moderation_error",
]

# Draft plus at most two refinements.
MAX_REFINEMENTS = 2


class AgentState(TypedDict, total=False):
    # --- Input ---
    run_id: str
    user_id: str
    grade: int
    topic: str
    deadline: float  # time.monotonic() cutoff
    started_at: str  # ISO 8601, UTC

    # --- Audit trail: append-only, never rewritten ---
    drafts: list[dict]
    reviews: list[dict]
    tags: dict | None

    # --- Counters: distinct failure classes, deliberately not merged ---
    refinement_count: int  # content quality; hard cap of 2, enforced by the graph
    schema_repair_attempts: int  # output failed validation and was asked again
    transport_attempts_total: int  # network/rate-limit retries
    logical_llm_calls: int

    # --- Terminal state ---
    failure_stage: FailureStage | None
    error_code: str | None
    moderation_results: dict


def new_state(
    run_id: str, user_id: str, grade: int, topic: str, deadline: float
) -> AgentState:
    return AgentState(
        run_id=run_id,
        user_id=user_id,
        grade=grade,
        topic=topic,
        deadline=deadline,
        started_at=datetime.now(timezone.utc).isoformat(),
        drafts=[],
        reviews=[],
        tags=None,
        refinement_count=0,
        schema_repair_attempts=0,
        transport_attempts_total=0,
        logical_llm_calls=0,
        failure_stage=None,
        error_code=None,
        moderation_results={},
    )


def latest_draft(state: AgentState) -> dict | None:
    drafts = state.get("drafts") or []
    return drafts[-1] if drafts else None


def latest_review(state: AgentState) -> dict | None:
    reviews = state.get("reviews") or []
    return reviews[-1] if reviews else None
