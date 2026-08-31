"""Content-producing nodes: topic moderation, generation, and the two refinements.

Both refinement nodes are built from one factory. They differ only in which
refinement they are, and that number is *passed in* rather than counted from
state — the cap is a property of the graph's shape, not of a counter a node
could increment twice.
"""

import logging
from collections.abc import Awaitable, Callable

from app.agents.generator import GeneratorAgent
from app.agents.refiner import RefinerAgent
from app.core.exceptions import (
    ModerationBlocked,
    ModerationUnavailable,
    PipelineDeadlineExceeded,
)
from app.pipeline.nodes.common import (
    blocked,
    context_of,
    counters,
    error_code,
    moderate_output,
    moderation_error,
    request_of,
    terminal_after_call,
)
from app.pipeline.state import AgentState
from app.schemas.content import GeneratorOutput
from app.schemas.review import ReviewerOutput
from app.services.moderation import moderate_topic

logger = logging.getLogger(__name__)

_generator = GeneratorAgent()
_refiner = RefinerAgent()


async def moderate_topic_node(state: AgentState) -> dict:
    """Gate the user's topic before spending anything on generation."""
    try:
        result = await moderate_topic(state["topic"])
        return {"moderation_results": {**state["moderation_results"], "topic": result}}
    except ModerationBlocked:
        return blocked(state, "topic")
    except ModerationUnavailable:
        return moderation_error(state, "topic")


async def generate_node(state: AgentState) -> dict:
    """The first draft."""
    ctx = context_of(state)
    try:
        output = await _generator.run(request_of(state), ctx)
    except PipelineDeadlineExceeded:
        return terminal_after_call(
            state, ctx, "generator_error", "pipeline_deadline_exceeded"
        )
    except Exception as exc:
        logger.exception("generator failed")
        return terminal_after_call(state, ctx, "generator_error", error_code(exc))

    stop = await moderate_output(state, output, "draft_1")
    if stop is not None:
        return {**stop, **counters(state, ctx)}

    return {"drafts": [output.model_dump()], **counters(state, ctx)}


def _refine_node(number: int) -> Callable[[AgentState], Awaitable[dict]]:
    """Build the node for refinement `number` (1 or 2)."""

    async def node(state: AgentState) -> dict:
        drafts = state["drafts"]
        draft = GeneratorOutput.model_validate(drafts[-1])
        review = ReviewerOutput.model_validate(state["reviews"][-1])

        ctx = context_of(state)
        try:
            output = await _refiner.run(request_of(state), draft, review.feedback, ctx)
        except PipelineDeadlineExceeded:
            return terminal_after_call(
                state, ctx, "generator_error", "pipeline_deadline_exceeded"
            )
        except Exception as exc:
            logger.exception("refinement %d failed", number)
            return terminal_after_call(state, ctx, "generator_error", error_code(exc))

        stop = await moderate_output(state, output, f"draft_{number + 1}")
        if stop is not None:
            # The model call happened even though its content is withheld. Keep
            # the refinement count truthful without storing that text.
            return {**stop, "refinement_count": number, **counters(state, ctx)}

        return {
            "drafts": [*drafts, output.model_dump()],
            # Set to this node's own number, never incremented: refine_2 is
            # reachable only through refine_1, so the value cannot exceed 2.
            "refinement_count": number,
            **counters(state, ctx),
        }

    node.__name__ = f"refine_{number}_node"
    return node


refine_1_node = _refine_node(1)
refine_2_node = _refine_node(2)
