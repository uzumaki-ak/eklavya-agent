"""Orchestration cases beyond the mandatory three.

The refinement budget, the enforced verdict driving the graph, and the three
technical-failure paths that must never be reported as quality verdicts.
"""

import time

from app.pipeline.graph import compiled_graph
from app.pipeline.nodes import content as content_nodes
from app.pipeline.nodes import common as common_nodes
from app.pipeline.state import new_state
from tests.factories import PERFECT_SCORES, judgement
from tests.pipeline_harness import (
    FakeGenerator,
    FakeRefiner,
    FakeReviewer,
    FakeTagger,
    artifact_of,
    run_pipeline,
)


# --- The remaining agreed cases -------------------------------------------


async def test_pass_on_the_second_refinement_is_approved(monkeypatch):
    state, agents = await run_pipeline(monkeypatch, verdicts=[False, False, True])

    assert agents["refiner"].calls == 2
    assert agents["tagger"].calls == 1
    artifact = artifact_of(state)
    assert artifact.final.status == "approved"
    assert len(artifact.attempts) == 3
    assert artifact.attempts[2].refined is None


async def test_a_clean_first_draft_skips_refinement(monkeypatch):
    state, agents = await run_pipeline(monkeypatch, verdicts=[True])

    assert agents["refiner"].calls == 0
    assert agents["tagger"].calls == 1
    assert state["refinement_count"] == 0
    assert len(artifact_of(state).attempts) == 1


async def test_a_reviewer_claiming_pass_with_failing_scores_triggers_refinement(monkeypatch):
    """The enforced verdict drives the graph, not the model's self-report."""

    class OverconfidentReviewer(FakeReviewer):
        async def run(self, content, grade, topic, ctx):
            self.calls += 1
            if self.calls == 1:
                return judgement(
                    passed=True,
                    scores={**PERFECT_SCORES, "correctness": 2},
                    feedback=[],
                ).to_output()
            return judgement(passed=True).to_output()

    state, agents = await run_pipeline(
        monkeypatch, verdicts=[], reviewer=OverconfidentReviewer([])
    )
    assert agents["refiner"].calls == 1
    assert artifact_of(state).final.status == "approved"


async def test_a_reviewer_error_is_not_a_quality_verdict(monkeypatch):
    state, agents = await run_pipeline(
        monkeypatch, verdicts=[], reviewer=FakeReviewer([], error=RuntimeError("boom"))
    )

    assert agents["refiner"].calls == 0, "never refine on feedback that does not exist"
    assert state["failure_stage"] == "reviewer_error"
    artifact = artifact_of(state)
    assert artifact.final.status == "rejected"
    assert artifact.final.pipeline_status == "reviewer_error"
    assert len(artifact.attempts) == 1
    assert artifact.attempts[0].draft.explanation.text == "Draft 1"
    assert artifact.attempts[0].review is None


async def test_failed_agent_call_counters_survive_into_the_artifact(monkeypatch):
    class ExhaustedGenerator(FakeGenerator):
        async def run(self, data, ctx):
            self.calls += 1
            ctx.counters["schema_repair_attempts"] = 1
            ctx.counters["transport_attempts"] = 2
            raise ValueError("schema repair exhausted")

    state, _ = await run_pipeline(
        monkeypatch,
        verdicts=[],
        generator=ExhaustedGenerator(),
    )
    artifact = artifact_of(state)
    assert artifact.provenance.logical_llm_calls == 1
    assert artifact.provenance.schema_repair_attempts == 1
    assert artifact.provenance.transport_attempts_total == 2


async def test_output_moderation_failure_keeps_the_call_counters(monkeypatch):
    """A blocked output is hidden, but the work that produced it stays auditable."""
    from app.core.exceptions import ModerationBlocked

    class RetriedGenerator(FakeGenerator):
        async def run(self, data, ctx):
            ctx.counters["schema_repair_attempts"] = 1
            ctx.counters["transport_attempts"] = 2
            return await super().run(data, ctx)

    async def block(*_args, **_kwargs):
        raise ModerationBlocked("draft")

    monkeypatch.setattr(content_nodes, "_generator", RetriedGenerator())
    monkeypatch.setattr(common_nodes, "moderate_content", block)
    state = new_state("run-1", "user-1", 5, "topic", time.monotonic() + 60)

    update = await content_nodes.generate_node(state)

    assert update["failure_stage"] == "moderation_blocked"
    assert update["logical_llm_calls"] == 1
    assert update["schema_repair_attempts"] == 1
    assert update["transport_attempts_total"] == 2

    state.update(update)
    artifact = artifact_of(state)
    assert len(artifact.attempts) == 1
    assert artifact.attempts[0].content_withheld is True
    assert artifact.attempts[0].draft is None
    assert artifact.moderation_results["draft_1"].outcome == "blocked"


async def test_blocked_refinement_is_counted_and_withheld(monkeypatch):
    """A safety block records the call without persisting its returned text."""
    from app.core.exceptions import ModerationBlocked
    from tests.factories import draft, review_dict

    async def block(*_args, **_kwargs):
        raise ModerationBlocked("refinement")

    monkeypatch.setattr(content_nodes, "_refiner", FakeRefiner())
    monkeypatch.setattr(common_nodes, "moderate_content", block)
    state = new_state("run-1", "user-1", 5, "topic", time.monotonic() + 60)
    state["drafts"] = [draft(text="Safe first draft")]
    state["reviews"] = [review_dict(passed=False)]

    update = await content_nodes.refine_1_node(state)
    state.update(update)
    artifact = artifact_of(state)

    assert state["refinement_count"] == 1
    assert len(artifact.attempts) == 2
    assert artifact.attempts[0].refined is None
    assert artifact.attempts[1].content_withheld is True
    assert artifact.attempts[1].draft is None
    assert artifact.provenance.logical_llm_calls == 1


async def test_a_tagger_failure_does_not_publish_an_untagged_approval(monkeypatch):
    state, _ = await run_pipeline(
        monkeypatch, verdicts=[True], tagger=FakeTagger(error=RuntimeError("boom"))
    )

    assert state["failure_stage"] == "tagger_error"
    artifact = artifact_of(state)
    assert artifact.final.status == "rejected"
    assert artifact.final.pipeline_status == "tagger_error"
    assert artifact.final.tags is None


async def test_blocked_topic_never_reaches_the_generator(monkeypatch):
    from app.core.exceptions import ModerationBlocked

    async def block(*_args, **_kwargs):
        raise ModerationBlocked("topic")

    generator = FakeGenerator()
    monkeypatch.setattr(content_nodes, "_generator", generator)
    monkeypatch.setattr(content_nodes, "moderate_topic", block)

    state = await compiled_graph.ainvoke(
        new_state("run-1", "user-1", 5, "how to make a bomb", time.monotonic() + 60)
    )

    assert generator.calls == 0
    assert state["failure_stage"] == "moderation_blocked"


async def test_the_artifact_holds_the_complete_ordered_trail(monkeypatch):
    state, _ = await run_pipeline(monkeypatch, verdicts=[False, False, True])
    artifact = artifact_of(state)

    assert [a.attempt for a in artifact.attempts] == [1, 2, 3]
    texts = [a.draft.explanation.text for a in artifact.attempts]
    assert texts == ["Draft 1", "Draft 2", "Draft 3"]
    assert [a.review.passed for a in artifact.attempts] == [False, False, True]
    assert artifact.provenance.refinement_count == 2
    assert artifact.timestamps.finished_at >= artifact.timestamps.started_at
