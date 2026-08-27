"""Graph routing tests — the assessment's hard rules, checked without an API key.

Covers: the one-refinement cap, that a draft is never overwritten, and that
moderation/technical failures exit instead of being treated as quality verdicts.
"""

from app.pipeline.graph import _after_generate, _after_moderation, _after_refine, _after_review
from langgraph.graph import END


def _state(**overrides) -> dict:
    base = {
        "original_output": None,
        "initial_review": None,
        "refined_output": None,
        "refinement_count": 0,
        "failure_stage": None,
    }
    return {**base, **overrides}


def test_moderation_block_ends_pipeline():
    assert _after_moderation(_state(failure_stage="moderation_blocked")) == END


def test_moderation_error_ends_pipeline():
    # Distinct from a block, but still terminal — never generates anyway.
    assert _after_moderation(_state(failure_stage="moderation_error")) == END


def test_clean_topic_proceeds_to_generation():
    assert _after_moderation(_state()) == "generate_original"


def test_generator_failure_ends_pipeline():
    assert _after_generate(_state(failure_stage="generator_error")) == END


def test_passing_review_ends_pipeline():
    state = _state(original_output={"explanation": "x"}, initial_review={"status": "pass"})
    assert _after_review(state) == END


def test_failing_review_triggers_one_refinement():
    state = _state(
        original_output={"explanation": "x"},
        initial_review={"status": "fail", "feedback": ["too hard"]},
        refinement_count=0,
    )
    assert _after_review(state) == "refine"


def test_refinement_cap_is_structural():
    """Even with a failing review, a second refinement is impossible."""
    state = _state(
        original_output={"explanation": "x"},
        initial_review={"status": "fail", "feedback": ["still too hard"]},
        refinement_count=1,  # already refined once
    )
    assert _after_review(state) == END


def test_reviewer_error_does_not_trigger_refinement():
    # A broken reviewer is a technical failure, not a "fail" verdict —
    # refining on it would be acting on feedback that does not exist.
    state = _state(original_output={"explanation": "x"}, failure_stage="reviewer_error")
    assert _after_review(state) == END


def test_refinement_routes_to_second_review():
    assert _after_refine(_state(refined_output={"explanation": "y"})) == "review_refined"


def test_failed_refinement_ends_pipeline():
    assert _after_refine(_state(failure_stage="generator_error")) == END
