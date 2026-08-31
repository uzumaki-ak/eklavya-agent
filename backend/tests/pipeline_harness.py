"""Test doubles for driving the real graph without a model.

Every orchestration test runs `compiled_graph` itself rather than the routing
functions, so a wrong edge fails even when every unit test passes. Only the four
agents and the moderation calls are replaced; the graph, the state merging and
the artifact derivation are the real ones.
"""

import time
from datetime import datetime, timezone


from app.pipeline.artifact import build_artifact, meta_for_run
from app.pipeline.graph import compiled_graph
from app.pipeline.nodes import content as content_nodes
from app.pipeline.nodes import common as common_nodes
from app.pipeline.nodes import judgement as judgement_nodes
from app.pipeline.state import new_state
from app.schemas.content import GeneratorOutput
from tests.factories import draft, judgement, tags
from app.services.envelope import envelope_from_state, final_status


class FakeGenerator:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def run(self, data, ctx):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return GeneratorOutput.model_validate(draft(text="Draft 1"))


class FakeRefiner:
    def __init__(self):
        self.calls = 0
        self.seen_feedback: list[list[str]] = []

    async def run(self, data, draft_in, feedback, ctx):
        self.calls += 1
        self.seen_feedback.append([item.field for item in feedback])
        return GeneratorOutput.model_validate(draft(text=f"Draft {self.calls + 1}"))


class FakeReviewer:
    """Answers the queued verdicts in order."""

    def __init__(self, verdicts: list[bool], error: Exception | None = None):
        self.verdicts = list(verdicts)
        self.error = error
        self.calls = 0

    async def run(self, content, grade, topic, ctx):
        self.calls += 1
        if self.error is not None:
            raise self.error
        passed = self.verdicts.pop(0)
        return judgement(passed=passed).to_output()


class FakeTagger:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    async def run(self, data, content, ctx):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return tags()


async def _allow(*_args, **_kwargs) -> dict:
    return {"outcome": "clear"}


async def run_pipeline(monkeypatch, *, verdicts, generator=None, reviewer=None, tagger=None):
    """Drive the compiled graph end to end. Returns (state, agents)."""
    agents = {
        "generator": generator or FakeGenerator(),
        "refiner": FakeRefiner(),
        "reviewer": reviewer or FakeReviewer(verdicts),
        "tagger": tagger or FakeTagger(),
    }
    monkeypatch.setattr(content_nodes, "_generator", agents["generator"])
    monkeypatch.setattr(content_nodes, "_refiner", agents["refiner"])
    monkeypatch.setattr(judgement_nodes, "_reviewer", agents["reviewer"])
    monkeypatch.setattr(judgement_nodes, "_tagger", agents["tagger"])
    monkeypatch.setattr(content_nodes, "moderate_topic", _allow)
    monkeypatch.setattr(common_nodes, "moderate_content", _allow)

    state = new_state("run-1", "user-1", 5, "The solar system", time.monotonic() + 60)
    return await compiled_graph.ainvoke(state), agents


def artifact_of(state: dict):
    return build_artifact(
        envelope_from_state(state),
        meta_for_run(
            run_id=state["run_id"],
            user_id=state["user_id"],
            grade=state["grade"],
            topic=state["topic"],
            started_at=datetime.now(timezone.utc),
            pipeline_status=final_status(state),
            reason_code=state.get("error_code"),
            state=state,
        ),
    )


