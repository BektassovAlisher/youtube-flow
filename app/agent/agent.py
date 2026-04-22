from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from typing import TypedDict, List, Annotated
import json
from tools.youtube_scraper import YoutubeExtractTool
from tools.chunking_transcript import ChukingTranscript
from tools.audio_generator import AudioGeneratorTool
from dotenv import load_dotenv
import os
import operator
from db.database import init_db
from db.cache import get_cached_video, save_to_cache, get_cached_audio, save_audio_to_cache
from db.chroma.vectore_store import rag_store
from agent.agent_state import GraphState, extract_text, llm, llm2

init_db()


def extract_transcript(state: GraphState):
    extractor = YoutubeExtractTool()
    chunking = ChukingTranscript()
    text = extractor.process_video(state["video_url"])
    splitted_text = chunking.to_timestamped_text(text.segments)
    return {"transcript": splitted_text,
            "video_metadata": text.metadata,
            "segments": text.segments
            }
    

def classify_node(state: GraphState):
    print("🔍 Агент 1: Классифицирую видео...")
    
    transcript = state["transcript"]
    metadata = state["video_metadata"]
    
    prompt = f"""Ты — классификатор видео-контента.

Перед тобой транскрипт видео и метаданные.

---МЕТАДАННЫЕ---
Название: {metadata.get("title", "Неизвестно")}
---ТРАНСКРИПТ (первые 2000 символов)---
{transcript[:2000]}
---КОНЕЦ---

Определи тип видео. Верни ТОЛЬКО валидный JSON:
{{
    "category": "educational" | "entertainment" | "news" | "random" | "music" | "gaming",
    "is_suitable": true/false,
    "confidence": 0.0-1.0,
    "reason": "краткое объяснение"
}}

is_suitable = true ТОЛЬКО если это обучающий/образовательный контент (лекция, туториал, курс, объяснение концепций).
Без markdown, без ```json.
"""
    
    result = llm2.invoke(prompt)
    raw = extract_text(result).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    
    try:
        classification = json.loads(raw)
    except:
        classification = {"category": "unknown", "is_suitable": True, "confidence": 0.5, "reason": "parse error"}
    
    print(f"📊 Категория: {classification['category']} | Подходит: {classification['is_suitable']} | Уверенность: {classification['confidence']}")
    
    return {
        "video_category": classification["category"],
        "is_suitable": classification["is_suitable"],
        "classification_confidence": classification["confidence"],
        "classification_reason": classification["reason"],
        "agent_execution_order": ["classify"]
    }


def route_classify(state: GraphState):
    if state.get("is_suitable") and state.get("classification_confidence", 1.0) >= 0.6:
        return "cache_node"
    else:
        return "reject"

def reject_node(state: GraphState):
    reason = state.get("classification_reason", "")
    category = state.get("video_category", "unknown")
    print(f"🚫 Видео отклонено. Категория: {category}. Причина: {reason}")
    return {
        "summary": f"❌ Видео не подходит для обработки.\nКатегория: {category}\nПричина: {reason}\n\nПожалуйста, выберите образовательное видео (лекция, туториал, курс).",
        "audio_path": "rejected",
        "agent_execution_order": ["reject"]
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
    video_id = state["video_metadata"]["video_id"]
    output_path = "podcast.mp3"

    cached_audio = get_cached_audio(video_id)
    if cached_audio:
        print(f"💾 Аудио найдено в БД, пропускаю генерацию: {video_id}")
        with open(output_path, "wb") as f:
            f.write(cached_audio)
        print(f"✅ Аудио восстановлено из БД: {output_path}")
        return {"audio_path": output_path}

    print("🎙️ Агент 5: Генерирую аудио через ElevenLabs...")
    audio_tool = AudioGeneratorTool()
    try:
        path = audio_tool.generate_podcast_audio(
            script=state["podcast_script"],
            language=state["video_metadata"]["language"],
            output_path=output_path,
        )
        with open(path, "rb") as f:
            audio_bytes = f.read()
        save_audio_to_cache(video_id, audio_bytes)
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
        category=state.get("video_category", "unknown"),
    )
    return {}


def route_cache(state: GraphState):
    if state.get("cache_hit"):
        if state.get("skip_audio"):
            return ["end"]
        return ["audio"]
    return ["summarize", "keywords"]


def route_post_save(state: GraphState):
    if state.get("skip_audio"):
        print("⏭️  Пропускаем генерацию аудио (skip_audio=True). Граф завершён.")
        return "end"
    return "audio"


def rag_index_node(state: GraphState):
    """Агент индексации: разбивает транскрипт на чанки и сохраняет в векторную БД."""
    print("🧠 Агент RAG: Индексирую транскрипт...")
    
    segments = state.get("segments", [])
    video_id = state["video_metadata"]["video_id"]
    
    if not segments:
        return {"vector_index_status": "skipped (no segments)"}
        
    chunker = ChukingTranscript()
    chunks = chunker.split(segments, video_id)
    
    rag_store.add_documents(chunks, video_id)
    
    return {"vector_index_status": f"indexed_{len(chunks)}_chunks"}


def qa_agent(video_id: str, question: str):
    """Утилита для QA по видео."""
    # 1. Поиск релевантных чанков
    docs = rag_store.search(question, video_id, k=5)
    
    context_parts = []
    sources = []
    for d in docs:
        ts = d.metadata.get("timestamp", "00:00")
        url = d.metadata.get("youtube_url", "")
        context_parts.append(f"[{ts}] {d.page_content}")
        sources.append({"timestamp": ts, "url": url})
        
    context = "\n\n".join(context_parts)
    
    prompt = f"""Ты — ассистент по вопросам к видео-лекциям. 
Используй предоставленный контекст из транскрипта, чтобы ответить на вопрос.

---КОНТЕКСТ---
{context}
---КОНЕЦ КОНТЕКСТА---

Вопрос: {question}

Если в контексте нет ответа, так и скажи. Не придумывай факты.
Отвечай на языке вопроса.
В конце ответа добавь ссылки на таймстампы из контекста, если они помогли ответить.
"""

    result = llm.invoke(prompt)
    return {
        "answer": extract_text(result),
        "sources": sources
    }
