"""LangGraph wiring — the Reflection pattern.

  moderate_topic -> generate -> review -> [pass: END | fail: refine -> review_refined -> END]

The one-refinement cap is enforced structurally: refine_node is only reachable from
review_original, and review_refined always routes to END. There is no edge back.
"""

from langgraph.graph import END, StateGraph

from app.pipeline.nodes import (
    generate_original_node,
    moderate_topic_node,
    refine_node,
    review_original_node,
    review_refined_node,
)
from app.pipeline.state import AgentState


def _after_moderation(state: AgentState) -> str:
    return END if state.get("failure_stage") else "generate_original"


def _after_generate(state: AgentState) -> str:
    return END if state.get("failure_stage") else "review_original"


def _after_review(state: AgentState) -> str:
    """Route to the single refinement pass, or end."""
    if state.get("failure_stage"):
        return END
    review = state.get("initial_review") or {}
    if review.get("status") == "fail" and state.get("refinement_count", 0) == 0:
        return "refine"
    return END


def _after_refine(state: AgentState) -> str:
    return END if state.get("failure_stage") else "review_refined"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("moderate_topic", moderate_topic_node)
    graph.add_node("generate_original", generate_original_node)
    graph.add_node("review_original", review_original_node)
    graph.add_node("refine", refine_node)
    graph.add_node("review_refined", review_refined_node)

    graph.set_entry_point("moderate_topic")
    graph.add_conditional_edges("moderate_topic", _after_moderation, {END: END, "generate_original": "generate_original"})
    graph.add_conditional_edges("generate_original", _after_generate, {END: END, "review_original": "review_original"})
    graph.add_conditional_edges("review_original", _after_review, {END: END, "refine": "refine"})
    graph.add_conditional_edges("refine", _after_refine, {END: END, "review_refined": "review_refined"})
    graph.add_edge("review_refined", END)  # terminal regardless of verdict

    return graph.compile()


compiled_graph = build_graph()
