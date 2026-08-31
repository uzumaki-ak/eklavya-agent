"""Streams the graph and persists progress after every node.

This is what makes the agent flow *live*. Running the graph with `ainvoke` and
saving once at the end means the UI sits on "Writing" and then jumps straight to
the finished result — the handoff the assessment asks us to show would never
actually be visible. Streaming state after each node lets SSE push
Writing -> Checking -> Fixing as they really happen.

Progress writes also keep the complete content envelope. The RunArtifact is
terminal by construction, so `persistence` writes it once from that checkpoint
on either success or a runner-level failure.
"""

import logging
import uuid

from app.core.exceptions import LeaseLost
from app.db import runs
from app.db.session import SessionLocal
from app.pipeline.graph import compiled_graph
from app.pipeline.state import new_state
from app.services.envelope import envelope_from_state, summary_from_envelope

logger = logging.getLogger(__name__)


def _stage_label(state: dict) -> str:
    """The stage now in progress, inferred from how far the trail has got."""
    if state.get("tags"):
        return "tagging"
    drafts = state.get("drafts") or []
    reviews = state.get("reviews") or []
    if not drafts:
        return "generating"
    if len(reviews) < len(drafts):
        return "reviewing"
    if reviews and reviews[-1].get("pass") is True:
        return "tagging"
    return "refining"


def _progress_fields(state: dict) -> dict:
    envelope = envelope_from_state(state)
    return {
        **summary_from_envelope(envelope),
        "progress_envelope": envelope,
        "tags": envelope["tags"],
        "refinement_count": envelope["refinement_count"],
        "schema_repair_attempts": state.get("schema_repair_attempts", 0),
        "transport_attempts_total": state.get("transport_attempts_total", 0),
        "logical_llm_calls": state.get("logical_llm_calls", 0),
        "moderation_results": state.get("moderation_results"),
        "current_stage": _stage_label(state),
    }


async def execute_graph(
    run_id: uuid.UUID,
    worker: str,
    epoch: int,
    user_id: str,
    grade: int,
    topic: str,
    deadline: float,
) -> dict:
    """Run the pipeline, saving progress as each stage lands. Returns final state."""
    state = new_state(str(run_id), user_id, grade, topic, deadline)
    latest = state
    last_written: dict | None = None

    # stream_mode="values" yields the full merged state after each node.
    async for snapshot in compiled_graph.astream(state, stream_mode="values"):
        latest = snapshot
        fields = _progress_fields(snapshot)
        if fields == last_written:
            continue
        last_written = fields

        # Best-effort progress write. A failure here must not kill the run —
        # the final persist in the runner is the authoritative one.
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await runs.write_stage(session, run_id, worker, epoch, **fields)
        except LeaseLost:
            raise  # we no longer own this job; stop immediately
        except Exception:
            logger.exception("progress write failed for run %s (continuing)", run_id)

    return latest
