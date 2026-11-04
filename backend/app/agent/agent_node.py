"""LangGraph pipeline for one video.

START → load → transcript → classify ─┬─▶ reject → END
                                      └─▶ start_pipeline ─┬─▶ summarize → keywords ─┬─▶ END (script exists)
                                                          │                         └─▶ script ⇄ critic → save_script → END
                                                          └─▶ index → END

Nodes persist their output and skip saved work, so the same graph resumes an interrupted run."""
from langgraph.graph import END, START, StateGraph

from agent.agent import (
    GraphState, classify_node, critic_node, index_node, keywords_node, load_node, reject_node, route_after_keywords,
    route_classify, route_critic, save_script_node, script_node, start_pipeline_node, summarize_node, transcript_node,
)

graph = StateGraph(GraphState)
graph.add_node("load", load_node)
graph.add_node("transcript", transcript_node)
graph.add_node("classify", classify_node)
graph.add_node("reject", reject_node)
graph.add_node("start_pipeline", start_pipeline_node)
graph.add_node("summarize", summarize_node)
graph.add_node("index", index_node)
graph.add_node("keywords", keywords_node)
graph.add_node("script", script_node)
graph.add_node("critic", critic_node)
graph.add_node("save_script", save_script_node)

graph.add_edge(START, "load")
graph.add_edge("load", "transcript")
graph.add_edge("transcript", "classify")
graph.add_conditional_edges("classify", route_classify, {"start_pipeline": "start_pipeline", "reject": "reject"})
graph.add_edge("reject", END)
graph.add_edge("start_pipeline", "summarize")
graph.add_edge("start_pipeline", "index")
graph.add_edge("index", END)
graph.add_edge("summarize", "keywords")
graph.add_conditional_edges("keywords", route_after_keywords, {"script": "script", "end": END})
graph.add_edge("script", "critic")
graph.add_conditional_edges("critic", route_critic, {"script": "script", "save_script": "save_script"})
graph.add_edge("save_script", END)

app = graph.compile()


def initial_state(video_id: str, force: bool = False) -> dict:
    return {"video_id": video_id, "force": force, "retry_count": 0, "max_retries": 2, "agent_execution_order": []}
