"""The live UI reads the SSE stream, so its payload shape is a real contract.

Regression: the stream dumped `JobResponse` without `by_alias`, so the review's
verdict arrived as "passed" while the UI read "pass". Every approved lesson was
rendered as "Found things to fix" — with four 5/5 scores, no feedback, and the
tagging step already complete, which is what made it obviously wrong on screen.

FastAPI applies aliases to `response_model` returns on its own, so the polling
endpoint was correct and only the hand-rolled stream dump was broken. That
asymmetry is why both are pinned here.
"""

from types import SimpleNamespace

from app.api.routes.jobs import _to_response
from app.schemas.api import JobResponse
from tests.factories import draft, review_dict, tags


def _run(**overrides):
    base = {
        "id": "8b0d2a1e-0000-4000-8000-000000000000",
        "status": "completed_pass",
        "grade": 1,
        "topic_original": "Shapes around us",
        "cache_hit": False,
        "original_output": draft(grade=1),
        "initial_review": review_dict(passed=True),
        "refined_output": None,
        "final_review": None,
        "tags": tags(grade=1).model_dump(),
        "refinement_count": 0,
        "error_code": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _stream_payload(run) -> dict:
    """Exactly what the SSE endpoint serialises."""
    return _to_response(run).model_dump(mode="json", by_alias=True)


def test_stream_uses_the_spec_key_for_the_verdict():
    review = _stream_payload(_run())["initial_review"]
    assert "pass" in review, "the UI reads review.pass"
    assert "passed" not in review, "the attribute name must not leak to the client"


def test_a_passing_review_streams_as_true():
    assert _stream_payload(_run())["initial_review"]["pass"] is True


def test_a_failing_review_streams_as_false():
    run = _run(status="completed_fail", initial_review=review_dict(passed=False))
    review = _stream_payload(run)["initial_review"]
    assert review["pass"] is False
    assert review["feedback"], "a failing verdict must carry its reasons"


def test_scores_reach_the_client():
    scores = _stream_payload(_run())["initial_review"]["scores"]
    assert set(scores) == {"age_appropriateness", "correctness", "clarity", "coverage"}


def test_the_quiz_answer_reaches_the_client_as_an_index():
    mcq = _stream_payload(_run())["original_output"]["mcqs"][0]
    assert "correct_index" in mcq
    assert "answer" not in mcq, "the answer text is derived, never sent as a field"


def test_the_polling_response_model_carries_the_same_alias():
    """FastAPI aliases `response_model` returns; this pins the shape both share."""
    assert "pass" in JobResponse.model_json_schema()["$defs"]["ReviewerOutput"]["properties"]
