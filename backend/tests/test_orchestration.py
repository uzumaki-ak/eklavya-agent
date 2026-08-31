"""The assessment's three mandatory orchestration tests.

  1. schema validation failure handling
  2. fail -> refine -> pass
  3. fail -> refine -> fail -> refine -> fail -> reject

Everything else the graph must get right lives in `test_orchestration_edges.py`.
"""

import time

import pytest
from pydantic import ValidationError

from app.agents import execution as execution_module
from app.agents.execution import ExecutionContext
from app.agents.generator import GeneratorAgent
from app.core.config import settings
from app.schemas.content import GeneratorInput, GeneratorOutput
from tests.factories import draft
from tests.pipeline_harness import FakeGenerator, artifact_of, run_pipeline


# --- Mandatory test 1: schema validation failure handling ------------------


def test_the_shipped_repair_budget_is_the_specified_one():
    """"If validation fails -> retry once": one repair, two calls."""
    assert settings.schema_repair_max_attempts == 1


async def test_generator_schema_failure_gets_exactly_one_repair(monkeypatch):
    calls = 0

    async def always_invalid(**_kwargs):
        nonlocal calls
        calls += 1
        # Missing teacher_notes — a shape the provider schema cannot prevent
        # in every case, and the exact class the repair pass exists for.
        payload = draft()
        del payload["teacher_notes"]
        return GeneratorOutput.model_validate(payload)

    monkeypatch.setattr(execution_module, "call_llm", always_invalid)
    with pytest.raises(ValidationError):
        await GeneratorAgent().run(
            GeneratorInput(grade=5, topic="The solar system"),
            ExecutionContext(deadline=time.monotonic() + 10),
        )

    assert calls == 2, "one initial call plus exactly one repair"


async def test_a_generator_that_never_validates_fails_gracefully(monkeypatch):
    """The run ends as a rejected artifact, not an exception out of the graph."""
    state, agents = await run_pipeline(
        monkeypatch,
        verdicts=[],
        generator=FakeGenerator(error=ValueError("schema repair exhausted")),
    )

    assert state["failure_stage"] == "generator_error"
    artifact = artifact_of(state)
    assert artifact.final.status == "rejected"
    assert artifact.final.pipeline_status == "generator_error"
    assert artifact.final.tags is None
    assert agents["tagger"].calls == 0


# --- Mandatory test 2: fail -> refine -> pass ------------------------------


async def test_fail_then_refine_then_pass_is_approved_and_tagged(monkeypatch):
    state, agents = await run_pipeline(monkeypatch, verdicts=[False, True])

    assert agents["refiner"].calls == 1
    assert agents["tagger"].calls == 1
    assert state["refinement_count"] == 1

    artifact = artifact_of(state)
    assert artifact.final.status == "approved"
    assert artifact.final.tags is not None
    assert artifact.final.content is not None
    assert len(artifact.attempts) == 2
    assert artifact.attempts[0].refined == artifact.attempts[1].draft
    assert artifact.attempts[1].refined is None


async def test_the_refiner_receives_the_reviewer_field_paths(monkeypatch):
    """Explainable review: the Refiner is told which field to fix.

    Two items travel: the Reviewer's own complaint, and the one synthesised from
    the score that fell below its threshold. Both are anchored to a real path,
    which is what makes the feedback actionable rather than a mood.
    """
    _, agents = await run_pipeline(monkeypatch, verdicts=[False, True])

    assert len(agents["refiner"].seen_feedback) == 1
    paths = agents["refiner"].seen_feedback[0]
    assert "mcqs[0].question" in paths, "the reviewer's own complaint must survive"
    assert "explanation.text" in paths, "the failing score must be explained too"


# --- Mandatory test 3: fail -> refine -> fail -> refine -> fail -> reject --


async def test_two_failed_refinements_reject_and_never_tag(monkeypatch):
    state, agents = await run_pipeline(monkeypatch, verdicts=[False, False, False])

    assert agents["refiner"].calls == 2
    assert agents["reviewer"].calls == 3
    assert agents["tagger"].calls == 0, "rejected content must never be tagged"
    assert state["refinement_count"] == 2

    artifact = artifact_of(state)
    assert artifact.final.status == "rejected"
    assert artifact.final.pipeline_status == "completed_fail"
    assert artifact.final.tags is None
    assert artifact.final.content is None
    assert len(artifact.attempts) == 3


async def test_a_third_refinement_is_impossible(monkeypatch):
    """The budget is spent after two; nothing offers a third."""
    state, agents = await run_pipeline(monkeypatch, verdicts=[False, False, False])
    assert agents["generator"].calls + agents["refiner"].calls == 3
    assert state["refinement_count"] <= 2
