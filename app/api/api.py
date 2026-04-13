from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import List
from agent.agent import app as agent_app
from db.cache import get_cached_video, get_cached_audio, delete_cache, delete_expired_cache
from db.database import SessionLocal, Video


app = FastAPI(
    title="VideoFlow API",
    description="API для генерации подкастов из YouTube-видео",
    version="1.0.0",
)


class GenerateRequest(BaseModel):
    video_url: str


class GenerateResponse(BaseModel):
    video_id: str
    summary: str
    keywords: List[str]
    podcast_script: str
    audio_cached: bool
    cache_hit: bool


class VideoInfo(BaseModel):
    video_id: str
    summary: str
    keywords: List[str]
    podcast_script: str
    language: str


class VideoListItem(BaseModel):
    video_id: str
    url: str
    language: str | None
    duration_sec: float | None


@app.post("/generate", response_model=GenerateResponse)
def generate_podcast(req: GenerateRequest):
    try:
        data = {
            "video_url": req.video_url,
            "retry_count": 0,
            "max_retries": 2,
            "critic_feedback": "",
            "is_valid": False,
            "cache_hit": False,
            "agent_execution_order": []
        }

        result = agent_app.invoke(data)
        video_id = result["video_metadata"]["video_id"]
        cached_audio = get_cached_audio(video_id)

        return GenerateResponse(
            video_id=video_id,
            summary=result.get("summary", ""),
            keywords=result.get("keywords", []),
            podcast_script=result.get("podcast_script", ""),
            audio_cached=cached_audio is not None,
            cache_hit=result.get("cache_hit", False)
        )
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
        language=cached["language"]
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
    deleted = delete_expired_cache(days=7)
    return {"message": f"Удалено {deleted} устаревших видео"}


@app.delete("/videos/{video_id}")
def delete_video(video_id: str):
    cached = get_cached_video(video_id)
    if not cached:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    delete_cache(video_id)
    return {"message": f"Видео {video_id} удалено из кэша"}