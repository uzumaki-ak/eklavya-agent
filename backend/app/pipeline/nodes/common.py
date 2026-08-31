"""Shared node plumbing.

Every node returns a partial state update and never raises on an expected
failure — it records a `failure_stage` so routing can terminate cleanly instead
of the graph unwinding through an exception.
"""

import logging

from app.agents.execution import ExecutionContext
from app.core.config import settings
from app.core.exceptions import ModerationBlocked, ModerationUnavailable
from app.pipeline.state import AgentState
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.services.moderation import moderate_content

logger = logging.getLogger(__name__)


def request_of(state: AgentState) -> GeneratorInput:
    return GeneratorInput(grade=state["grade"], topic=state["topic"])


def context_of(state: AgentState) -> ExecutionContext:
    return ExecutionContext(deadline=state["deadline"])


def counters(state: AgentState, ctx: ExecutionContext, calls: int = 1) -> dict:
    """Roll one agent call's retry counters into the running totals."""
    return {
        "schema_repair_attempts": state["schema_repair_attempts"] + ctx.schema_repair_attempts,
        "transport_attempts_total": state["transport_attempts_total"] + ctx.transport_attempts,
        "logical_llm_calls": state["logical_llm_calls"] + calls,
    }


async def moderate_output(
    state: AgentState, output: GeneratorOutput, key: str
) -> dict | None:
    """Returns a terminal state update if blocked or errored, else None."""
    try:
        result = await moderate_content(output)
        state["moderation_results"][key] = result
        return None
    except ModerationBlocked:
        return blocked(state, key)
    except ModerationUnavailable:
        return moderation_error(state, key)


def blocked(state: AgentState, key: str) -> dict:
    return {
        "failure_stage": "moderation_blocked",
        "error_code": f"blocked_at_{key}",
        "moderation_results": {
            **state["moderation_results"],
            key: {
                "outcome": "blocked",
                "policy_version": settings.moderation_policy_version,
                "stage": key,
            },
        },
    }


def moderation_error(state: AgentState, key: str) -> dict:
    # Fails closed like a block, but a distinct status so ops can tell
    # "safety caught something" from "safety is down".
    return {
        "failure_stage": "moderation_error",
        "error_code": f"moderation_unavailable_at_{key}",
        "moderation_results": {
            **state["moderation_results"],
            key: {
                "outcome": "error",
                "policy_version": settings.moderation_policy_version,
                "stage": key,
            },
        },
    }


def terminal(stage: str, code: str) -> dict:
    return {"failure_stage": stage, "error_code": code}


def terminal_after_call(
    state: AgentState,
    ctx: ExecutionContext,
    stage: str,
    code: str,
) -> dict:
    """Terminalize an agent call without dropping the attempts it consumed."""
    return {**terminal(stage, code), **counters(state, ctx)}


def error_code(exc: BaseException) -> str:
    """Turn provider-specific exceptions into stable UI-safe codes."""
    if getattr(exc, "code", None) == 429:
        if "GenerateRequestsPerDay" in str(exc):
            return "provider_daily_quota_exhausted"
        return "provider_rate_limited"
    return type(exc).__name__
