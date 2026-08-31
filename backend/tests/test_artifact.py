"""The RunArtifact contract.

The artifact is the Part 2 core requirement, so its invariants are enforced by
the schema rather than trusted from the pipeline: a malformed audit trail must be
impossible to store, not merely unlikely to be produced. The endpoint that serves
them is covered in `test_history.py`.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.pipeline.artifact import build_artifact, envelope_from_artifact, meta_for_run
from app.schemas.artifact import Attempt, FinalDecision, RunArtifact, RunInput, RunTimestamps
from tests.factories import draft, review_dict, tags

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _envelope(*, drafts=1, verdicts=None, tagged=False, refinements=0) -> dict:
    verdicts = verdicts if verdicts is not None else [True]
    return {
        "drafts": [draft(text=f"Draft {i + 1}") for i in range(drafts)],
        "reviews": [review_dict(passed=v) for v in verdicts],
        "tags": tags().model_dump() if tagged else None,
        "refinement_count": refinements,
        "moderation_results": {},
    }


def _meta(status: str = "completed_pass", **overrides):
    return meta_for_run(
        run_id="run-1",
        user_id="user-1",
        grade=5,
        topic="The solar system",
        started_at=NOW,
        pipeline_status=status,
        **overrides,
    )


# --- Structure -------------------------------------------------------------


def test_an_approved_run_carries_content_and_tags():
    artifact = build_artifact(_envelope(tagged=True), _meta())
    assert artifact.final.status == "approved"
    assert artifact.final.content is not None
    assert artifact.final.tags is not None


def test_an_untagged_pass_is_not_an_approval():
    """Tagging is part of approval, not a decoration on top of it."""
    artifact = build_artifact(_envelope(tagged=False), _meta("tagger_error"))
    assert artifact.final.status == "rejected"


def test_a_rejected_run_may_not_carry_tags():
    with pytest.raises(ValidationError):
        FinalDecision(status="rejected", tags=tags(), pipeline_status="completed_fail")


def test_an_approved_run_must_carry_tags():
    with pytest.raises(ValidationError):
        FinalDecision(
            status="approved",
            content=draft(),
            tags=None,
            pipeline_status="completed_pass",
        )


def test_attempts_must_be_numbered_from_one():
    with pytest.raises(ValidationError):
        RunArtifact(
            run_id="r", user_id="u",
            input=RunInput(grade=5, topic="t"),
            attempts=[
                Attempt(attempt=2, draft=draft(), review=review_dict(passed=True))
            ],
            final=FinalDecision(status="rejected", pipeline_status="completed_fail"),
            timestamps=RunTimestamps(started_at=NOW),
        )


def test_a_broken_refinement_chain_is_rejected():
    """Attempt N's refinement must be attempt N+1's draft, or the trail lies."""
    with pytest.raises(ValidationError):
        RunArtifact(
            run_id="r", user_id="u",
            input=RunInput(grade=5, topic="t"),
            attempts=[
                Attempt(
                    attempt=1,
                    draft=draft(text="A"),
                    review=review_dict(passed=False),
                    refined=draft(text="B"),
                ),
                Attempt(
                    attempt=2,
                    draft=draft(text="C"),  # not the refinement above
                    review=review_dict(passed=False),
                ),
            ],
            final=FinalDecision(status="rejected", pipeline_status="completed_fail"),
            timestamps=RunTimestamps(started_at=NOW),
        )


def test_a_passing_review_may_not_be_followed_by_a_refinement():
    with pytest.raises(ValidationError):
        RunArtifact(
            run_id="r", user_id="u",
            input=RunInput(grade=5, topic="t"),
            attempts=[
                Attempt(
                    attempt=1,
                    draft=draft(text="A"),
                    review=review_dict(passed=True),
                    refined=draft(text="B"),
                )
            ],
            final=FinalDecision(status="rejected", pipeline_status="completed_fail"),
            timestamps=RunTimestamps(started_at=NOW),
        )


def test_a_technical_failure_still_produces_an_artifact():
    artifact = build_artifact({}, _meta("reviewer_error", reason_code="provider_rate_limited"))
    assert artifact.attempts == []
    assert artifact.final.status == "rejected"
    assert artifact.final.pipeline_status == "reviewer_error"
    assert artifact.final.reason_code == "provider_rate_limited"


def test_a_blocked_first_draft_is_counted_but_its_content_is_withheld():
    envelope = _envelope(drafts=0, verdicts=[], refinements=0)
    envelope["moderation_results"] = {"draft_1": {"outcome": "blocked"}}
    artifact = build_artifact(envelope, _meta("moderation_blocked"))

    assert len(artifact.attempts) == 1
    assert artifact.attempts[0].content_withheld is True
    assert artifact.attempts[0].draft is None
    assert artifact.moderation_results["draft_1"].outcome == "blocked"


def test_a_blocked_refinement_is_counted_without_storing_its_content():
    envelope = _envelope(drafts=1, verdicts=[False], refinements=1)
    envelope["moderation_results"] = {"draft_2": {"outcome": "blocked"}}
    artifact = build_artifact(envelope, _meta("moderation_blocked"))

    assert len(artifact.attempts) == 2
    assert artifact.attempts[0].refined is None
    assert artifact.attempts[1].content_withheld is True
    assert artifact.attempts[1].draft is None
    assert artifact.provenance.refinement_count == 1


def test_a_reused_result_is_recorded_as_a_cache_hit():
    artifact = build_artifact(_envelope(tagged=True), _meta(cache_hit=True))
    assert artifact.provenance.cache_hit is True
    assert artifact.run_id == "run-1", "a reused envelope must not carry the leader's identity"


def test_provenance_records_the_prompt_versions():
    artifact = build_artifact(_envelope(tagged=True), _meta())
    assert set(artifact.provenance.prompt_versions) >= {
        "generator", "reviewer", "refiner", "tagger"
    }


# --- Round trip ------------------------------------------------------------


def test_the_trail_survives_a_round_trip_through_the_artifact():
    """A single-flight follower reads the trail back out of the artifact."""
    original = _envelope(drafts=3, verdicts=[False, False, True], tagged=True, refinements=2)
    artifact = build_artifact(original, _meta())
    restored = envelope_from_artifact(artifact.model_dump(mode="json", by_alias=True))

    assert restored["drafts"] == original["drafts"]
    assert restored["reviews"] == original["reviews"]
    assert restored["refinement_count"] == 2
    assert restored["tags"] == original["tags"]


def test_an_unreviewed_final_refinement_survives_the_round_trip():
    envelope = {
        "drafts": [draft(text="A"), draft(text="B")],
        "reviews": [review_dict(passed=False)],
        "tags": None,
        "refinement_count": 1,
    }
    artifact = build_artifact(envelope, _meta("completed_fail"))
    restored = envelope_from_artifact(artifact.model_dump(mode="json", by_alias=True))
    assert len(artifact.attempts) == 2
    assert artifact.attempts[-1].review is None
    assert len(restored["drafts"]) == 2
