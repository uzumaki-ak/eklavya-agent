"""The pipeline envelope: the four stage outputs the UI needs, plus its status.

One shared derivation, used by the worker, the API's cache path, and the cache
itself — previously each computed status separately and the cache paths always
claimed "pass", so a cached failing review was reported as having passed.
"""

COMPLETED = {"completed_pass", "completed_fail"}

STAGE_FIELDS = ("original_output", "initial_review", "refined_output", "final_review")


def envelope_from_state(state: dict) -> dict:
    """Stage outputs only — no status, no internals."""
    return {field: state.get(field) for field in STAGE_FIELDS}


def status_from_envelope(envelope: dict) -> str:
    """Derive the terminal status from the reviews inside an envelope.

    The last review that ran wins: a refined draft is judged by final_review.
    """
    review = envelope.get("final_review") or envelope.get("initial_review") or {}
    return "completed_pass" if review.get("status") == "pass" else "completed_fail"


def final_status(state: dict) -> str:
    """Terminal status for a finished pipeline run."""
    if state.get("failure_stage"):
        return state["failure_stage"]
    return status_from_envelope(state)


def cacheable(status: str) -> bool:
    """Only clean, completed results may be cached — never an error or a block."""
    return status in COMPLETED
