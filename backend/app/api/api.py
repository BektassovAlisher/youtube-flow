from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
import json
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from agent.agent_node import app as agent_app
from agent.agent import qa_agent, recommend_node
from db.cache import (
    get_cached_video, get_cached_audio, delete_cache,
    save_audio_to_cache, get_cached_recommendation,
)
from db.database import SessionLocal, Video
from tools.youtube_scraper import YoutubeExtractTool


app = FastAPI(
    title="VideoFlow API",
    description="API для генерации подкастов из YouTube-видео",
    version="1.0.0",
)


class GenerateRequest(BaseModel):
    video_url: str
    skip_audio: bool = False


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
    title: str | None = None
    summary: str
    keywords: List[str]
    podcast_script: str
    language: str
    category: Optional[str] = None


class VideoListItem(BaseModel):
    video_id: str
    title: str | None = None
    url: str
    language: str | None
    duration_sec: float | None
    category: str | None = None
    created_at: datetime | None = None


class AudioGenerateResponse(BaseModel):
    video_id: str
    audio_path: str
    from_cache: bool


class RecommendResponse(BaseModel):
    video_id: str
    courses: List[dict]
    books: List[dict]
    from_cache: bool


def _start(req: GenerateRequest) -> dict:
    try:
        YoutubeExtractTool().extract_video_id(req.video_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
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


def _response(result: dict, req: GenerateRequest) -> GenerateResponse:
    video_id = result["video_metadata"]["video_id"]
    if result.get("audio_path") == "rejected":
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
    return GenerateResponse(
        video_id=video_id,
        summary=result.get("summary", ""),
        keywords=result.get("keywords", []),
        podcast_script=result.get("podcast_script", ""),
        audio_cached=get_cached_audio(video_id) is not None,
        cache_hit=result.get("cache_hit", False),
        rejected=False,
        skip_audio=req.skip_audio,
        video_category=result.get("video_category"),
        classification_reason=result.get("classification_reason"),
        recommendation=result.get("recommendation"),
    )


@app.post("/generate", response_model=GenerateResponse)
def generate_podcast(req: GenerateRequest):
    data = _start(req)
    try:
        return _response(agent_app.invoke(data), req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Same as /generate, but reports progress: one NDJSON line per finished graph node ({"step": name}),
# then {"result": ...} or {"error": ...}. The UI uses it to show which stage is running.
@app.post("/generate/stream")
def generate_stream(req: GenerateRequest):
    data = _start(req)

    def events():
        state = None
        try:
            for mode, chunk in agent_app.stream(data, stream_mode=["updates", "values"]):
                if mode == "values":
                    state = chunk
                else:
                    for node in chunk:
                        yield json.dumps({"step": node}) + "\n"
            yield json.dumps({"result": _response(state, req).model_dump(mode="json")}) + "\n"
        except Exception as e:
            yield json.dumps({"error": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.post("/videos/{video_id}/qa", response_model=QAResponse)
def ask_video_question(video_id: str, req: QARequest):
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
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено. Сначала запустите /generate.")
    cached_rec = get_cached_recommendation(video_id)
    if cached_rec:
        return RecommendResponse(
            video_id=video_id,
            courses=cached_rec.get("courses", []),
            books=cached_rec.get("books", []),
            from_cache=True,
        )

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
    audio_url = f"/videos/{video_id}/audio"
    if get_cached_audio(video_id):
        return AudioGenerateResponse(video_id=video_id, audio_path=audio_url, from_cache=True)

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
        audio_bytes = audio_tool.generate_podcast_audio(script=script, language=language)
        save_audio_to_cache(video_id, audio_bytes)
        return AudioGenerateResponse(video_id=video_id, audio_path=audio_url, from_cache=False)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/videos", response_model=list[VideoListItem])
def list_videos():
    session = SessionLocal()
    try:
        videos = session.query(Video).order_by(Video.created_at.desc()).all()
        return [
            VideoListItem(
                video_id=v.video_id,
                title=v.title,
                url=v.url,
                language=v.language,
                duration_sec=v.duration_sec,
                category=v.category,
                created_at=v.created_at,
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
        title=cached["title"],
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


@app.delete("/videos/{video_id}")
def delete_video(video_id: str):
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    delete_cache(video_id)
    return {"message": f"Видео {video_id} удалено из кэша"}