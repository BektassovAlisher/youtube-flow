import asyncio
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

import config
import jobs
from agent.chat_agent import rag
from api.security import client_id, limiter, require_token
from db import cache as repo
from db.database import init_db
from errors import UserError, humanize
from tools import recommendations, sources, text_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("videoflow")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(init_db)  # waits for Postgres instead of crashing while it starts
    if not config.API_TOKEN:
        log.warning("API_TOKEN не задан: запускать обработку и удалять видео может любой, кто видит API")
    jobs.resume_interrupted()
    threading.Thread(target=rag.warm_up, name="embeddings-warm-up", daemon=True).start()
    yield
    jobs.hub.shutdown()


app = FastAPI(title="VideoFlow API", description="Конспекты, подкасты и ответы по обучающим видео, статьям и текстам",
              version="2.1.0", lifespan=lifespan)

protected = [Depends(require_token)]


@app.exception_handler(UserError)
async def _user_error(_request: Request, exc: UserError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


# ---- models -----------------------------------------------------------------------------------

class CreateVideo(BaseModel):
    """A link (YouTube video or article) or a pasted text with an optional title."""
    url: str | None = None
    video_url: str | None = None  # the old name of `url`
    text: str | None = None
    title: str | None = Field(None, max_length=300)
    force: bool = False  # process even if the classifier decided the material is not educational


class Regenerate(BaseModel):
    part: Literal["summary", "script"]


class Turn(BaseModel):
    q: str
    a: str


class Question(BaseModel):
    question: str
    history: list[Turn] = Field(default_factory=list, max_length=10)


class GenerateRequest(BaseModel):
    video_url: str  # a YouTube video or an article
    skip_audio: bool = True


def _json(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json(v) for v in value]
    return value


def _payload(video_id: str) -> dict:
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    return _json({**video, "jobs": jobs.hub.active(video_id)})


def _complete(video: dict) -> bool:
    return video["status"] == "ready" and bool(video["summary"] and video["keywords"] and video["podcast_script"])


def _start(link: str, force: bool, request: Request) -> str:
    kind, video_id, url = sources.detect_url(link)
    video = repo.get_video(video_id)
    if video and not force and (video["status"] == "rejected" or _complete(video)):
        return video_id  # nothing to do: the stored result (or the stored rejection) is the answer
    if jobs.hub.get(video_id, "process") is None:  # a new run spends LLM credits
        limiter.hit("videos", client_id(request), config.LIMIT_VIDEOS_PER_HOUR)
    jobs.start_processing(video_id, url, force, kind)
    return video_id


def _start_segments(text: str, segments: list[dict], title: str, source: str, request: Request) -> str:
    """Pasted or uploaded text is saved right away; the run then starts from the summary."""
    video_id = text_sources.text_id(text)
    video = repo.get_video(video_id)
    if video and _complete(video):
        return video_id
    if jobs.hub.get(video_id, "process") is None:
        limiter.hit("videos", client_id(request), config.LIMIT_VIDEOS_PER_HOUR)
        repo.begin_processing(video_id, "", kind="text", title=title)
        repo.save_transcript(video_id, segments, language=text_sources.guess_language(text), source=source,
                             duration_sec=None, title=title, channel=None,
                             word_count=text_sources.word_count(segments))
    jobs.start_processing(video_id, "", kind="text")
    return video_id


def _start_text(text: str, title: str | None, request: Request) -> str:
    segments = text_sources.parse_pasted(text)
    name = (title or "").strip() or text_sources.title_from_text(text)
    return _start_segments(text, segments, name, "pasted", request)


# ---- videos -----------------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/videos")
def list_videos(response: Response, limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0),
                q: str | None = Query(None, max_length=200)):
    items, total = repo.list_videos(limit, offset, q.strip() if q else None)
    response.headers["X-Total-Count"] = str(total)
    return _json(items)


@app.post("/videos", dependencies=protected)
def create_video(req: CreateVideo, request: Request):
    """Starts processing (or returns the stored result) right away; progress comes from /videos/{id}/events."""
    if req.text is not None:
        return _payload(_start_text(req.text, req.title, request))
    return _payload(_start(req.url or req.video_url or "", req.force, request))


@app.post("/videos/upload", dependencies=protected)
async def upload(request: Request, file: UploadFile = File(...), title: str | None = Form(None, max_length=300)):
    """A PDF, TXT or Markdown file becomes a text material, like pasted text."""
    data = await file.read(text_sources.MAX_FILE_BYTES + 1)
    doc = await asyncio.to_thread(text_sources.parse_document, file.filename or "", data)
    name = (title or "").strip() or doc["title"]
    video_id = await asyncio.to_thread(_start_segments, doc["text"], doc["segments"], name, doc["source"], request)
    return await asyncio.to_thread(_payload, video_id)


@app.get("/videos/{video_id}")
def get_video(video_id: str):
    return _payload(video_id)


@app.get("/videos/{video_id}/source")
def get_source(video_id: str):
    """The paragraphs of a pasted text, for reading it next to the summary. Articles link to the original instead."""
    video = repo.get_video(video_id)
    if video is None or video["kind"] != "text":
        raise HTTPException(status_code=404, detail="Исходный текст есть только у вставленных текстов")
    return {"video_id": video_id, "segments": repo.load_transcript(video_id) or []}


@app.get("/videos/{video_id}/events")
async def video_events(video_id: str):
    """NDJSON: snapshot, then job/token/saved/rejected/done/error events, ending with "idle"."""
    async def stream():
        async for event in jobs.hub.events(video_id):
            yield json.dumps(event, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/videos/{video_id}/regenerate", dependencies=protected)
def regenerate(video_id: str, req: Regenerate, request: Request):
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    if jobs.hub.get(video_id, "process") or jobs.hub.get(video_id, "audio"):
        raise UserError("Материал сейчас обрабатывается. Дождитесь окончания.", status=409)
    limiter.hit("videos", client_id(request), config.LIMIT_VIDEOS_PER_HOUR)
    repo.clear_for_regenerate(video_id, req.part)
    jobs.start_processing(video_id, video["url"])
    return _payload(video_id)


@app.post("/videos/{video_id}/resume", dependencies=protected)
def resume(video_id: str, request: Request):
    """Continue an interrupted or failed run from its last saved step (works for every kind of material)."""
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    if jobs.hub.get(video_id, "process") is None and not _complete(video):
        limiter.hit("videos", client_id(request), config.LIMIT_VIDEOS_PER_HOUR)
        jobs.start_processing(video_id, video["url"])
    return _payload(video_id)


@app.delete("/videos/{video_id}", dependencies=protected)
def delete_video(video_id: str):
    if jobs.hub.active(video_id):
        raise UserError("Материал сейчас обрабатывается. Удалить его можно после окончания.", status=409)
    if not repo.delete_video(video_id):
        raise HTTPException(status_code=404, detail="Видео не найдено")
    rag.delete_video_index(video_id)
    return {"message": "Видео удалено"}


# ---- questions and recommendations ------------------------------------------------------------

def _charge(request: Request):
    return lambda: limiter.hit("questions", client_id(request), config.LIMIT_QUESTIONS_PER_HOUR)


def _ensure_video(video_id: str) -> dict:
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    if not video["summary"]:
        raise UserError("Вопросы появятся, когда будет готов конспект.", status=409)
    return video


@app.post("/videos/{video_id}/qa", dependencies=protected)
async def ask(video_id: str, req: Question, request: Request):
    await asyncio.to_thread(_ensure_video, video_id)
    sources, parts, cached = [], [], False
    history = [t.model_dump() for t in req.history]
    async for event in rag.answer_events(video_id, req.question, history, charge=_charge(request)):
        if event["type"] == "sources":
            sources = event["sources"]
        elif event["type"] == "token":
            parts.append(event["text"])
        elif event["type"] == "done":
            cached = event["cached"]
    return {"video_id": video_id, "answer": "".join(parts), "sources": sources, "cached": cached}


@app.post("/videos/{video_id}/qa/stream", dependencies=protected)
async def ask_stream(video_id: str, req: Question, request: Request):
    """NDJSON: {"type": "sources"}, {"type": "token"}…, then {"type": "done"} or {"type": "error"}."""
    await asyncio.to_thread(_ensure_video, video_id)
    history = [t.model_dump() for t in req.history]

    async def stream():
        try:
            async for event in rag.answer_events(video_id, req.question, history, charge=_charge(request)):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001 — the status line is already sent: report inside the stream
            if not isinstance(e, UserError):
                log.exception("ответ на вопрос по %s", video_id)
            yield json.dumps({"type": "error", "message": humanize(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/videos/{video_id}/recommend", dependencies=protected)
def recommend(video_id: str, request: Request):
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    if video["recommendation"]:
        rec, from_cache = video["recommendation"], True
    else:
        limiter.hit("questions", client_id(request), config.LIMIT_QUESTIONS_PER_HOUR)
        try:
            rec, from_cache = recommendations.find(video), False
        except UserError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("рекомендации для %s", video_id)
            raise UserError(f"Не удалось подобрать рекомендации. {humanize(e)}", status=503)
    return {"video_id": video_id, "courses": rec.get("courses", []), "books": rec.get("books", []),
            "from_cache": from_cache}


# ---- audio ------------------------------------------------------------------------------------

@app.post("/videos/{video_id}/audio", dependencies=protected)
def create_audio(video_id: str, request: Request):
    audio_url = f"/videos/{video_id}/audio"
    if repo.audio_exists(video_id):
        return {"video_id": video_id, "audio_path": audio_url, "from_cache": True, "job": None}
    video = repo.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Видео не найдено")
    if not video["podcast_script"]:
        raise UserError("Сценарий подкаста ещё не готов.", status=409)
    if jobs.hub.get(video_id, "audio") is None:
        limiter.hit("audio", client_id(request), config.LIMIT_AUDIO_PER_HOUR)
    job, _ = jobs.start_audio(video_id, video["podcast_script"])
    return JSONResponse({"video_id": video_id, "audio_path": audio_url, "from_cache": False, "job": job.snapshot()},
                        status_code=202)


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _byte_range(header: str | None, size: int):
    """(start, end) for a single "bytes=" range, None to send everything, "invalid" for 416."""
    m = _RANGE.match((header or "").strip())
    if not m or (not m.group(1) and not m.group(2)):
        return None
    if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
    else:  # suffix: the last N bytes
        start, end = max(0, size - int(m.group(2))), size - 1
    if start >= size or start > end:
        return "invalid"
    return start, end


@app.get("/videos/{video_id}/audio")
def get_audio(video_id: str, request: Request):
    item = repo.get_audio_cached(video_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Аудио ещё не создано")
    data, etag = item
    headers = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": "no-cache",
               "Content-Disposition": f'inline; filename="{video_id}.mp3"'}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    rng = _byte_range(request.headers.get("range"), len(data))
    if rng == "invalid":
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{len(data)}"})
    if rng is None:
        return Response(content=data, media_type="audio/mpeg", headers=headers)
    start, end = rng
    return Response(content=data[start:end + 1], status_code=206, media_type="audio/mpeg",
                    headers={**headers, "Content-Range": f"bytes {start}-{end}/{len(data)}"})


# ---- compatibility ----------------------------------------------------------------------------

@app.post("/generate", dependencies=protected)
def generate(req: GenerateRequest, request: Request):
    """Old synchronous endpoint for scripts and curl: waits until the video is processed."""
    video_id = _start(req.video_url, False, request)
    jobs.hub.wait(video_id, "process", timeout=1800)
    video = repo.get_video(video_id)
    if video and not req.skip_audio and video["podcast_script"] and not video["audio_ready"]:
        jobs.start_audio(video_id, video["podcast_script"])
        jobs.hub.wait(video_id, "audio", timeout=1800)
        video = repo.get_video(video_id)
    if video is None or video["status"] == "failed":
        raise UserError((video or {}).get("error") or "Не удалось обработать видео.", status=502)
    classification = video["classification"] or {}
    rejected = video["status"] == "rejected"
    return {
        "video_id": video_id,
        "summary": "" if rejected else video["summary"],
        "keywords": [] if rejected else video["keywords"],
        "podcast_script": "" if rejected else video["podcast_script"],
        "audio_cached": video["audio_ready"],
        "rejected": rejected,
        "skip_audio": req.skip_audio,
        "video_category": video["category"],
        "classification_reason": classification.get("reason"),
        "error": video["error"],
    }
