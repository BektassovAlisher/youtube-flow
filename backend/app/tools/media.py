"""Video and audio from sites other than YouTube (Vimeo, Rutube, VK Видео, TED, SoundCloud, podcasts…) and
direct links to media files. Subtitles are used when the site has them, otherwise speech is recognized
(Groq Whisper). Places are timestamps, like in YouTube videos."""
import hashlib
import logging
import os
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests

import config
from errors import UserError
from tools import text_sources

log = logging.getLogger(__name__)

# host -> path prefix of media pages on it (None: every page). Curated on purpose: news sites also have
# yt-dlp extractors, and their articles must stay articles.
MEDIA_SITES = {
    "vimeo.com": None, "rutube.ru": "/video", "vkvideo.ru": None, "vk.com": "/video", "ok.ru": "/video",
    "dzen.ru": "/video", "twitch.tv": "/videos", "dailymotion.com": "/video", "ted.com": "/talks",
    "bilibili.com": "/video", "soundcloud.com": None, "podcasts.apple.com": None, "mixcloud.com": None,
}
AUDIO_SITES = {"soundcloud.com", "podcasts.apple.com", "mixcloud.com"}
AUDIO_EXTENSIONS = (".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".flac")
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm", ".mkv")
MAX_FILE_BYTES = 500 * 1024 * 1024
PREFERRED_LANGUAGES = ("ru", "en", "kk")


def _site(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m.", "player."):
        host = host.removeprefix(prefix)
    return host


def media_site(url: str) -> str | None:
    """The platform name if the link is a video/audio page of a known platform."""
    site, path = _site(url), urlparse(url).path
    for name, prefix in MEDIA_SITES.items():
        if (site == name or site.endswith("." + name)) and (prefix is None or path.startswith(prefix)):
            return name
    return None


def is_direct_file(url: str) -> bool:
    return urlparse(url).path.lower().endswith(AUDIO_EXTENSIONS + VIDEO_EXTENSIONS)


def is_media_url(url: str) -> bool:
    return media_site(url) is not None or is_direct_file(url)


def media_id(url: str) -> str:
    return "m-" + hashlib.sha1(url.encode()).hexdigest()[:12]


def _with_query(url: str, key: str, value: str) -> str:
    u = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if k != key] + [(key, value)]
    return urlunparse(u._replace(query=urlencode(query), fragment=""))


def time_link(url: str, sec: float) -> str:
    """The original page opened at a second, where the platform supports it (the frontend mirrors this)."""
    s = int(sec)
    site = _site(url)
    if site.endswith("vimeo.com"):
        return f"{url.split('#')[0]}#t={s}s"
    if site.endswith("dailymotion.com"):
        return _with_query(url, "start", str(s))
    if site.endswith("rutube.ru"):
        return _with_query(url, "t", str(s))
    if site.endswith("twitch.tv"):
        return _with_query(url, "t", f"{s // 3600}h{s % 3600 // 60}m{s % 60}s")
    if is_direct_file(url):
        return f"{url.split('#')[0]}#t={s}"  # media fragment: browsers start the file there
    return url


# ---- subtitles --------------------------------------------------------------------------------

_CUE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def _seconds(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_subtitles(text: str) -> list[dict]:
    """WebVTT or SRT into [{start, duration, text}]; tags and repeated rolling lines are dropped."""
    segments, last = [], None
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _CUE.search(line)
            if not m:
                continue
            start, end = _seconds(*m.groups()[:4]), _seconds(*m.groups()[4:])
            words = " ".join(re.sub(r"<[^>]+>|\{[^}]*\}", "", t).strip() for t in lines[i + 1:])
            words = " ".join(words.split())
            if words and words != last:
                segments.append({"start": round(start, 2), "duration": round(max(0.0, end - start), 2), "text": words})
                last = words
            break
    return segments


def _pick(tracks: dict) -> tuple[str, dict] | None:
    """Best (language, track): ru/en/kk first, then any language; WebVTT or SRT only."""
    def usable(lang):
        return next((t for t in reversed(tracks.get(lang) or []) if t.get("ext") in ("vtt", "srt")), None)

    for lang in [*PREFERRED_LANGUAGES, *sorted(tracks)]:
        base = lang.split("-")[0]
        for key in (lang, *[k for k in tracks if k.split("-")[0] == base]):
            track = usable(key)
            if track:
                return base, track
    return None


# ---- fetching ---------------------------------------------------------------------------------

def _info(url: str) -> dict:
    import yt_dlp

    u = urlparse(url)
    text_sources.check_host(u.hostname or "", u.port or 443)
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
    if config.YOUTUBE_PROXY_URL:
        opts["proxy"] = config.YOUTUBE_PROXY_URL
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist" or info.get("entries"):
                raise UserError("Это ссылка на плейлист или канал. Откройте нужную запись и скопируйте ссылку на неё.")
            if info.get("is_live"):
                raise UserError("Прямые трансляции не поддерживаются — дождитесь записи.")
            for field in ("subtitles", "automatic_captions"):
                picked = _pick(info.get(field) or {})
                if not picked:
                    continue
                lang, track = picked
                try:
                    data = track.get("data") or ydl.urlopen(track["url"]).read().decode("utf-8", errors="replace")
                except Exception as e:  # noqa: BLE001 — no subtitles then: speech recognition still works
                    log.info("субтитры %s не скачались: %s", url, e)
                    continue
                segments = parse_subtitles(data)
                if segments:
                    info["_subtitles"] = (lang, segments, field)
                    break
            return info
    except UserError:
        raise
    except Exception as e:  # yt_dlp.utils.DownloadError and friends
        text = str(e).lower()
        log.warning("yt-dlp %s: %s", url, e)
        if "private" in text or "unavailable" in text or "404" in text or "not found" in text:
            raise UserError("Запись недоступна: она удалена, скрыта или в ссылке ошибка.")
        if "login" in text or "sign in" in text or "registered users" in text:
            raise UserError("Эта запись доступна только после входа на сайте — так её не получить.")
        raise UserError("Не удалось получить запись с этого сайта. Попробуйте позже или вставьте расшифровку текстом.", 503)


def _download_file(url: str, folder: str) -> str:
    """A direct media link, with the same safety checks as articles and a size limit."""
    session = requests.Session()
    session.headers["User-Agent"] = text_sources.USER_AGENT
    current = url
    for _ in range(text_sources.MAX_REDIRECTS + 1):
        u = urlparse(current)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise UserError("Сайт перенаправил на неподдерживаемый адрес.")
        text_sources.check_host(u.hostname, u.port or (443 if u.scheme == "https" else 80))
        try:
            r = session.get(current, allow_redirects=False, timeout=(5, 60), stream=True)
        except requests.RequestException:
            raise UserError("Не удалось скачать файл. Проверьте ссылку.", status=503)
        with r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                current = urljoin(current, r.headers["location"])
                continue
            if r.status_code >= 400:
                raise UserError(f"Сервер с файлом ответил ошибкой {r.status_code}.")
            path = os.path.join(folder, "source" + os.path.splitext(u.path)[1].lower())
            size = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise UserError("Файл слишком большой (больше 500 МБ).")
                    f.write(chunk)
            return path
    raise UserError("Слишком много перенаправлений.")


def fetch_media(url: str) -> dict:
    """{segments, language, source, title, channel, image, duration_sec} for a media link."""
    from tools import whisper
    from tools.youtube_scraper import duration_of

    if is_direct_file(url):
        if not (config.WHISPER_FALLBACK and os.getenv("GROQ_API_KEY")):
            raise UserError("Для файлов по прямой ссылке нужно распознавание речи — оно выключено (WHISPER_FALLBACK).")
        with tempfile.TemporaryDirectory(prefix="videoflow-") as folder:
            data = whisper.transcribe_file(_download_file(url, folder))
        name = os.path.basename(urlparse(url).path)
        return {**data, "title": os.path.splitext(name)[0].replace("_", " ") or name, "channel": _site(url),
                "image": None, "duration_sec": data.get("duration_sec") or duration_of(data["segments"])}

    info = _info(url)
    meta = {"title": info.get("title") or _site(url), "channel": info.get("uploader") or info.get("channel"),
            "image": info.get("thumbnail"), "duration_sec": info.get("duration")}
    subtitles = info.get("_subtitles")
    if subtitles and subtitles[1]:
        lang, segments, field = subtitles
        log.info("%s: субтитры %s (%s), %d сегментов", url, lang, field, len(segments))
        return {**meta, "segments": segments, "language": lang,
                "source": "generated" if field == "automatic_captions" else "manual",
                "duration_sec": meta["duration_sec"] or duration_of(segments)}
    if not (config.WHISPER_FALLBACK and os.getenv("GROQ_API_KEY")):
        raise UserError("У записи нет субтитров, а распознавание речи выключено (WHISPER_FALLBACK).")
    log.info("%s: субтитров нет, распознаю речь", url)
    data = whisper.transcribe_url(url)
    return {**meta, **{k: v for k, v in data.items() if k in ("segments", "language", "source")},
            "duration_sec": meta["duration_sec"] or duration_of(data["segments"])}
