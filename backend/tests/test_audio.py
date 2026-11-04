import shutil
import subprocess
import threading
import time

import pytest

from errors import UserError
from tools import audio_generator, mp3

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")


def make_clip(tmp_path, i: int, seconds: float = 2.0, id3: bool = True) -> bytes:
    """A clip shaped like ElevenLabs' mp3_44100_128: mono, 44.1 kHz, 128 kbit/s, with a LAME Info frame."""
    path = tmp_path / f"clip{i}.mp3"
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={300 + 40 * i}:duration={seconds}",
           "-ar", "44100", "-ac", "1", "-b:a", "128k"]
    cmd += ["-metadata", f"title=line {i}", "-id3v2_version", "3"] if id3 else ["-write_id3v2", "0"]
    subprocess.run(cmd + [str(path)], check=True)
    return path.read_bytes()


def probe(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=bit_rate,channels:format=duration",
                          "-of", "default=nw=1", str(path)], capture_output=True, text=True, check=True).stdout
    return dict(line.split("=", 1) for line in out.split())


@needs_ffmpeg
def test_concat_keeps_quality_and_duration(tmp_path):
    clips = [make_clip(tmp_path, i, id3=i % 2 == 0) for i in range(5)]
    out = tmp_path / "joined.mp3"
    out.write_bytes(mp3.concat(clips))
    info = probe(out)
    assert info["bit_rate"] == "128000" and info["channels"] == "1"  # no re-encode to 64 kbit/s
    assert abs(float(info["duration"]) - 10.0) < 0.3  # all five clips, not the first clip's Info header
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-f", "null", "-"], capture_output=True, text=True)
    assert decode.returncode == 0 and decode.stderr == ""
    assert b"ID3" not in out.read_bytes()[:10] and b"Info" not in out.read_bytes()[:200]


def test_concat_rejects_garbage():
    with pytest.raises(ValueError):
        mp3.concat([b"not an mp3 at all" * 10])


def test_parse_script():
    lines = audio_generator.parse_script("**Алекс:** Привет!\nремарка без имени\nМарина: Здравствуй\nAlex: hi\nБорис: кто?")
    assert [text for _, text in lines] == ["Привет!", "Здравствуй", "hi"]


class FakeElevenLabs:
    def __init__(self, clips, fail_on=None, errors=None):
        self.clips, self.fail_on, self.errors = clips, fail_on, list(errors or [])
        self.active = self.peak = self.calls = 0
        self.lock = threading.Lock()
        self.text_to_speech = self

    def convert(self, voice_id, text, model_id, output_format, previous_text=None, next_text=None):
        with self.lock:
            self.calls += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(0.05)
            if self.errors:
                raise self.errors.pop(0)
            if text == self.fail_on:
                raise type("ApiError", (Exception,), {"status_code": 422})("bad text")
            return iter([self.clips[int(text.split()[-1])]])
        finally:
            with self.lock:
                self.active -= 1


@needs_ffmpeg
def test_lines_are_voiced_in_parallel_in_order(tmp_path, monkeypatch):
    clips = [make_clip(tmp_path, i, seconds=1.0) for i in range(6)]
    script = "\n".join(f"{'Алекс' if i % 2 == 0 else 'Марина'}: реплика {i}" for i in range(6))
    client = FakeElevenLabs(clips)
    monkeypatch.setattr(audio_generator.config, "TTS_CONCURRENCY", 3)
    progress = []
    audio = audio_generator.generate_podcast_audio(script, on_progress=lambda d, t: progress.append((d, t)), client=client)
    assert client.peak == 3
    assert progress[0] == (0, 6) and progress[-1] == (6, 6)
    assert audio == mp3.concat(clips)  # order of the script, whatever order the requests finished in


@needs_ffmpeg
def test_rate_limited_line_is_retried(tmp_path, monkeypatch):
    clips = [make_clip(tmp_path, 0, seconds=0.5)]
    busy = type("ApiError", (Exception,), {"status_code": 429})("too_many_concurrent_requests")
    client = FakeElevenLabs(clips, errors=[busy])
    monkeypatch.setattr(audio_generator.time, "sleep", lambda s: None)
    audio_generator.generate_podcast_audio("Алекс: реплика 0", client=client)
    assert client.calls == 2


@needs_ffmpeg
def test_a_failed_line_fails_the_whole_podcast(tmp_path):
    clips = [make_clip(tmp_path, i, seconds=0.5) for i in range(3)]
    client = FakeElevenLabs(clips, fail_on="реплика 1")
    with pytest.raises(UserError, match="не смог озвучить"):
        audio_generator.generate_podcast_audio("Алекс: реплика 0\nМарина: реплика 1\nАлекс: реплика 2", client=client)


def test_script_without_hosts():
    with pytest.raises(UserError, match="нет реплик"):
        audio_generator.generate_podcast_audio("просто текст", client=object())
