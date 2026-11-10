"""LangGraph pipeline for one video.

START → load → transcript ─┬─▶ classify ──┬─▶ gate ─┬─▶ reject → END
                           ├─▶ summarize ─┘         └─▶ keywords ─┬─▶ END (script exists)
                           │                                      └─▶ script ⇄ critic → save_script → END
                           └─▶ index → END

The check runs alongside the summary, so it does not delay the first words: the gate waits for both and stops
the run there when the material is not educational (the summary stays saved, so "process anyway" goes on from it).

Nodes persist their output and skip saved work, so the same graph resumes an interrupted run."""
import time

from langgraph.graph import END, START, StateGraph

from agent.agent import (
    GraphState, _emit, classify_node, critic_node, index_node, keywords_node, load_node, reject_node, route_after_keywords,
    route_classify, route_critic, save_script_node, script_node, gate_node, summarize_node, transcript_node,
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
graph.add_node("gate", gate_node)
graph.add_node("save_script", save_script_node)
for _name, _node in (("transcript", transcript_node), ("classify", classify_node), ("summarize", summarize_node),
                     ("index", index_node), ("keywords", keywords_node), ("script", script_node), ("critic", critic_node)):
    graph.add_node(_name, timed(_name, _node))

graph.add_edge(START, "load")
graph.add_edge("load", "transcript")
graph.add_edge("transcript", "classify")
graph.add_edge("transcript", "summarize")
graph.add_edge("transcript", "index")
graph.add_edge("index", END)
graph.add_edge(["classify", "summarize"], "gate")  # waits for both
graph.add_conditional_edges("gate", route_classify, {"keywords": "keywords", "reject": "reject"})
graph.add_edge("reject", END)
graph.add_conditional_edges("keywords", route_after_keywords, {"script": "script", "end": END})
graph.add_edge("script", "critic")
graph.add_conditional_edges("critic", route_critic, {"script": "script", "save_script": "save_script"})
graph.add_edge("save_script", END)

app = graph.compile()


def initial_state(video_id: str, force: bool = False) -> dict:
    return {"video_id": video_id, "force": force, "retry_count": 0, "max_retries": 2, "agent_execution_order": []}
