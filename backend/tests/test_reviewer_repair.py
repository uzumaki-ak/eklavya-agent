"""Schema failures get one bounded repair instead of immediately killing a run."""

import time

import pytest
from pydantic import ValidationError

from app.agents import execution as execution_module
from app.agents.execution import ExecutionContext
from app.agents.reviewer import ReviewerAgent
from app.agents.tagger import TaggerAgent
from app.core.config import settings
from app.schemas.content import GeneratorInput, GeneratorOutput
from app.schemas.review import ReviewerJudgement
from tests.factories import PERFECT_SCORES, draft, judgement, tags


def _content() -> GeneratorOutput:
    return GeneratorOutput.model_validate(draft())


def _ctx() -> ExecutionContext:
    return ExecutionContext(deadline=time.monotonic() + 10)


async def test_reviewer_repairs_an_omitted_topic_flag(monkeypatch):
    calls: list[str] = []

    async def fake_call_llm(**kwargs):
        calls.append(kwargs["user"])
        if len(calls) == 1:
            # Fails closed: the omission raises rather than reading as on-topic.
            ReviewerJudgement.model_validate(
                {"scores": PERFECT_SCORES, "pass": True, "feedback": []}
            )
        return judgement()

    monkeypatch.setattr(execution_module, "call_llm", fake_call_llm)
    ctx = _ctx()
    verdict = await ReviewerAgent().judge(_content(), 4, "Types of angles", ctx)

    assert verdict.passed is True
    assert len(calls) == 2
    assert "previous response was rejected" in calls[1]
    assert ctx.schema_repair_attempts == 1


async def test_a_hallucinated_field_path_is_sent_back(monkeypatch):
    """Explainable review is enforced, not merely requested."""
    calls = 0

    async def fake_call_llm(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            ReviewerJudgement.model_validate(
                {
                    "scores": {**PERFECT_SCORES, "clarity": 2},
                    "pass": False,
                    "feedback": [{"field": "the second paragraph", "issue": "too long"}],
                    "addresses_requested_topic": True,
                }
            )
        return judgement(passed=False)

    monkeypatch.setattr(execution_module, "call_llm", fake_call_llm)
    verdict = await ReviewerAgent().judge(_content(), 4, "Types of angles", _ctx())

    assert calls == 2
    assert all(item.field.startswith(("explanation", "mcqs", "teacher_notes"))
               for item in verdict.feedback)


async def test_reviewer_repair_is_bounded(monkeypatch):
    calls = 0

    async def always_invalid(**_kwargs):
        nonlocal calls
        calls += 1
        ReviewerJudgement.model_validate(
            {"scores": PERFECT_SCORES, "pass": True, "feedback": []}
        )

    monkeypatch.setattr(execution_module, "call_llm", always_invalid)
    ctx = _ctx()
    with pytest.raises(ValidationError):
        await ReviewerAgent().judge(_content(), 4, "Types of angles", ctx)

    assert calls == settings.schema_repair_max_attempts + 1
    assert ctx.schema_repair_attempts == settings.schema_repair_max_attempts


async def test_tagger_repairs_a_grade_it_reassigned(monkeypatch):
    """The Tagger classifies what was produced; it does not get a vote on the grade."""
    calls = 0

    async def fake_call_llm(**_kwargs):
        nonlocal calls
        calls += 1
        return tags(grade=3) if calls == 1 else tags(grade=5)

    monkeypatch.setattr(execution_module, "call_llm", fake_call_llm)
    result = await TaggerAgent().run(
        GeneratorInput(grade=5, topic="The solar system"), _content(), _ctx()
    )

    assert calls == 2
    assert result.grade == 5


def test_provider_schema_uses_the_spec_key_for_pass():
    """`pass` is a Python keyword; the wire name must survive the alias."""
    schema = ReviewerJudgement.model_json_schema()
    assert "pass" in schema["properties"]
    assert "reported_pass" not in schema["properties"]


def test_every_golden_case_reaches_the_reviewer_schema():
    from tests.reviewer_golden_set import GOLDEN_SET

    for case in GOLDEN_SET:
        GeneratorOutput.model_validate(case.content)
