from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List, Optional
from agent.agent_node import app as agent_app
from agent.agent import qa_agent, recommend_node
from db.cache import (
    get_cached_video, get_cached_audio, delete_cache, delete_expired_cache,
    save_audio_to_cache, get_cached_recommendation,
)
from db.database import SessionLocal, Video


app = FastAPI(
    title="VideoFlow API",
    description="API для генерации подкастов из YouTube-видео",
    version="1.0.0",
)


# ─── Request / Response models ───────────────────────────────────────────────

class GenerateRequest(BaseModel):
    video_url: str
    skip_audio: bool = False  # True → только текст, аудио можно сгенерировать позже


class GenerateResponse(BaseModel):
    video_id: str
    summary: str
    keywords: List[str]
    podcast_script: str
    audio_cached: bool
    cache_hit: bool
    rejected: bool
    skip_audio: bool = False
    video_category: Optional[str] = None
    classification_reason: Optional[str] = None
    recommendation: Optional[dict] = None


class QARequest(BaseModel):
    question: str


class QASource(BaseModel):
    timestamp: str
    url: str


class QAResponse(BaseModel):
    video_id: str
    answer: str
    sources: List[QASource]


class VideoInfo(BaseModel):
    video_id: str
    summary: str
    keywords: List[str]
    podcast_script: str
    language: str
    category: Optional[str] = None


class VideoListItem(BaseModel):
    video_id: str
    url: str
    language: str | None
    duration_sec: float | None
    category: str | None = None


class AudioGenerateResponse(BaseModel):
    video_id: str
    audio_path: str
    from_cache: bool


class RecommendResponse(BaseModel):
    video_id: str
    courses: List[dict]
    books: List[dict]
    from_cache: bool


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.post("/generate", response_model=GenerateResponse)
def generate_podcast(req: GenerateRequest):
    try:
        data = {
            "video_url": req.video_url,
            "retry_count": 0,
            "max_retries": 2,
            "critic_feedback": "",
            "is_valid": False,
            "is_suitable": False,
            "cache_hit": False,
            "agent_execution_order": [],
            "skip_audio": req.skip_audio,
        }

        result = agent_app.invoke(data)

        video_id = result["video_metadata"]["video_id"]
        rejected = result.get("audio_path") == "rejected"

        if rejected:
            return GenerateResponse(
                video_id=video_id,
                summary=result.get("summary", ""),
                keywords=[],
                podcast_script="",
                audio_cached=False,
                cache_hit=False,
                rejected=True,
                skip_audio=req.skip_audio,
                video_category=result.get("video_category"),
                classification_reason=result.get("classification_reason"),
            )

        cached_audio = get_cached_audio(video_id)

        return GenerateResponse(
            video_id=video_id,
            summary=result.get("summary", ""),
            keywords=result.get("keywords", []),
            podcast_script=result.get("podcast_script", ""),
            audio_cached=cached_audio is not None,
            cache_hit=result.get("cache_hit", False),
            rejected=False,
            skip_audio=req.skip_audio,
            video_category=result.get("video_category"),
            classification_reason=result.get("classification_reason"),
            recommendation=result.get("recommendation"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/videos/{video_id}/qa", response_model=QAResponse)
def ask_video_question(video_id: str, req: QARequest):
    """Ответ на вопросы по конкретному видео через RAG."""
    try:
        cached = get_cached_video(video_id)
        if not cached:
            raise HTTPException(status_code=404, detail="Видео не найдено. Сначала запустите /generate.")

        result = qa_agent(video_id, req.question)
        return QAResponse(
            video_id=video_id,
            answer=result["answer"],
            sources=result["sources"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/videos/{video_id}/recommend", response_model=RecommendResponse)
def get_recommendations(video_id: str):
    """Получает рекомендации курсов и книг для видео. Использует кэш если есть."""
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено. Сначала запустите /generate.")

    # Return from cache if already computed
    cached_rec = get_cached_recommendation(video_id)
    if cached_rec:
        return RecommendResponse(
            video_id=video_id,
            courses=cached_rec.get("courses", []),
            books=cached_rec.get("books", []),
            from_cache=True,
        )

    # Build a minimal state and call recommend_node directly
    state = {
        "video_metadata": {
            "video_id": video_id,
            "title": cached.get("title", f"Video {video_id}"),
            "language": cached.get("language", "en"),
        },
        "keywords": cached.get("keywords", []),
    }
    try:
        result = recommend_node(state)
        rec = result.get("recommendation", {"courses": [], "books": []})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка рекомендаций: {e}")

    return RecommendResponse(
        video_id=video_id,
        courses=rec.get("courses", []),
        books=rec.get("books", []),
        from_cache=False,
    )


@app.post("/videos/{video_id}/audio", response_model=AudioGenerateResponse)
def generate_audio_for_video(video_id: str):
    """Генерирует аудио для уже обработанного видео (скрипт должен быть в кэше)."""
    cached_audio = get_cached_audio(video_id)
    if cached_audio:
        output_path = f"{video_id}.mp3"
        with open(output_path, "wb") as f:
            f.write(cached_audio)
        return AudioGenerateResponse(video_id=video_id, audio_path=output_path, from_cache=True)

    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено в кэше. Сначала запустите /generate.")

    script = cached.get("podcast_script", "")
    language = cached.get("language", "ru")
    if not script:
        raise HTTPException(status_code=400, detail="Скрипт подкаста не найден.")

    try:
        from tools.audio_generator import AudioGeneratorTool
        audio_tool = AudioGeneratorTool()
        output_path = f"{video_id}.mp3"
        path = audio_tool.generate_podcast_audio(
            script=script,
            language=language,
            output_path=output_path,
        )
        with open(path, "rb") as f:
            audio_bytes = f.read()
        save_audio_to_cache(video_id, audio_bytes)
        return AudioGenerateResponse(video_id=video_id, audio_path=path, from_cache=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/videos", response_model=list[VideoListItem])
def list_videos():
    session = SessionLocal()
    try:
        videos = session.query(Video).all()
        return [
            VideoListItem(
                video_id=v.video_id,
                url=v.url,
                language=v.language,
                duration_sec=v.duration_sec,
                category=v.category,
            )
            for v in videos
        ]
    finally:
        session.close()


@app.get("/videos/{video_id}", response_model=VideoInfo)
def get_video(video_id: str):
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено в кэше")
    return VideoInfo(
        video_id=cached["video_id"],
        summary=cached["summary"],
        keywords=cached["keywords"],
        podcast_script=cached["podcast_script"],
        language=cached["language"],
        category=cached.get("category"),
    )


@app.get("/videos/{video_id}/audio")
def get_audio(video_id: str):
    audio_data = get_cached_audio(video_id)
    if not audio_data:
        raise HTTPException(status_code=404, detail="Аудио не найдено в кэше")
    return Response(
        content=audio_data,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f"attachment; filename={video_id}.mp3"}
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.delete("/videos/expired")
def delete_expired():
    delete_expired_cache(days=7)
    return {"message": "Устаревшие видео удалены"}


@app.delete("/videos/{video_id}")
def delete_video(video_id: str):
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    delete_cache(video_id)
    return {"message": f"Видео {video_id} удалено из кэша"}