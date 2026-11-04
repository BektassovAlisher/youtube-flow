"""Recordings from other sites and media files: subtitles when there are any, otherwise speech recognition."""
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import config
import jobs
from api.api import app
from errors import UserError
from tools import media, whisper

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.500
<c.colorE5E5E5>Сегодня разберём</c> градиентный спуск

00:00:04.500 --> 00:00:04.600
<c.colorE5E5E5>Сегодня разберём</c> градиентный спуск

00:01:05.250 --> 00:01:09.000 align:start position:0%
{\\an8}Шаг обучения задаёт <i>learning rate</i>
"""
SRT = """1
00:00:02,000 --> 00:00:05,000
Hello and welcome

2
01:02:03,500 --> 01:02:07,000
Final words
"""


def test_parse_subtitles():
    assert media.parse_subtitles(VTT) == [
        {"start": 1.0, "duration": 3.5, "text": "Сегодня разберём градиентный спуск"},  # the rolling repeat is gone
        {"start": 65.25, "duration": 3.75, "text": "Шаг обучения задаёт learning rate"},
    ]
    assert media.parse_subtitles(SRT)[1] == {"start": 3723.5, "duration": 3.5, "text": "Final words"}


def test_subtitle_track_choice():
    tracks = {"de": [{"ext": "vtt", "url": "de"}], "en-US": [{"ext": "json3", "url": "x"}, {"ext": "vtt", "url": "en"}],
              "fr": [{"ext": "ttml", "url": "fr"}]}
    assert media._pick(tracks) == ("en", {"ext": "vtt", "url": "en"})  # en before de, vtt/srt only
    assert media._pick({"ru": [{"ext": "srt", "url": "ru"}], "en": [{"ext": "vtt", "url": "en"}]})[0] == "ru"
    assert media._pick({"fr": [{"ext": "ttml"}]}) is None


@pytest.mark.parametrize("url, link", [
    ("https://vimeo.com/76979871", "https://vimeo.com/76979871#t=95s"),
    ("https://rutube.ru/video/abc/?r=wd", "https://rutube.ru/video/abc/?r=wd&t=95"),
    ("https://www.dailymotion.com/video/x8", "https://www.dailymotion.com/video/x8?start=95"),
    ("https://www.twitch.tv/videos/123", "https://www.twitch.tv/videos/123?t=0h1m35s"),
    ("https://cdn.example.com/ep1.mp3", "https://cdn.example.com/ep1.mp3#t=95"),
    ("https://soundcloud.com/a/b", "https://soundcloud.com/a/b"),
])
def test_time_links(url, link):
    assert media.time_link(url, 95.7) == link


class FakeYDL:
    info: dict = {}
    error: Exception | None = None

    def __init__(self, opts):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if FakeYDL.error:
            raise FakeYDL.error
        return dict(FakeYDL.info)

    def urlopen(self, url):
        return type("R", (), {"read": lambda self: VTT.encode()})()


@pytest.fixture
def ydl(monkeypatch):
    import yt_dlp

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(media.text_sources, "check_host", lambda host, port: None)
    FakeYDL.error = None
    FakeYDL.info = {"title": "Лекция на Vimeo", "uploader": "Школа", "duration": 70, "thumbnail": "https://i.vimeocdn.com/t.jpg",
                    "subtitles": {"ru": [{"ext": "vtt", "url": "https://captions/ru.vtt"}]}}
    return FakeYDL


def test_recording_with_subtitles(ydl):
    rec = media.fetch_media("https://vimeo.com/76979871")
    assert rec["source"] == "manual" and rec["language"] == "ru" and len(rec["segments"]) == 2
    assert rec["title"] == "Лекция на Vimeo" and rec["channel"] == "Школа" and rec["image"].startswith("https://")
    assert rec["duration_sec"] == 70


def test_recording_without_subtitles_is_recognized(ydl, monkeypatch):
    ydl.info = {**ydl.info, "subtitles": {}, "automatic_captions": {}}
    monkeypatch.setattr(whisper, "transcribe_url", lambda url: {"segments": [{"start": 0.0, "duration": 5.0, "text": "речь"}],
                                                                "language": "ru", "source": "whisper"})
    rec = media.fetch_media("https://soundcloud.com/a/b")
    assert rec["source"] == "whisper" and rec["segments"][0]["text"] == "речь" and rec["title"] == "Лекция на Vimeo"


@pytest.mark.parametrize("info, error, hint", [
    ({"_type": "playlist", "entries": [{}]}, None, "плейлист или канал"),
    ({"is_live": True}, None, "Прямые трансляции"),
    (None, Exception("ERROR: [vimeo] 123: This video is private"), "Запись недоступна"),
    (None, Exception("ERROR: Only registered users can see this video"), "после входа"),
    (None, Exception("ERROR: unexpected HTML"), "Не удалось получить запись"),
])
def test_recording_errors(ydl, info, error, hint):
    ydl.info, ydl.error = info or {}, error
    with pytest.raises(UserError) as e:
        media.fetch_media("https://vimeo.com/1")
    assert hint in e.value.message


def test_platform_link_to_internal_network_is_refused(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", 443))])
    with pytest.raises(UserError, match="внутреннюю сеть"):
        media.fetch_media("https://vimeo.com/1")


# ---- a media file by direct link: our own download, ffmpeg pieces, Whisper ---------------------

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")


@pytest.fixture(scope="module")
def mp3_site(tmp_path_factory):
    path = tmp_path_factory.mktemp("media") / "ep.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=25",
                    "-ac", "1", "-b:a", "64k", str(path)], check=True)
    data = path.read_bytes()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/podcast/lecture_one.mp3"
    server.shutdown()


class FakeGroq:
    def __init__(self):
        self.audio = self
        self.transcriptions = self
        self.pieces = []

    def create(self, file, model, response_format, temperature):
        self.pieces.append(file[0])
        return type("T", (), {"model_dump": lambda self: {"language": "russian", "segments": [
            {"start": 1.0, "end": 4.0, "text": " первая фраза"}, {"start": 6.0, "end": 9.5, "text": " вторая фраза"}]}})()


@needs_ffmpeg
def test_media_file_by_direct_link(mp3_site, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)
    monkeypatch.setattr(whisper, "CHUNK_SECONDS", 10)  # 25 s -> pieces at 0, 10 and 20 s
    groq = FakeGroq()
    monkeypatch.setattr(whisper, "_client", lambda client: groq)
    rec = media.fetch_media(mp3_site)
    assert len(groq.pieces) == 3
    assert [s["start"] for s in rec["segments"]] == [1.0, 6.0, 11.0, 16.0, 21.0, 26.0]
    assert rec["language"] == "ru" and rec["source"] == "whisper" and rec["title"] == "lecture one"
    assert rec["channel"] == "127.0.0.1" and abs(rec["duration_sec"] - 25) < 1  # the file's length, not the last phrase


@needs_ffmpeg
def test_media_file_on_internal_address_is_refused(mp3_site):
    with pytest.raises(UserError, match="внутреннюю сеть"):
        media.fetch_media(mp3_site)


# ---- the whole pipeline --------------------------------------------------------------------------

def test_recording_pipeline_links_to_seconds(llm, youtube, monkeypatch):
    import asyncio

    import agent.agent as nodes
    from agent.chat_agent import rag
    from conftest import SEGMENTS

    monkeypatch.setattr(nodes, "fetch_media", lambda url: {"segments": SEGMENTS, "language": "ru", "source": "manual",
                                                          "title": "Лекция", "channel": "Школа", "image": None,
                                                          "duration_sec": 1200.0})
    with TestClient(app) as client:
        body = client.post("/videos", json={"url": "https://vimeo.com/76979871"}).json()
        vid = body["video_id"]
        assert body["kind"] == "media" and vid.startswith("m-")
        jobs.hub.wait(vid, "process", timeout=30)
        video = client.get(f"/videos/{vid}").json()
    assert video["status"] == "ready" and video["duration_sec"] == 1200.0 and youtube["transcript"] == 0
    assert "[00:00]" in dict(llm.calls)["summary"]  # the timed prompt, as for YouTube

    async def ask():
        return [e async for e in rag.answer_events(vid, "Что такое веса?")]

    sources = asyncio.run(ask())[0]["sources"]
    assert sources and all(s["url"].startswith("https://vimeo.com/76979871#t=") for s in sources)
    assert "эту запись" in [p for k, p in llm.calls if k == "qa"][-1]


def test_subtitles_that_fail_to_download_fall_back_to_speech(ydl, monkeypatch):
    def broken(self, url):
        raise OSError("connection reset")

    monkeypatch.setattr(FakeYDL, "urlopen", broken)
    monkeypatch.setattr(whisper, "transcribe_url", lambda url: {"segments": [{"start": 0.0, "duration": 5.0, "text": "речь"}],
                                                                "language": "ru", "source": "whisper"})
    assert media.fetch_media("https://vimeo.com/1")["source"] == "whisper"
