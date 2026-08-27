"""Streams the graph and persists after every node.

This is what makes the agent flow *live*. Running the graph with `ainvoke` and
saving once at the end means the UI sits on "Writing" and then jumps straight to
the finished result — the handoff the assessment asks us to show would never
actually be visible. Streaming state after each node lets SSE push
Writing -> Checking -> Fixing as they really happen.
"""

import logging
import uuid

from app.core.exceptions import LeaseLost
from app.db import runs
from app.db.session import SessionLocal
from app.pipeline.graph import compiled_graph
from app.pipeline.state import new_state

logger = logging.getLogger(__name__)

# Which stage label to show once a given field first appears.
_STAGE_BY_FIELD = (
    ("final_review", "reviewing_refined"),
    ("refined_output", "refining"),
    ("initial_review", "reviewing"),
    ("original_output", "generating"),
)

_PERSISTED_FIELDS = ("original_output", "initial_review", "refined_output", "final_review")


def _stage_label(state: dict) -> str:
    for field, label in _STAGE_BY_FIELD:
        if state.get(field):
            return label
    return "generating"


async def execute_graph(
    run_id: uuid.UUID,
    worker: str,
    epoch: int,
    grade: int,
    topic: str,
    deadline: float,
) -> dict:
    """Run the pipeline, saving progress as each stage lands. Returns final state."""
    state = new_state(str(run_id), grade, topic, deadline)
    latest = state
    seen: set[str] = set()

    # stream_mode="values" yields the full merged state after each node.
    async for snapshot in compiled_graph.astream(state, stream_mode="values"):
        latest = snapshot
        new_fields = {
            field: snapshot[field]
            for field in _PERSISTED_FIELDS
            if snapshot.get(field) and field not in seen
        }
        if not new_fields:
            continue
        seen.update(new_fields)

        # Best-effort progress write. A failure here must not kill the run —
        # the final persist in the runner is the authoritative one.
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await runs.write_stage(
                        session, run_id, worker, epoch,
                        current_stage=_stage_label(snapshot),
                        **new_fields,
                    )
        except LeaseLost:
            raise  # we no longer own this job; stop immediately
        except Exception:
            logger.exception("progress write failed for run %s (continuing)", run_id)

    return latest
