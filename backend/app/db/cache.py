"""Data access for videos and everything generated for them. Each function is one short transaction."""
import threading
from collections import OrderedDict
from contextlib import contextmanager

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import undefer

from .database import (
    Keyword, PodcastAudio, PodcastScript, QAAnswer, Recommendation, SessionLocal, Summary, Video, utcnow,
)


@contextmanager
def _session():
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _has_summary(s, video_id: str) -> bool:
    return bool(s.scalar(select(exists().where(Summary.video_id == video_id))))


def _latest(column, fk, video_id, order):
    return select(column).where(fk == video_id).order_by(order.desc()).limit(1).scalar_subquery()


def get_video(video_id: str) -> dict | None:
    """The video with its summary, script, keywords and flags — two queries."""
    with _session() as s:
        row = s.execute(
            select(
                Video,
                _latest(Summary.content, Summary.video_id, Video.video_id, Summary.id).label("summary"),
                _latest(PodcastScript.script, PodcastScript.video_id, Video.video_id, PodcastScript.id).label("script"),
                _latest(Recommendation.data, Recommendation.video_id, Video.video_id, Recommendation.id).label("rec"),
                exists().where(PodcastAudio.video_id == Video.video_id).label("audio"),
            ).where(Video.video_id == video_id)
        ).first()
        if row is None:
            return None
        v, summary, script, rec, audio = row
        keywords = s.scalars(select(Keyword.keyword).where(Keyword.video_id == video_id).order_by(Keyword.id)).all()
        return {
            **_item(v),
            "summary": summary or "",
            "podcast_script": script or "",
            "keywords": list(dict.fromkeys(keywords)),
            "recommendation": rec,
            "audio_ready": bool(audio),
            "stage": v.stage,
            "error": v.error,
            "classification": v.classification,
            "force": bool(v.force),
            "indexed": bool(v.indexed),
            "transcript_source": v.transcript_source,
            "anchors": v.anchors,
            "metrics": v.metrics,
        }


def _item(v: Video) -> dict:
    return {
        "video_id": v.video_id,
        "kind": v.kind or "youtube",
        "title": v.title,
        "url": v.url,
        "language": v.language,
        "duration_sec": v.duration_sec,
        "category": v.category,
        "channel": v.channel,
        "image_url": v.image_url,
        "word_count": v.word_count,
        "source": v.transcript_source,
        "status": v.status,
        "created_at": v.created_at,
    }


def list_videos(limit: int = 24, offset: int = 0, q: str | None = None) -> tuple[list[dict], int]:
    """Library page: ready and in-progress videos, newest first, optionally filtered by title/channel."""
    cond = Video.status.in_(("ready", "processing"))
    if q:
        like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cond = cond & or_(func.lower(Video.title).like(like, escape="\\"), func.lower(Video.channel).like(like, escape="\\"))
    with _session() as s:
        total = s.scalar(select(func.count()).select_from(Video).where(cond)) or 0
        rows = s.scalars(select(Video).where(cond).order_by(Video.created_at.desc()).limit(limit).offset(offset)).all()
        return [_item(v) for v in rows], total


# ---- processing state -------------------------------------------------------------------------

def begin_processing(video_id: str, url: str, force: bool = False, kind: str | None = None,
                     title: str | None = None) -> None:
    """Creates the row for a new material, or prepares an existing one for another run (its kind is kept)."""
    with _session() as s:
        v = s.get(Video, video_id)
        if v is None:
            s.add(Video(video_id=video_id, url=url, kind=kind or "youtube", title=title, status="processing",
                        stage="queued", force=force))
            return
        v.force = v.force or force
        v.error = None
        v.stage = "queued"
        v.status = "ready" if _has_summary(s, video_id) else "processing"


def set_stage(video_id: str, stage: str) -> None:
    with _session() as s:
        s.execute(update(Video).where(Video.video_id == video_id).values(stage=stage, updated_at=utcnow()))


def finish(video_id: str) -> None:
    with _session() as s:
        status = "ready" if _has_summary(s, video_id) else "failed"
        s.execute(update(Video).where(Video.video_id == video_id).values(stage="done", error=None, status=status))


def fail(video_id: str, message: str) -> None:
    """Keeps whatever was saved before the failure; the summary stays readable if it exists."""
    with _session() as s:
        status = "ready" if _has_summary(s, video_id) else "failed"
        s.execute(update(Video).where(Video.video_id == video_id).values(status=status, error=message))


def reject(video_id: str) -> None:
    with _session() as s:
        s.execute(update(Video).where(Video.video_id == video_id).values(status="rejected", stage="classify", error=None))


def interrupted() -> list[dict]:
    """Runs that were cut off by a restart: resumed when the API starts."""
    with _session() as s:
        rows = s.scalars(
            select(Video).where(
                Video.stage.is_not(None), Video.stage != "done", Video.error.is_(None), Video.status != "rejected"
            )
        ).all()
        return [{"video_id": v.video_id, "url": v.url, "force": bool(v.force)} for v in rows]


# ---- pipeline artifacts -----------------------------------------------------------------------

def save_transcript(video_id: str, segments: list[dict], *, language: str, source: str, duration_sec: float | None,
                    title: str | None, channel: str | None, **extra) -> None:
    """The material's text with its metadata; `extra` takes image_url, word_count and anchors for text materials."""
    with _session() as s:
        s.execute(update(Video).where(Video.video_id == video_id).values(
            transcript=segments, transcript_source=source, language=language, duration_sec=duration_sec,
            title=title, channel=channel, **{k: v for k, v in extra.items() if k in ("image_url", "word_count", "anchors")},
        ))


def load_transcript(video_id: str) -> list[dict] | None:
    with _session() as s:
        v = s.scalars(select(Video).options(undefer(Video.transcript)).where(Video.video_id == video_id)).first()
        return v.transcript if v and v.transcript else None


def save_classification(video_id: str, classification: dict) -> None:
    with _session() as s:
        s.execute(update(Video).where(Video.video_id == video_id).values(
            classification=classification, category=classification.get("category"),
        ))


def save_summary(video_id: str, content: str) -> None:
    with _session() as s:
        s.execute(delete(Summary).where(Summary.video_id == video_id))
        s.add(Summary(video_id=video_id, content=content))
        s.execute(update(Video).where(Video.video_id == video_id).values(status="ready"))


def save_keywords(video_id: str, keywords: list[str]) -> None:
    with _session() as s:
        s.execute(delete(Keyword).where(Keyword.video_id == video_id))
        s.add_all(Keyword(video_id=video_id, keyword=k) for k in keywords)


def save_script(video_id: str, script: str) -> None:
    with _session() as s:
        s.execute(delete(PodcastScript).where(PodcastScript.video_id == video_id))
        s.add(PodcastScript(video_id=video_id, script=script))


def mark_indexed(video_id: str, indexed: bool = True) -> None:
    with _session() as s:
        s.execute(update(Video).where(Video.video_id == video_id).values(indexed=indexed))


def clear_for_regenerate(video_id: str, part: str) -> None:
    """part="summary" redoes everything after the transcript, part="script" only the podcast."""
    with _session() as s:
        s.execute(delete(PodcastScript).where(PodcastScript.video_id == video_id))
        s.execute(delete(PodcastAudio).where(PodcastAudio.video_id == video_id))
        if part == "summary":
            s.execute(delete(Summary).where(Summary.video_id == video_id))
            s.execute(delete(Keyword).where(Keyword.video_id == video_id))
            s.execute(delete(QAAnswer).where(QAAnswer.video_id == video_id))
            s.execute(update(Video).where(Video.video_id == video_id).values(metrics=None))  # a new run, new numbers
    _audio_cache.drop(video_id)


# ---- metrics ----------------------------------------------------------------------------------

def add_metrics(video_id: str, run: dict) -> None:
    """Adds one run to the material's metrics. A resumed run only does the steps that were left, so seconds,
    step times and tokens add up; the time to the first words is kept from the run that wrote the summary."""
    with _session() as s:
        v = s.get(Video, video_id)
        if v is None:
            return
        m = dict(v.metrics or {})
        m["seconds"] = round(m.get("seconds", 0) + run.get("seconds", 0), 2)
        steps = dict(m.get("steps") or {})
        for name, sec in (run.get("steps") or {}).items():
            steps[name] = round(steps.get(name, 0) + sec, 2)
        m["steps"] = steps
        tokens = dict(m.get("tokens") or {})
        for name, n in (run.get("tokens") or {}).items():
            tokens[name] = tokens.get(name, 0) + n
        m["tokens"] = tokens
        for key in ("first_token", "audio", "model"):
            if run.get(key) is not None:
                m[key] = run[key]
        m["runs"] = m.get("runs", 0) + (1 if run.get("steps") else 0)
        v.metrics = m


def stats() -> dict:
    """Averages over the materials that have metrics: for the README's numbers and a quick health look."""
    with _session() as s:
        rows = [m for m in s.scalars(select(Video.metrics).where(Video.status == "ready")).all() if m and m.get("steps")]
    avg = lambda values: round(sum(values) / len(values), 2) if values else None  # noqa: E731
    names = sorted({name for m in rows for name in m["steps"]})
    return {
        "materials": len(rows),
        "avg_seconds": avg([m["seconds"] for m in rows]),
        "avg_first_token": avg([m["first_token"] for m in rows if m.get("first_token") is not None]),
        "avg_steps": {name: avg([m["steps"][name] for m in rows if name in m["steps"]]) for name in names},
        "avg_audio": avg([m["audio"] for m in rows if m.get("audio") is not None]),
        "tokens": {k: sum((m.get("tokens") or {}).get(k, 0) for m in rows) for k in ("input", "output")},
    }


# ---- audio ------------------------------------------------------------------------------------

def audio_exists(video_id: str) -> bool:
    with _session() as s:
        return bool(s.scalar(select(exists().where(PodcastAudio.video_id == video_id))))


def get_audio(video_id: str) -> tuple[bytes, object] | None:
    """(mp3 bytes, created_at) or None."""
    with _session() as s:
        a = s.scalars(
            select(PodcastAudio).options(undefer(PodcastAudio.audio_data)).where(PodcastAudio.video_id == video_id)
        ).first()
        return (a.audio_data, a.created_at) if a else None


def save_audio(video_id: str, data: bytes) -> None:
    with _session() as s:
        s.execute(delete(PodcastAudio).where(PodcastAudio.video_id == video_id))
        s.add(PodcastAudio(video_id=video_id, audio_data=data, created_at=utcnow()))
    _audio_cache.drop(video_id)


class _AudioCache:
    """Recently played podcasts in memory: a player makes several Range requests per file."""

    def __init__(self, max_bytes: int = 64 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, video_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._items.get(video_id)
            if item:
                self._items.move_to_end(video_id)
            return item

    def put(self, video_id: str, data: bytes, etag: str) -> None:
        with self._lock:
            self._items[video_id] = (data, etag)
            self._items.move_to_end(video_id)
            while sum(len(d) for d, _ in self._items.values()) > self.max_bytes and len(self._items) > 1:
                self._items.popitem(last=False)

    def drop(self, video_id: str) -> None:
        with self._lock:
            self._items.pop(video_id, None)


_audio_cache = _AudioCache()


def get_audio_cached(video_id: str) -> tuple[bytes, str] | None:
    """(mp3 bytes, ETag) — from memory when possible."""
    item = _audio_cache.get(video_id)
    if item:
        return item
    row = get_audio(video_id)
    if row is None:
        return None
    data, created_at = row
    stamp = int(created_at.timestamp()) if created_at else len(data)
    item = (data, f'"{video_id}-{stamp}"')
    _audio_cache.put(video_id, *item)
    return item


# ---- recommendations and answers --------------------------------------------------------------

def get_recommendation(video_id: str) -> dict | None:
    with _session() as s:
        return s.scalar(select(Recommendation.data).where(Recommendation.video_id == video_id))


def save_recommendation(video_id: str, data: dict) -> None:
    with _session() as s:
        s.execute(delete(Recommendation).where(Recommendation.video_id == video_id))
        s.add(Recommendation(video_id=video_id, data=data))


def get_answer(video_id: str, key: str) -> dict | None:
    with _session() as s:
        a = s.scalars(select(QAAnswer).where(QAAnswer.video_id == video_id, QAAnswer.question_key == key)).first()
        return {"answer": a.answer, "sources": a.sources} if a else None


def save_answer(video_id: str, key: str, question: str, answer: str, sources: list[dict]) -> None:
    with _session() as s:
        s.execute(delete(QAAnswer).where(QAAnswer.video_id == video_id, QAAnswer.question_key == key))
        s.add(QAAnswer(video_id=video_id, question_key=key, question=question, answer=answer, sources=sources))


def delete_video(video_id: str) -> bool:
    """Deletes the row and everything generated for it in one transaction. The vector index is removed by the caller."""
    with _session() as s:
        if s.get(Video, video_id) is None:
            return False
        for model in (Summary, Keyword, PodcastScript, PodcastAudio, Recommendation, QAAnswer):
            s.execute(delete(model).where(model.video_id == video_id))
        s.execute(delete(Video).where(Video.video_id == video_id))
    _audio_cache.drop(video_id)
    return True
