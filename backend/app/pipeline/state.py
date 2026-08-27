"""Pipeline state.

Original and refined outputs are kept in SEPARATE fields — the UI must show both,
so a refinement must never overwrite the draft it replaced.
"""

from typing import Literal, TypedDict

FailureStage = Literal[
    "generator_error",
    "reviewer_error",
    "moderation_blocked",
    "moderation_error",
]


class AgentState(TypedDict, total=False):
    # --- Input ---
    run_id: str
    grade: int
    topic: str
    deadline: float  # time.monotonic() cutoff

    # --- Stage outputs (each written once, never overwritten) ---
    original_output: dict | None
    initial_review: dict | None
    refined_output: dict | None
    final_review: dict | None

    # --- Counters: three distinct failure classes, deliberately not merged ---
    refinement_count: int  # content quality; hard cap of 1 per spec
    schema_repair_attempts: int  # output failed Pydantic validation
    transport_attempts_total: int  # network/rate-limit retries
    logical_llm_calls: int

    # --- Terminal state ---
    failure_stage: FailureStage | None
    error_code: str | None
    moderation_results: dict


def new_state(run_id: str, grade: int, topic: str, deadline: float) -> AgentState:
    return AgentState(
        run_id=run_id,
        grade=grade,
        topic=topic,
        deadline=deadline,
        original_output=None,
        initial_review=None,
        refined_output=None,
        final_review=None,
        refinement_count=0,
        schema_repair_attempts=0,
        transport_attempts_total=0,
        logical_llm_calls=0,
        failure_stage=None,
        error_code=None,
        moderation_results={},
    )
