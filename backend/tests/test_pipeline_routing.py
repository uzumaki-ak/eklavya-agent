"""Graph routing — the assessment's hard rules, checked without an API key.

Two kinds of assertion here. The routing functions are tested directly, and the
*shape* of the compiled graph is tested too, because that shape is where the
two-refinement cap actually lives: there are exactly two refine nodes and nothing
routes back into one. A counter can be got wrong; a missing edge cannot.
"""

from langgraph.graph import END

from app.pipeline.graph import _after_review, _continue_unless_failed, compiled_graph
from tests.factories import review_dict


def _state(**overrides) -> dict:
    base = {"drafts": [], "reviews": [], "tags": None, "failure_stage": None}
    return {**base, **overrides}


# --- routing functions -----------------------------------------------------


def test_moderation_block_ends_pipeline():
    route = _continue_unless_failed("generate")
    assert route(_state(failure_stage="moderation_blocked")) == END


def test_moderation_error_ends_pipeline():
    # Distinct from a block, but still terminal — never generates anyway.
    route = _continue_unless_failed("generate")
    assert route(_state(failure_stage="moderation_error")) == END


def test_clean_topic_proceeds_to_generation():
    assert _continue_unless_failed("generate")(_state()) == "generate"


def test_generator_failure_ends_pipeline():
    route = _continue_unless_failed("review_1")
    assert route(_state(failure_stage="generator_error")) == END


def test_passing_review_routes_to_tagging():
    state = _state(drafts=[{}], reviews=[review_dict(passed=True)])
    assert _after_review("refine_1")(state) == "tag"


def test_failing_review_routes_to_the_next_refinement():
    state = _state(drafts=[{}], reviews=[review_dict(passed=False)])
    assert _after_review("refine_1")(state) == "refine_1"


def test_second_failure_routes_to_the_second_refinement():
    state = _state(drafts=[{}, {}], reviews=[review_dict(passed=False)] * 2)
    assert _after_review("refine_2")(state) == "refine_2"


def test_third_failure_is_terminal():
    """No refinement is offered after the budget is spent — this is the rejection."""
    state = _state(drafts=[{}] * 3, reviews=[review_dict(passed=False)] * 3)
    assert _after_review(None)(state) == END


def test_a_pass_on_the_third_review_still_tags():
    state = _state(drafts=[{}] * 3, reviews=[review_dict(passed=False)] * 2 + [review_dict()])
    assert _after_review(None)(state) == "tag"


def test_reviewer_error_does_not_trigger_refinement():
    # A broken reviewer is a technical failure, not a "fail" verdict —
    # refining on it would be acting on feedback that does not exist.
    state = _state(drafts=[{}], failure_stage="reviewer_error")
    assert _after_review("refine_1")(state) == END


def test_tagger_failure_ends_the_pipeline():
    route = _continue_unless_failed("review_2")
    assert route(_state(failure_stage="tagger_error")) == END


# --- graph shape -----------------------------------------------------------


def _edges() -> set[tuple[str, str]]:
    graph = compiled_graph.get_graph()
    return {(edge.source, edge.target) for edge in graph.edges}


def _nodes() -> set[str]:
    return set(compiled_graph.get_graph().nodes)


def test_there_are_exactly_two_refinement_nodes():
    """The cap is a property of the graph, not of a counter."""
    assert {node for node in _nodes() if node.startswith("refine")} == {
        "refine_1",
        "refine_2",
    }


def test_no_edge_leads_back_into_a_refinement_from_the_last_review():
    outgoing = {target for source, target in _edges() if source == "review_3"}
    assert not any(target.startswith("refine") for target in outgoing)


def test_the_second_refinement_is_only_reachable_from_the_second_review():
    incoming = {source for source, target in _edges() if target == "refine_2"}
    assert incoming == {"review_2"}


def test_tagging_is_only_reachable_from_a_review():
    """"Classify approved content only" — enforced by which edges exist."""
    incoming = {source for source, target in _edges() if target == "tag"}
    assert incoming == {"review_1", "review_2", "review_3"}


def test_the_graph_is_acyclic_over_its_content_stages():
    order = ["generate", "review_1", "refine_1", "review_2", "refine_2", "review_3"]
    rank = {name: index for index, name in enumerate(order)}
    for source, target in _edges():
        if source in rank and target in rank:
            assert rank[source] < rank[target], f"{source} -> {target} goes backwards"
