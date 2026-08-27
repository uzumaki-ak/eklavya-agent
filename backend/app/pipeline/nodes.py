"""Graph node implementations.

Each node returns a partial state update. Nodes never raise on expected failures —
they record a `failure_stage` so routing can terminate cleanly.
"""

import logging

from app.agents.generator import ExecutionContext, GeneratorAgent
from app.agents.reviewer import ReviewerAgent
from app.core.exceptions import ModerationBlocked, ModerationUnavailable, PipelineDeadlineExceeded
from app.pipeline.state import AgentState
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.services.moderation import moderate_content, moderate_topic

logger = logging.getLogger(__name__)

_generator = GeneratorAgent()
_reviewer = ReviewerAgent()


async def moderate_topic_node(state: AgentState) -> dict:
    """Gate the user's topic before spending anything on generation."""
    try:
        result = await moderate_topic(state["topic"])
        return {"moderation_results": {**state["moderation_results"], "topic": result}}
    except ModerationBlocked:
        return _blocked(state, "topic")
    except ModerationUnavailable:
        return _mod_error(state, "topic")


async def generate_original_node(state: AgentState) -> dict:
    ctx = ExecutionContext(deadline=state["deadline"])
    try:
        output = await _generator.run(
            GeneratorInput(grade=state["grade"], topic=state["topic"]), ctx
        )
    except PipelineDeadlineExceeded:
        return _terminal(state, "generator_error", "pipeline_deadline_exceeded")
    except Exception as exc:
        logger.exception("generator failed")
        return _terminal(state, "generator_error", _error_code(exc))

    moderation = await _moderate_output(state, output, "original_output")
    if moderation is not None:
        return moderation

    return {
        "original_output": output.model_dump(),
        "schema_repair_attempts": state["schema_repair_attempts"] + ctx.schema_repair_attempts,
        "transport_attempts_total": state["transport_attempts_total"]
        + ctx.counters.get("transport_attempts", 0),
        "logical_llm_calls": state["logical_llm_calls"] + 1,
    }


async def review_original_node(state: AgentState) -> dict:
    return await _review(state, state["original_output"], "initial_review")


async def refine_node(state: AgentState) -> dict:
    """The single permitted refinement pass. Writes ONLY refined_output."""
    feedback = (state["initial_review"] or {}).get("feedback", [])
    ctx = ExecutionContext(deadline=state["deadline"], feedback=feedback)
    try:
        output = await _generator.run(
            GeneratorInput(grade=state["grade"], topic=state["topic"]), ctx
        )
    except PipelineDeadlineExceeded:
        return _terminal(state, "generator_error", "pipeline_deadline_exceeded")
    except Exception as exc:
        logger.exception("refinement failed")
        return _terminal(state, "generator_error", _error_code(exc))

    moderation = await _moderate_output(state, output, "refined_output")
    if moderation is not None:
        return moderation

    return {
        "refined_output": output.model_dump(),
        "refinement_count": 1,  # set, never incremented — the cap is structural
        "schema_repair_attempts": state["schema_repair_attempts"] + ctx.schema_repair_attempts,
        "transport_attempts_total": state["transport_attempts_total"]
        + ctx.counters.get("transport_attempts", 0),
        "logical_llm_calls": state["logical_llm_calls"] + 1,
    }


async def review_refined_node(state: AgentState) -> dict:
    return await _review(state, state["refined_output"], "final_review")


# --- helpers -------------------------------------------------------------


async def _review(state: AgentState, content: dict | None, field: str) -> dict:
    if content is None:
        return _terminal(state, "reviewer_error", "missing_content")
    counters: dict = {}
    try:
        review = await _reviewer.run(
            content=GeneratorOutput.model_validate(content),
            grade=state["grade"],
            topic=state["topic"],
            deadline=state["deadline"],
            counters=counters,
        )
    except PipelineDeadlineExceeded:
        return _terminal(state, "reviewer_error", "pipeline_deadline_exceeded")
    except Exception as exc:
        # Never fabricate a {"status": "fail"} here — a broken reviewer is a
        # technical error, not a quality verdict about the content.
        logger.exception("reviewer failed")
        return _terminal(state, "reviewer_error", _error_code(exc))

    return {
        field: review.model_dump(),
        "transport_attempts_total": state["transport_attempts_total"]
        + counters.get("transport_attempts", 0),
        "logical_llm_calls": state["logical_llm_calls"] + 1,
    }


async def _moderate_output(state: AgentState, output: GeneratorOutput, key: str) -> dict | None:
    """Returns a terminal state update if blocked/errored, else None."""
    try:
        result = await moderate_content(output)
        state["moderation_results"][key] = result
        return None
    except ModerationBlocked:
        return _blocked(state, key)
    except ModerationUnavailable:
        return _mod_error(state, key)


def _blocked(state: AgentState, key: str) -> dict:
    return {
        "failure_stage": "moderation_blocked",
        "error_code": f"blocked_at_{key}",
        "moderation_results": {**state["moderation_results"], key: {"outcome": "blocked"}},
    }


def _mod_error(state: AgentState, key: str) -> dict:
    # Fails closed like a block, but a distinct status so ops can tell
    # "safety caught something" from "safety is down".
    return {
        "failure_stage": "moderation_error",
        "error_code": f"moderation_unavailable_at_{key}",
        "moderation_results": {**state["moderation_results"], key: {"outcome": "error"}},
    }


def _terminal(state: AgentState, stage: str, code: str) -> dict:
    return {"failure_stage": stage, "error_code": code}


def _error_code(exc: BaseException) -> str:
    """Turn provider-specific exceptions into stable UI-safe codes."""
    if getattr(exc, "code", None) == 429:
        if "GenerateRequestsPerDay" in str(exc):
            return "provider_daily_quota_exhausted"
        return "provider_rate_limited"
    return type(exc).__name__
