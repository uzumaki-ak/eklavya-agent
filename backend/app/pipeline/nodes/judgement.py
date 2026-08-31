"""Judging nodes: the three reviews and the tagger.

All three review nodes are the same function. The graph, not the node, decides
which draft is being reviewed and where the verdict leads — a review node has no
idea whether it is the first or the last, which is why none of them can route
back into a refinement they were not given an edge to.
"""

import logging

from app.agents.reviewer import ReviewerAgent
from app.agents.tagger import TaggerAgent
from app.core.exceptions import PipelineDeadlineExceeded
from app.pipeline.nodes.common import (
    context_of,
    counters,
    error_code,
    request_of,
    terminal,
    terminal_after_call,
)
from app.pipeline.state import AgentState
from app.schemas.content import GeneratorOutput

logger = logging.getLogger(__name__)

_reviewer = ReviewerAgent()
_tagger = TaggerAgent()


async def review_node(state: AgentState) -> dict:
    """Judge the most recent draft. Used at every review point in the graph."""
    drafts = state.get("drafts") or []
    if not drafts:
        return terminal("reviewer_error", "missing_content")

    ctx = context_of(state)
    try:
        review = await _reviewer.run(
            content=GeneratorOutput.model_validate(drafts[-1]),
            grade=state["grade"],
            topic=state["topic"],
            ctx=ctx,
        )
    except PipelineDeadlineExceeded:
        return terminal_after_call(
            state, ctx, "reviewer_error", "pipeline_deadline_exceeded"
        )
    except Exception as exc:
        # Never fabricate a failing verdict here — a broken reviewer is a
        # technical error, not a quality judgement about the content.
        logger.exception("reviewer failed")
        return terminal_after_call(state, ctx, "reviewer_error", error_code(exc))

    return {
        # by_alias so the stored key is the spec's "pass", not the attribute name.
        "reviews": [*state["reviews"], review.model_dump(by_alias=True)],
        **counters(state, ctx),
    }


async def tag_node(state: AgentState) -> dict:
    """Classify approved content. Reachable only from a passing review.

    A tagging failure is terminal rather than "approved without tags": the
    artifact's contract is that approved content is catalogued, and publishing an
    approval with no subject or grade label is a worse outcome than a run the
    operator can see failed and retry. `pipeline_status` keeps it distinguishable
    from a quality rejection.
    """
    ctx = context_of(state)
    try:
        tags = await _tagger.run(
            request_of(state),
            GeneratorOutput.model_validate(state["drafts"][-1]),
            ctx,
        )
    except PipelineDeadlineExceeded:
        return terminal_after_call(
            state, ctx, "tagger_error", "pipeline_deadline_exceeded"
        )
    except Exception as exc:
        logger.exception("tagger failed")
        return terminal_after_call(state, ctx, "tagger_error", error_code(exc))

    return {"tags": tags.model_dump(), **counters(state, ctx)}
