"""Reviewer schema failures get bounded repair instead of immediately killing a run."""

import time

import pytest
from pydantic import ValidationError

from app.agents import reviewer as reviewer_module
from app.agents.reviewer import ReviewerAgent
from app.schemas.content import GeneratorOutput, ReviewerJudgement


def _content() -> GeneratorOutput:
    return GeneratorOutput.model_validate(
        {
            "explanation": "A right angle measures 90 degrees.",
            "mcqs": [
                {
                    "question": "How many degrees is a right angle?",
                    "options": ["45", "90", "180", "360"],
                    "answer": "90",
                }
            ],
        }
    )


async def test_reviewer_repairs_an_omitted_topic_flag(monkeypatch):
    calls: list[str] = []

    async def fake_call_llm(**kwargs):
        calls.append(kwargs["user"])
        if len(calls) == 1:
            ReviewerJudgement.model_validate({"status": "pass", "feedback": []})
        return ReviewerJudgement(
            status="pass", feedback=[], addresses_requested_topic=True
        )

    monkeypatch.setattr(reviewer_module, "call_llm", fake_call_llm)
    counters = {}
    judgement = await ReviewerAgent().judge(
        _content(), 4, "Types of angles", time.monotonic() + 10, counters
    )

    assert judgement.status == "pass"
    assert len(calls) == 2
    assert "previous review failed" in calls[1]
    assert counters["schema_repair_attempts"] == 1


def test_reviewer_feedback_is_required_by_provider_schema():
    required = ReviewerJudgement.model_json_schema()["required"]
    assert "feedback" in required
    assert "addresses_requested_topic" in required


def test_every_golden_case_reaches_the_reviewer_schema():
    from tests.reviewer_golden_set import GOLDEN_SET

    for case in GOLDEN_SET:
        GeneratorOutput.model_validate(case.content)


async def test_reviewer_repair_is_bounded(monkeypatch):
    calls = 0

    async def always_invalid(**_kwargs):
        nonlocal calls
        calls += 1
        ReviewerJudgement.model_validate({"status": "pass", "feedback": []})

    monkeypatch.setattr(reviewer_module, "call_llm", always_invalid)
    counters = {}
    with pytest.raises(ValidationError):
        await ReviewerAgent().judge(
            _content(), 4, "Types of angles", time.monotonic() + 10, counters
        )

    assert calls == reviewer_module.settings.schema_repair_max_attempts + 1
    assert counters["schema_repair_attempts"] == reviewer_module.settings.schema_repair_max_attempts
