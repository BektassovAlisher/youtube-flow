"""Speech recognition for recordings without subtitles: yt-dlp downloads the audio track (or a media file is
given), ffmpeg cuts it into 10-minute mono 16 kHz pieces and Groq Whisper transcribes them in parallel."""
import glob
import logging
import math
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

import config
from errors import UserError, require_env
from tools.youtube_scraper import BLOCKED, watch_url

log = logging.getLogger(__name__)

CHUNK_SECONDS = 600
PARALLEL = 3
LANGUAGE_CODES = {"russian": "ru", "english": "en", "kazakh": "kk", "ukrainian": "uk", "german": "de",
                  "french": "fr", "spanish": "es", "turkish": "tr", "uzbek": "uz", "chinese": "zh"}


def _download(url: str, folder: str) -> tuple[str, dict]:
    import yt_dlp

    opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(folder, "source.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
    }
    if config.YOUTUBE_PROXY_URL:
        opts["proxy"] = config.YOUTUBE_PROXY_URL
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get("duration") or 0
            if duration > config.WHISPER_MAX_MINUTES * 60:
                raise UserError(f"Субтитров нет, а распознавать речь в записях длиннее "
                                f"{config.WHISPER_MAX_MINUTES} минут слишком долго.")
            ydl.process_ie_result(info, download=True)
    except UserError:
        raise
    except Exception as e:  # yt_dlp.utils.DownloadError and friends
        text = str(e).lower()
        log.warning("yt-dlp %s: %s", url, e)
        if "not a bot" in text or "sign in" in text or "429" in text:
            raise UserError(BLOCKED, status=503)
        if "private" in text or "unavailable" in text:
            raise UserError("Запись недоступна: она удалена, скрыта или в ссылке ошибка.")
        raise UserError("Субтитров нет, а скачать звук для распознавания речи не получилось.", 503)
    files = glob.glob(os.path.join(folder, "source.*"))
    if not files:
        raise UserError("Субтитров нет, а скачать звук для распознавания речи не получилось.", 503)
    return files[0], info


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out or 0)


def _cut(source: str, folder: str, index: int) -> str:
    """One mono 16 kHz 32 kbps piece: ~2.4 MB per 10 minutes, far below Whisper's upload limit."""
    out = os.path.join(folder, f"chunk{index:03d}.mp3")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", str(index * CHUNK_SECONDS), "-t", str(CHUNK_SECONDS), "-i", source,
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", out],
        check=True, capture_output=True,
    )
    return out


def _transcribe_piece(client, path: str, offset: float) -> tuple[list[dict], str | None]:
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model=config.WHISPER_MODEL,
            response_format="verbose_json",
            temperature=0.0,
        )
    data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
    segments = []
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if text:
            start = float(seg.get("start", 0))
            segments.append({"start": round(offset + start, 2),
                             "duration": round(max(0.0, float(seg.get("end", start)) - start), 2),
                             "text": text})
    if not segments and (data.get("text") or "").strip():
        segments = [{"start": offset, "duration": float(CHUNK_SECONDS), "text": data["text"].strip()}]
    return segments, data.get("language")


def _language_code(name: str | None) -> str:
    if not name:
        return "ru"
    name = name.strip().lower()
    return name if len(name) == 2 else LANGUAGE_CODES.get(name, name[:2])


def _transcribe(source: str, duration: float, folder: str, client) -> dict:
    pieces = max(1, math.ceil(duration / CHUNK_SECONDS))

    def work(i: int):
        return _transcribe_piece(client, _cut(source, folder, i), i * CHUNK_SECONDS)

    try:
        with ThreadPoolExecutor(PARALLEL) as pool:
            results = list(pool.map(work, range(pieces)))
    except subprocess.CalledProcessError as e:
        log.error("ffmpeg: %s", e.stderr)
        raise UserError("Не удалось подготовить звук к распознаванию (ffmpeg).", status=500)
    segments = [s for part, _ in results for s in part]
    if not segments:
        raise UserError("В записи не удалось распознать речь.")
    language = next((lang for _, lang in results if lang), None)
    return {"segments": segments, "language": _language_code(language), "source": "whisper"}


def _client(client):
    from groq import Groq

    return client or Groq(api_key=require_env("GROQ_API_KEY"), max_retries=3, timeout=300)


def transcribe_url(url: str, client=None) -> dict:
    """A page yt-dlp can download (a YouTube video, a Vimeo video, a podcast episode…)."""
    client = _client(client)
    with tempfile.TemporaryDirectory(prefix="videoflow-") as folder:
        source, info = _download(url, folder)
        data = _transcribe(source, info.get("duration") or _probe_duration(source), folder, client)
    return {**data, "title": info.get("title"), "channel": info.get("uploader") or info.get("channel")}


def transcribe_file(path: str, client=None) -> dict:
    """A media file already on disk."""
    client = _client(client)
    duration = _probe_duration(path)
    if duration > config.WHISPER_MAX_MINUTES * 60:
        raise UserError(f"Распознавать речь в записях длиннее {config.WHISPER_MAX_MINUTES} минут слишком долго.")
    with tempfile.TemporaryDirectory(prefix="videoflow-") as folder:
        return {**_transcribe(path, duration, folder, client), "duration_sec": round(duration, 2)}


def transcribe_youtube(video_id: str, client=None) -> dict:
    return transcribe_url(watch_url(video_id), client)
