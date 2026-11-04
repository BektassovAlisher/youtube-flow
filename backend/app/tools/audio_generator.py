"""Two-voice podcast from the script: lines are voiced in parallel by ElevenLabs and glued without re-encoding."""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import config
from errors import UserError, require_env
from tools import mp3

log = logging.getLogger(__name__)

VOICES = {
    "алекс": "pNInz6obpgDQGcFmaJgB", "alex": "pNInz6obpgDQGcFmaJgB",
    "марина": "EXAVITQu4vr4xnSDxMaL", "marina": "EXAVITQu4vr4xnSDxMaL",
}
MODEL = "eleven_multilingual_v2"
OUTPUT_FORMAT = "mp3_44100_128"
ATTEMPTS = 4


def parse_script(script: str) -> list[tuple[str, str]]:
    """[(voice_id, text)] for every "Name: text" line of a known host ("**Алекс:** текст" too)."""
    lines = []
    for raw in (script or "").splitlines():
        if ":" not in raw:
            continue
        name, text = raw.split(":", 1)
        name = re.sub(r"[*_#>\s]+", " ", name).strip().lower()
        text = text.strip(" *_")
        if text and name in VOICES:
            lines.append((VOICES[name], text))
    return lines


def _status(e: Exception) -> int | None:
    code = getattr(e, "status_code", None)
    return code if isinstance(code, int) else None


def _voice(client, voice_id: str, text: str, previous: str | None, following: str | None) -> bytes:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            stream = client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                model_id=MODEL,
                output_format=OUTPUT_FORMAT,
                previous_text=previous,  # neighbouring lines keep the intonation natural across separate requests
                next_text=following,
            )
            return b"".join(stream)
        except Exception as e:  # noqa: BLE001
            status = _status(e)
            body = str(getattr(e, "body", "") or e).lower()
            if status == 401:
                raise UserError("ElevenLabs отклонил API-ключ. Проверьте ELEVENLABS_API_KEY.", status=503)
            if "quota" in body or status == 402:
                raise UserError("Закончился лимит символов ElevenLabs. Озвучка снова заработает, когда он пополнится.", 503)
            retryable = status in (None, 429, 500, 502, 503, 504)
            if not retryable or attempt == ATTEMPTS:
                log.error("ElevenLabs: %s", e)
                raise UserError("ElevenLabs не смог озвучить реплику. Попробуйте ещё раз позже.", status=503)
            time.sleep(min(8, 2 ** attempt))  # also covers "too many concurrent requests"
    raise AssertionError("unreachable")


def generate_podcast_audio(script: str, on_progress: Callable[[int, int], None] | None = None, client=None) -> bytes:
    """MP3 of the whole dialogue. Raises instead of returning a podcast with missing lines."""
    lines = parse_script(script)
    if not lines:
        raise UserError("В сценарии нет реплик ведущих, озвучивать нечего.")
    if client is None:
        from elevenlabs.client import ElevenLabs

        client = ElevenLabs(api_key=require_env("ELEVENLABS_API_KEY"))

    total = len(lines)
    parts: list[bytes | None] = [None] * total
    done = 0
    if on_progress:
        on_progress(0, total)
    with ThreadPoolExecutor(config.TTS_CONCURRENCY) as pool:
        futures = {
            pool.submit(
                _voice, client, voice, text,
                lines[i - 1][1] if i > 0 else None,
                lines[i + 1][1] if i + 1 < total else None,
            ): i
            for i, (voice, text) in enumerate(lines)
        }
        try:
            for future in as_completed(futures):
                parts[futures[future]] = future.result()
                done += 1
                if on_progress:
                    on_progress(done, total)
        except BaseException:
            for f in futures:
                f.cancel()
            raise
    try:
        audio = mp3.concat(parts)  # type: ignore[arg-type]
    except ValueError:
        raise UserError("ElevenLabs вернул повреждённый звук. Попробуйте ещё раз.", status=503)
    log.info("аудио: %d реплик, %d КБ", total, len(audio) // 1024)
    return audio
