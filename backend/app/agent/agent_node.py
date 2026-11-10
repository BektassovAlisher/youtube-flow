"""LangGraph pipeline for one video.

START → load → transcript → classify ─┬─▶ reject → END
                                      └─▶ start_pipeline ─┬─▶ summarize → keywords → END
                                                          └─▶ index → END

Nodes persist their output and skip saved work, so the same graph resumes an interrupted run.

The podcast script is a second graph, started by a button once the summary is there:

START → script ⇄ critic → save_script → END"""
import time

from langgraph.graph import END, START, StateGraph

from agent.agent import (
    GraphState, _emit, classify_node, critic_node, index_node, keywords_node, load_node, reject_node,
    route_classify, route_critic, save_script_node, script_node, start_pipeline_node, summarize_node, transcript_node,
)



def timed(name: str, node):
    """Reports how long a step took (a "timing" event). Steps that find their work already saved return
    nothing and are not counted."""
    def run(state):
        started = time.monotonic()
        out = node(state)
        if out:
            _emit(timing={name: round(time.monotonic() - started, 2)})
        return out

    run.__name__ = name
    return run


graph = StateGraph(GraphState)
graph.add_node("load", load_node)
graph.add_node("reject", reject_node)
graph.add_node("start_pipeline", start_pipeline_node)
for _name, _node in (("transcript", transcript_node), ("classify", classify_node), ("summarize", summarize_node),
                     ("index", index_node), ("keywords", keywords_node)):
    graph.add_node(_name, timed(_name, _node))

graph.add_edge(START, "load")
graph.add_edge("load", "transcript")
graph.add_edge("transcript", "classify")
graph.add_conditional_edges("classify", route_classify, {"start_pipeline": "start_pipeline", "reject": "reject"})
graph.add_edge("reject", END)
graph.add_edge("start_pipeline", "summarize")
graph.add_edge("start_pipeline", "index")
graph.add_edge("index", END)
graph.add_edge("summarize", "keywords")
graph.add_edge("keywords", END)

app = graph.compile()

script_graph = StateGraph(GraphState)
script_graph.add_node("script", timed("script", script_node))
script_graph.add_node("critic", timed("critic", critic_node))
script_graph.add_node("save_script", save_script_node)
script_graph.add_edge(START, "script")
script_graph.add_edge("script", "critic")
script_graph.add_conditional_edges("critic", route_critic, {"script": "script", "save_script": "save_script"})
script_graph.add_edge("save_script", END)

script_app = script_graph.compile()


def initial_state(video_id: str, force: bool = False) -> dict:
    return {"video_id": video_id, "force": force, "agent_execution_order": []}


def script_state(video: dict) -> dict:
    return {"video_id": video["video_id"], "summary": video["summary"], "keywords": video.get("keywords") or [],
            "retry_count": 0, "max_retries": 2, "agent_execution_order": []}
