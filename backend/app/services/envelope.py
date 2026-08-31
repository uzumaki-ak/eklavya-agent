"""The pipeline envelope: one run's content result, and everything derived from it.

There is exactly one path from pipeline state to stored data:

    state ──► envelope ──┬──► RunArtifact   (the Part 2 source of truth)
                         └──► summary columns (queue state, indexing, live progress)

Both outputs come from the same envelope so they cannot disagree. That is not
theoretical caution: Part 1 had the cache path and the worker path each derive
the run's status separately, and the cache paths always claimed "pass", so a
cached failing review was replayed as a success.

The envelope is also the cache payload, which is why it holds content and not
identity — run_id, user_id and timestamps belong to the run reusing it, not to
the run that produced it.
"""

COMPLETED = {"completed_pass", "completed_fail"}

# What one run produced. `drafts` and `reviews` are the full ordered trail.
CONTENT_FIELDS = ("drafts", "reviews", "tags", "refinement_count", "moderation_results")

# The Part 1 columns, kept as a fixed-width summary for the UI's live stage view
# and for indexing. They are a projection of the envelope, never a second copy:
# with two refinements there are up to six artifacts and only four slots, so
# these hold the first cycle and the final outcome. The complete trail lives in
# the artifact.
SUMMARY_COLUMNS = ("original_output", "initial_review", "refined_output", "final_review")


def envelope_from_state(state: dict) -> dict:
    """Content only — no status, no identity, no internals."""
    return {
        "drafts": list(state.get("drafts") or []),
        "reviews": list(state.get("reviews") or []),
        "tags": state.get("tags"),
        "refinement_count": state.get("refinement_count", 0) or 0,
        "moderation_results": dict(state.get("moderation_results") or {}),
    }


def summary_from_envelope(envelope: dict) -> dict:
    """Project the trail onto the four fixed columns."""
    drafts = envelope.get("drafts") or []
    reviews = envelope.get("reviews") or []
    return {
        "original_output": drafts[0] if drafts else None,
        "initial_review": reviews[0] if reviews else None,
        "refined_output": drafts[-1] if len(drafts) > 1 else None,
        "final_review": reviews[-1] if len(reviews) > 1 else None,
    }


def approved(envelope: dict) -> bool:
    """A run is approved when its last review passed and its content is tagged."""
    reviews = envelope.get("reviews") or []
    if not reviews or reviews[-1].get("pass") is not True:
        return False
    # Tagging is part of approval, not a decoration on top of it: an untagged
    # "approved" run would violate the artifact's own contract.
    return envelope.get("tags") is not None


def status_from_envelope(envelope: dict) -> str:
    """Derive the terminal status from the reviews inside an envelope."""
    return "completed_pass" if approved(envelope) else "completed_fail"


def final_status(state: dict) -> str:
    """Terminal status for a finished pipeline run."""
    if state.get("failure_stage"):
        return state["failure_stage"]
    return status_from_envelope(envelope_from_state(state))


def cacheable(status: str) -> bool:
    """Only clean, completed results may be cached — never an error or a block."""
    return status in COMPLETED
