"""YouTube: link parsing, video metadata and the transcript (subtitles first, speech recognition as a fallback)."""
import html
import logging
import os
import re
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import (
    AgeRestricted, CouldNotRetrieveTranscript, InvalidVideoId, IpBlocked, NoTranscriptFound, PoTokenRequired,
    RequestBlocked, TranscriptsDisabled, VideoUnavailable, VideoUnplayable, YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

import config
from errors import UserError

log = logging.getLogger(__name__)

PREFERRED_LANGUAGES = ["ru", "en", "kk"]
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtu.be"}

BLOCKED = ("YouTube блокирует запросы с этого сервера, так часто бывает с облачными IP. "
           "Попробуйте позже или задайте прокси в YOUTUBE_PROXY_URL.")


def parse_video_id(raw: str) -> str:
    """Video id from any YouTube video link (or a bare id). Raises UserError with a hint otherwise."""
    s = (raw or "").strip()
    if not s:
        raise UserError("Вставьте ссылку на видео с YouTube.")
    if VIDEO_ID.match(s):
        return s
    if "://" not in s:
        s = "https://" + s
    try:
        u = urlparse(s)
        host = (u.hostname or "").lower().removeprefix("www.")
    except ValueError:
        host = ""
    if host not in HOSTS:
        raise UserError("Это не ссылка на YouTube. Нужна ссылка вида youtube.com/watch?v=… или youtu.be/….")
    parts = [p for p in u.path.split("/") if p]
    candidate = None
    if host == "youtu.be":
        candidate = parts[0] if parts else None
    elif not parts or parts[0] == "watch":
        candidate = (parse_qs(u.query).get("v") or [None])[0]
    elif parts[0] in ("shorts", "embed", "live", "v", "e") and len(parts) > 1:
        candidate = parts[1]
    elif parts[0] == "playlist":
        raise UserError("Это ссылка на плейлист. Откройте нужное видео и скопируйте ссылку на него.")
    elif parts[0].startswith("@") or parts[0] in ("channel", "c", "user"):
        raise UserError("Это ссылка на канал. Откройте нужное видео и скопируйте ссылку на него.")
    if not candidate or not VIDEO_ID.match(candidate):
        raise UserError("Не удалось найти видео в ссылке. Проверьте, что она ведёт на конкретное видео.")
    return candidate


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _proxies() -> dict | None:
    return {"http": config.YOUTUBE_PROXY_URL, "https": config.YOUTUBE_PROXY_URL} if config.YOUTUBE_PROXY_URL else None


def fetch_metadata(video_id: str, timeout: float = 5) -> dict:
    """Title and channel from YouTube's oEmbed endpoint: plain JSON, no HTML scraping or consent pages."""
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": watch_url(video_id), "format": "json"},
            timeout=timeout,
            proxies=_proxies(),
        )
        if r.ok:
            data = r.json()
            return {"title": html.unescape(data.get("title") or "") or None, "channel": data.get("author_name")}
    except (requests.RequestException, ValueError) as e:
        log.info("oEmbed для %s недоступен: %s", video_id, e)
    return {"title": None, "channel": None}


_GENRE = re.compile(r'<meta itemprop="genre" content="([^"]+)"|"category":"([^"]+)"')


def fetch_category(video_id: str, timeout: float = 5) -> str | None:
    """The category the author picked on YouTube ("Education", "Music", ...), from the watch page.
    None when the page is unavailable: the check then simply asks the model."""
    try:
        r = requests.get(watch_url(video_id), timeout=timeout, proxies=_proxies(),
                         headers={"Accept-Language": "en-US,en;q=0.8"},
                         cookies={"CONSENT": "YES+1", "SOCS": "CAI"})  # skips the EU cookie consent page
        if r.ok:
            m = _GENRE.search(r.text)
            if m:
                return html.unescape(m.group(1) or m.group(2)).strip() or None
    except requests.RequestException as e:
        log.info("категория %s недоступна: %s", video_id, e)
    return None


class NoSubtitles(Exception):
    """The video has no subtitles at all: the caller may fall back to speech recognition."""


def fetch_subtitles(video_id: str) -> dict:
    """Subtitles in ru/en/kk if there are any, otherwise in whatever language the video has them."""
    proxy = GenericProxyConfig(http_url=config.YOUTUBE_PROXY_URL, https_url=config.YOUTUBE_PROXY_URL) \
        if config.YOUTUBE_PROXY_URL else None
    api = YouTubeTranscriptApi(proxy_config=proxy)
    try:
        listing = api.list(video_id)
        try:
            transcript = listing.find_transcript(PREFERRED_LANGUAGES)
        except NoTranscriptFound:
            transcript = next(iter(listing), None)  # manual ones come first, then auto-generated
            if transcript is None:
                raise NoSubtitles()
            log.info("%s: нет субтитров ru/en/kk, беру %s", video_id, transcript.language_code)
        fetched = transcript.fetch()
    except (TranscriptsDisabled, NoTranscriptFound):
        raise NoSubtitles()
    except AgeRestricted:
        raise UserError("У видео возрастное ограничение: YouTube не отдаёт его субтитры без входа в аккаунт.")
    except VideoUnplayable:
        raise UserError("YouTube не даёт воспроизвести это видео (ограничение по региону или правам).")
    except VideoUnavailable:
        raise UserError("Видео недоступно: оно удалено, скрыто или в ссылке ошибка.")
    except InvalidVideoId:
        raise UserError("Неверный идентификатор видео. Проверьте ссылку.")
    except (RequestBlocked, IpBlocked):
        raise UserError(BLOCKED, status=503)
    except PoTokenRequired:
        raise UserError("YouTube потребовал дополнительную проверку для субтитров этого видео. Попробуйте позже.", 503)
    except CouldNotRetrieveTranscript as e:
        log.warning("субтитры %s: %s", video_id, type(e).__name__)
        raise UserError("Не удалось получить субтитры с YouTube. Попробуйте ещё раз позже.", status=503)

    segments = [
        {"start": float(s.start), "duration": float(s.duration), "text": s.text.strip()}
        for s in fetched.snippets if s.text and s.text.strip()
    ]
    if not segments:
        raise NoSubtitles()
    return {
        "segments": segments,
        "language": fetched.language_code,
        "source": "generated" if fetched.is_generated else "manual",
    }


def get_transcript(video_id: str) -> dict:
    """{segments, language, source[, title, channel]}: subtitles, or Whisper when the video has none."""
    try:
        return fetch_subtitles(video_id)
    except NoSubtitles:
        pass
    if not (config.WHISPER_FALLBACK and os.getenv("GROQ_API_KEY")):
        raise UserError("У этого видео нет субтитров, а распознавание речи выключено (WHISPER_FALLBACK).")
    from tools.whisper import transcribe_youtube  # heavy imports only when needed

    log.info("%s: субтитров нет, распознаю речь через Whisper", video_id)
    return transcribe_youtube(video_id)


def duration_of(segments: list[dict]) -> float:
    """Length of a video transcript; 0 for text materials (they have paragraphs, not times)."""
    if not segments or "start" not in segments[-1]:
        return 0.0
    last = segments[-1]
    return round(last["start"] + last.get("duration", 0.0), 2)
