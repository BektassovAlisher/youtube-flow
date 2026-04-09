from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langgraph.graph import START, END, StateGraph
from typing import TypedDict, List, Annotated
import json
from tools.youtube_scraper import YoutubeExtractTool
from tools.chunking_transcript import ChukingTranscript
from tools.audio_generator import AudioGeneratorTool
from dotenv import load_dotenv
import os
import operator
from db.database import init_db
from db.cache import get_cached_video, save_to_cache

init_db()

load_dotenv()

GOOGLE_API = os.getenv("GOOGLE_API_KEY")
llm = ChatGoogleGenerativeAI(model="gemini-3-flash-preview", api_key=GOOGLE_API)
llm2 = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY"))

class GraphState(TypedDict):
    video_url: str
    transcript: str        
    video_metadata: dict
    summary: str
    keywords: List[str]
    podcast_script: str
    audio_path: str
    agent_execution_order: Annotated[List[str], operator.add]
    retry_count: int       
    critic_feedback: str    
    max_retries: int    
    is_valid: bool
    cache_hit: bool

def extract_text(result) -> str:
    if isinstance (result.content, list):
        return result.content[0]["text"]
    return result.content


def extract_transcript(state: GraphState):
    extractor = YoutubeExtractTool()
    chunking = ChukingTranscript()
    text = extractor.process_video(state["video_url"])
    splitted_text = chunking.to_timestamped_text(text.segments)
    return {"transcript": splitted_text,
            "video_metadata": text.metadata
            }
    
def summarize_node(state: GraphState):
    print("📝 Агент 2: Пишу конспект...")
    
    transcript = state["transcript"]
    language = state["video_metadata"]["language"]

    prompt = f"""Ты — эксперт по составлению учебных конспектов.

Перед тобой транскрипт лекции с временными метками в формате [MM:SS].

---ТРАНСКРИПТ---
{transcript}
---КОНЕЦ---

Составь структурированный конспект. Используй временные метки из транскрипта.

Формат:

## Обзор лекции
3-5 предложений о чём вся лекция.

## [MM:SS] Название раздела
**Краткое содержание:** 2-3 предложения.

**Ключевые понятия:**
- **Термин**: определение

**Важные моменты:**
- факт или идея

---

Правила:
- Отвечай строго на языке указанном в транскрипте: {language}
- Указывай реальные таймстампы из транскрипта у каждого раздела
- Выделяй жирным технические термины
- В конце добавь раздел "## Все ключевые понятия" — сводный список всех терминов

"""

    result = llm.invoke(prompt)
    print("✅ Конспект готов")
    print(extract_text(result))
    return {
        "summary": extract_text(result),
        "agent_execution_order" : ["summary"]
        }



def keyword_node(state:GraphState):

    trasnscript = state["transcript"]
    language = state["video_metadata"]["language"]
    prompt = f"""Ты — эксперт по анализу образовательного контента.

Перед тобой конспект лекции.

---КОНСПЕКТ---
{trasnscript}
---КОНЕЦ---

Твоя задача — извлечь ключевые термины и понятия из этого конспекта.

Правила:
- Извлеки 10-15 самых важных терминов
- Только технические термины и ключевые понятия — не общие слова
- Верни ТОЛЬКО валидный JSON массив строк
- Без пояснений, без markdown, без ```json
- Пример формата: ["термин1", "термин2", "термин3"]

Термины должны быть:
- Конкретными (не "метод" а "градиентный спуск")
- На языке конспекта
- Отсортированы по важности — самые главные первыми
- Отвечай строго на языке указанном в транскрипте: {language}
"""
    


    result = llm2.invoke(prompt)
    raw = extract_text(result).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    keywords = json.loads(raw)
    print(f"✅ Ключевые слова: {keywords}")
    return {"keywords": keywords,
            "agent_execution_order" : ["keywords"]
            }


characters = {
    "ru": ("Алекс", "Марина"),
    "en": ("Alex", "Marina"),
}

def script_node(state: GraphState):
    print("🎙️ Агент 4: Пишу сценарий подкаста...")

    summary = state["summary"]
    keywords = ", ".join(state["keywords"])
    language = state["video_metadata"]["language"]

    if "retry_count" not in state:
        state["retry_count"] = 0

    host1, host2 = characters.get(language, ("Alex", "Marina"))
    prompt = f"""Ты — сценарист образовательного подкаста.

Перед тобой конспект лекции и ключевые термины.

---КОНСПЕКТ---
{summary}
---КОНЕЦ---

Ключевые термины которые нужно упомянуть: {keywords}

Напиши диалог между двумя ведущими подкаста:
- Алекс — новичок, задаёт простые вопросы, удивляется
- Марина — эксперт, объясняет понятно и с примерами

Структура диалога:
1. Вступление — о чём будет выпуск (2 реплики)
2. Основная часть — разбор главных идей (6-8 реплик)
3. Заключение — главный вывод и зачем это знать (2 реплики)

Правила:
- Строго в формате "Имя: текст" каждая реплика с новой строки
- Каждая реплика 1-3 предложения — не длиннее
- Упомяни минимум 5 терминов из списка ключевых
- Объясняй термины простыми словами через реплики Марины
- Пиши на языке конспекта
- Без ремарок, без описаний действий, только диалог
- Отвечай строго на языке указанном в транскрипте: {language}

Пример формата:
{host1}
{host2}
"""
    
    if state.get("critic_feedback") and state.get("retry_count", 0) > 0:
        prompt += f"""
        \n\nВНИМАНИЕ! Прошлая версия сценария была отклонена редактором.
        Комментарий редактора: {state['critic_feedback']}
        
        Пожалуйста, исправь ошибки и напиши сценарий заново, учитывая этот комментарий.
        """

    result = llm.invoke(prompt)
    print("✅ Сценарий готов")
    print(extract_text(result))
    return {"podcast_script": extract_text(result)}  

def critic_node(state:GraphState):
    script = state.get("podcast_script", "")
    keywords = state.get("keywords", [])
    retry_count = state.get("retry_count", 0)
    language = state["video_metadata"]["language"]

    prompt = f"""Ты — строгий редактор подкаста. Твоя задача проверить сценарий.
    
    Сценарий:
    {script}
    
    Обязательные ключевые слова (нужно использовать минимум 5): 
    {', '.join(keywords)}

    Проверь сценарий по двум критериям:
    1. Формат строго "Имя: текст" в каждой строке диалога. Нет ли лишних описаний действий?
    2. Использовано ли как минимум 5 ключевых слов из списка?
    3. Посчитай сколько именно ключевых слов найдено в тексте. 
    4. Если меньше 5 — is_valid: false обязательно.

    Верни ТОЛЬКО валидный JSON в формате:
    {{
        "is_valid": true/false,
        "feedback": "Если false, напиши что исправить. Если true, напиши 'Одобрено'"
    }}
    Отвечай строго на языке: {language} (для фидбека).
    """

    result = llm2.invoke(prompt)
    raw = extract_text(result).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        critic_result = json.loads(raw)
    
    except Exception as e:
        critic_result = {"is_valid": True, "feedback": "JSON parse error, пропускаем."}
    
    print(f"  📝 Вердикт критика: {critic_result['is_valid']} | Фидбек: {critic_result['feedback']}")

    return {
        "critic_feedback" : critic_result["feedback"],
        "retry_count": retry_count + 1,
        "is_valid": critic_result["is_valid"]
    }


def route_critic(state: GraphState):
    is_valid = state.get("is_valid", False)
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 2)

    if is_valid:
        return "audio"
    
    if retry_count >= max_retries:
        return "audio"
    
    else:
        return "script"


def audio_node(state: GraphState):
    print("🎙️ Агент 5: Генерирую аудио через ElevenLabs...")

    audio_tool = AudioGeneratorTool()
    try:
        path = audio_tool.generate_podcast_audio(
            script=state["podcast_script"],
            language=state["video_metadata"]["language"]
        )
        return {"audio_path": path}
    except Exception as e:
        print(f"🚨 Ошибка в audio_node: {e}")
        return {"audio_path": "error"}

def merge_node(state: GraphState):
    return {}

def cache_node(state:GraphState):
    video_id = state["video_metadata"]["video_id"]
    cached= get_cached_video(video_id)

    if cached:
        print(f"💾 Найдено в кэше: {video_id}")
        return {
            "summary" : cached["summary"],
            "keywords" : cached["keywords"],
            "podcast_script": cached["podcast_script"],
            "cache_hit": True,
        }

    print(f"🔍 Не найдено в кэше: {video_id}")
    return {"cache_hit": False}


def save_to_db_node(state: GraphState):
    meta = state["video_metadata"]
    save_to_cache(
        video_id=meta["video_id"],
        url=meta["video_url"],
        language=meta["language"],
        duration_sec=meta["total_duration_sec"],
        summary=state["summary"],
        keywords=state["keywords"],
        script=state["podcast_script"],
    )
    return {}


def route_cache(state: GraphState):
    if state.get("cache_hit"):
        return ["audio"]
    return ["summarize", "keywords"]



agent = StateGraph(GraphState)

agent.add_node("extract_transcript", extract_transcript)
agent.add_node("summarize", summarize_node)
agent.add_node("keywords", keyword_node)
agent.add_node("merge", merge_node)       
agent.add_node("script", script_node)
agent.add_node("audio", audio_node)
agent.add_node("critic", critic_node)
agent.add_node("cache_node", cache_node)
agent.add_node("save_to_db", save_to_db_node)

agent.add_edge(START, "extract_transcript")
agent.add_edge("extract_transcript", "cache_node")

agent.add_conditional_edges(
    "cache_node",
    route_cache,
    {
        "audio": "audio",
        "summarize": "summarize",
        "keywords": "keywords",
    }
)

# Если кэш не найден — идём через генерацию
agent.add_edge("summarize", "merge")      
agent.add_edge("keywords", "merge")        
agent.add_edge("merge", "script")          
agent.add_edge("script", "critic")

agent.add_conditional_edges(
    "critic",
    route_critic,
    {
        "audio": "save_to_db",   # сначала сохраняем в БД
        "script" : "script" 
    }
)

agent.add_edge("save_to_db", "audio")
agent.add_edge("audio", END)
app = agent.compile()

if __name__ == "__main__":
    print("🚀 Запуск мультиагентной системы...")
    data = {
        "video_url": "https://www.youtube.com/watch?v=jdknLDkBS3k",
        "retry_count": 0,       
        "max_retries": 2,       
        "critic_feedback": "",   
        "is_valid": False,
        "cache_hit": False,       
        "agent_execution_order": []  
    }
    final_state = app.invoke(data)
    print("--- ГОТОВО! Проверь файл podcast.mp3 ---")