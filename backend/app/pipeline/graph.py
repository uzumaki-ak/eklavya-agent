"""LangGraph wiring — the Reflection pattern, unrolled.

  moderate ─► generate ─► review_1 ─┬─ pass ─────────────────► tag ─► END
                                    └─ fail ─► refine_1 ─► review_2 ─┬─ pass ─► tag
                                                                     └─ fail ─►
              refine_2 ─► review_3 ─┬─ pass ─► tag ─► END
                                    └─ fail ─────────► END   (rejected)

The two-refinement cap is structural, not counted. There are exactly two refine
nodes, `refine_2` is reachable only from `review_2`, and `review_3` has no edge
to any refinement — so a third refinement is not something the graph can express,
regardless of what any counter says. Unrolling rather than looping is what buys
that: a cyclic graph would push the guarantee into a comparison someone can get
wrong later.

`tag` is reachable only from a passing review, which is how "classify approved
content only" is enforced.
"""

from langgraph.graph import END, StateGraph

from app.pipeline.nodes import (
    generate_node,
    moderate_topic_node,
    refine_1_node,
    refine_2_node,
    review_node,
    tag_node,
)
from app.pipeline.state import AgentState, latest_review


def _continue_unless_failed(next_node: str):
    def route(state: AgentState) -> str:
        return END if state.get("failure_stage") else next_node

    return route


def _after_review(on_fail: str | None):
    """Route a verdict: approved content goes to tagging, a failure to the next
    refinement — or to END when the refinement budget is spent."""

    def route(state: AgentState) -> str:
        if state.get("failure_stage"):
            return END
        review = latest_review(state) or {}
        # Stored under the spec's alias, and already enforced against the
        # documented thresholds before it was written.
        if review.get("pass") is True:
            return "tag"
        return END if on_fail is None else on_fail

    return route


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("moderate_topic", moderate_topic_node)
    graph.add_node("generate", generate_node)
    # One implementation, three positions. The node cannot tell which it is,
    # so it cannot decide its own successor.
    graph.add_node("review_1", review_node)
    graph.add_node("refine_1", refine_1_node)
    graph.add_node("review_2", review_node)
    graph.add_node("refine_2", refine_2_node)
    graph.add_node("review_3", review_node)
    graph.add_node("tag", tag_node)

    graph.set_entry_point("moderate_topic")
    graph.add_conditional_edges(
        "moderate_topic", _continue_unless_failed("generate"), {END: END, "generate": "generate"}
    )
    graph.add_conditional_edges(
        "generate", _continue_unless_failed("review_1"), {END: END, "review_1": "review_1"}
    )
    graph.add_conditional_edges(
        "review_1", _after_review("refine_1"), {END: END, "tag": "tag", "refine_1": "refine_1"}
    )
    graph.add_conditional_edges(
        "refine_1", _continue_unless_failed("review_2"), {END: END, "review_2": "review_2"}
    )
    graph.add_conditional_edges(
        "review_2", _after_review("refine_2"), {END: END, "tag": "tag", "refine_2": "refine_2"}
    )
    graph.add_conditional_edges(
        "refine_2", _continue_unless_failed("review_3"), {END: END, "review_3": "review_3"}
    )
    # No refinement left to offer: a failure here is the rejected outcome.
    graph.add_conditional_edges("review_3", _after_review(None), {END: END, "tag": "tag"})
    graph.add_edge("tag", END)

    return graph.compile()


compiled_graph = build_graph()
