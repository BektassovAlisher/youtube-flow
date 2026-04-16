from agent.agent import (
    extract_transcript, 
    classify_node, 
    reject_node, 
    summarize_node,
    keyword_node, 
    merge_node, 
    script_node, 
    critic_node,
    audio_node, 
    cache_node, 
    save_to_db_node,
    GraphState,
    route_classify,
    route_cache,
    route_critic
)

from langgraph.graph import StateGraph, START, END

agent = StateGraph(GraphState)

agent.add_node("extract_transcript", extract_transcript)
agent.add_node("classify", classify_node)
agent.add_node("reject", reject_node)
agent.add_node("summarize", summarize_node)
agent.add_node("keywords", keyword_node)
agent.add_node("merge", merge_node)       
agent.add_node("script", script_node)
agent.add_node("audio", audio_node)
agent.add_node("critic", critic_node)
agent.add_node("cache_node", cache_node)
agent.add_node("save_to_db", save_to_db_node)

agent.add_edge(START, "extract_transcript")
agent.add_edge("extract_transcript", "classify")

agent.add_conditional_edges(
    "classify",
    route_classify,
    {
        "cache_node": "cache_node",
        "reject": "reject"
    }
)

agent.add_edge("reject", END)

agent.add_conditional_edges(
    "cache_node",
    route_cache,
    {
        "audio": "audio",
        "summarize": "summarize",
        "keywords": "keywords",
    }
)

agent.add_edge("summarize", "merge")      
agent.add_edge("keywords", "merge")        
agent.add_edge("merge", "script")          
agent.add_edge("script", "critic")

agent.add_conditional_edges(
    "critic",
    route_critic,
    {
        "audio": "save_to_db",   
        "script": "script" 
    }
)

agent.add_edge("save_to_db", "audio")
agent.add_edge("audio", END)

app = agent.compile()

if __name__ == "__main__":
    print("🚀 Запуск мультиагентной системы...")
    data = {
        "video_url": "https://www.youtube.com/watch?v=22tkx79icy4",
        "retry_count": 0,       
        "max_retries": 2,       
        "critic_feedback": "",   
        "is_valid": False,
        "cache_hit": False,       
        "agent_execution_order": []  
    }
    final_state = app.invoke(data)
    print("--- ГОТОВО! Проверь файл podcast.mp3 ---")