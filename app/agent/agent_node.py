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
    rag_index_node, # добавленный узел
    GraphState,
    route_classify,
    route_cache,
    route_critic,
    route_post_save,
)

from langgraph.graph import StateGraph, START, END

agent = StateGraph(GraphState)

agent.add_node("extract_transcript", extract_transcript)
agent.add_node("classify", classify_node)
agent.add_node("rag_index", rag_index_node) # добавленный узел
agent.add_node("reject", reject_node)
agent.add_node("summarize", summarize_node)
agent.add_node("keywords", keyword_node)
agent.add_node("merge", merge_node)       
agent.add_node("script", script_node)
agent.add_node("audio", audio_node)
agent.add_node("critic", critic_node)
agent.add_node("cache_node", cache_node)
agent.add_node("save_to_db", save_to_db_node)

# ── рёбра ─────────────────────────────────────────────────────────

agent.add_edge(START, "extract_transcript")

# Запускаем классификацию и индексацию параллельно
agent.add_edge("extract_transcript", "classify")
agent.add_edge("extract_transcript", "rag_index")

# Ветка индексации заканчивается здесь
agent.add_edge("rag_index", END)

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
        "end": END,
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

agent.add_conditional_edges(
    "save_to_db",
    route_post_save,
    {
        "audio": "audio",
        "end": END,
    }
)

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
        "is_suitable": False,
        "cache_hit": False,       
        "agent_execution_order": [],
        "skip_audio": True,
    }
    final_state = app.invoke(data)
    print("--- ГОТОВО! ---")
    print(f"Статус RAG: {final_state.get('vector_index_status')}")
    if not data["skip_audio"]:
        print("Проверь файл podcast.mp3")
    else:
        print("Текст сохранён в БД. Для аудио запусти generate_audio() или установи skip_audio=False.")