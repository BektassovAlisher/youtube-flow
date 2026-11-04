import pytest
from youtube_transcript_api import (
    AgeRestricted, IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled, VideoUnavailable,
)

from errors import UserError, humanize
from tools import youtube_scraper as yt

VID = "aircAruvnKk"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=120s",
    f"https://m.youtube.com/watch?feature=share&v={VID}",
    f"https://music.youtube.com/watch?v={VID}&list=RD123",
    f"https://www.youtube.com/watch?list=PL123&v={VID}",
    f"https://youtu.be/{VID}?si=abc",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/embed/{VID}?start=10",
    f"https://www.youtube-nocookie.com/embed/{VID}",
    f"https://www.youtube.com/live/{VID}",
    f"youtube.com/watch?v={VID}",
    f"  {VID}  ",
])
def test_video_links(url):
    assert yt.parse_video_id(url) == VID


@pytest.mark.parametrize("url, hint", [
    ("https://example.com/articles/how-to-learn-python", "не ссылка на YouTube"),
    ("https://www.youtube.com/playlist?list=PLZHQObOWTQDNU6R1_67000Dx_ZCJB-3pi", "плейлист"),
    ("https://www.youtube.com/@3blue1brown/videos", "канал"),
    ("https://www.youtube.com/c/ProgrammingWithMosh", "канал"),
    ("https://www.youtube.com/watch?v=short", "Не удалось найти видео"),
    ("https://www.youtube.com/", "Не удалось найти видео"),
    ("", "Вставьте ссылку"),
])
def test_bad_links_explain_what_is_wrong(url, hint):
    with pytest.raises(UserError) as e:
        yt.parse_video_id(url)
    assert hint in e.value.message


class FakeTranscript:
    def __init__(self, code, generated=False):
        self.language_code, self.is_generated = code, generated

    def fetch(self):
        snippet = type("S", (), {"start": 1.0, "duration": 2.0, "text": f"текст {self.language_code}"})
        return type("F", (), {"snippets": [snippet], "language_code": self.language_code,
                              "is_generated": self.is_generated})()


class FakeListing:
    def __init__(self, transcripts):
        self.transcripts = transcripts

    def find_transcript(self, codes):
        for code in codes:
            for t in self.transcripts:
                if t.language_code == code:
                    return t
        raise NoTranscriptFound(VID, codes, None)

    def __iter__(self):
        return iter(self.transcripts)


def fake_api(monkeypatch, listing=None, error=None):
    class Api:
        def __init__(self, proxy_config=None):
            pass

        def list(self, video_id):
            if error:
                raise error
            return listing

    monkeypatch.setattr(yt, "YouTubeTranscriptApi", Api)


def test_prefers_ru_en_kk(monkeypatch):
    fake_api(monkeypatch, FakeListing([FakeTranscript("de"), FakeTranscript("en", generated=True)]))
    data = yt.fetch_subtitles(VID)
    assert data["language"] == "en" and data["source"] == "generated"
    assert data["segments"] == [{"start": 1.0, "duration": 2.0, "text": "текст en"}]


def test_falls_back_to_any_language(monkeypatch):
    fake_api(monkeypatch, FakeListing([FakeTranscript("de")]))
    assert yt.fetch_subtitles(VID)["language"] == "de"


def test_no_subtitles_goes_to_whisper(monkeypatch):
    fake_api(monkeypatch, error=TranscriptsDisabled(VID))
    import tools.whisper as whisper

    monkeypatch.setattr(whisper, "transcribe_youtube", lambda vid: {"segments": [], "language": "ru", "source": "whisper"})
    assert yt.get_transcript(VID)["source"] == "whisper"


def test_no_subtitles_without_whisper(monkeypatch):
    fake_api(monkeypatch, error=TranscriptsDisabled(VID))
    monkeypatch.setattr(yt.config, "WHISPER_FALLBACK", False)
    with pytest.raises(UserError, match="нет субтитров"):
        yt.get_transcript(VID)


@pytest.mark.parametrize("error, text", [
    (VideoUnavailable(VID), "Видео недоступно"),
    (AgeRestricted(VID), "возрастное ограничение"),
    (RequestBlocked(VID), "блокирует запросы"),
    (IpBlocked(VID), "блокирует запросы"),
])
def test_youtube_errors_are_in_russian(monkeypatch, error, text):
    fake_api(monkeypatch, error=error)
    with pytest.raises(UserError) as e:
        yt.fetch_subtitles(VID)
    assert text in e.value.message
    assert "github.com" not in e.value.message


def test_humanize():
    class RateLimitError(Exception):
        pass

    class Weird(Exception):
        status_code = 401

    assert "лимит" in humanize(RateLimitError("429"))
    assert "API-ключ" in humanize(Weird())
    assert "не ответил вовремя" in humanize(TimeoutError("timed out"))
    assert humanize(UserError("как есть")) == "как есть"
    assert "Попробуйте ещё раз" in humanize(KeyError("x"))


def test_metadata_unescapes_and_survives_errors(monkeypatch):
    class R:
        ok = True

        @staticmethod
        def json():
            return {"title": "Steve Jobs&#39; speech &amp; more", "author_name": "Stanford"}

    monkeypatch.setattr(yt.requests, "get", lambda *a, **k: R())
    assert yt.fetch_metadata(VID) == {"title": "Steve Jobs' speech & more", "channel": "Stanford"}

    def boom(*a, **k):
        raise yt.requests.ConnectionError("offline")

    monkeypatch.setattr(yt.requests, "get", boom)
    assert yt.fetch_metadata(VID) == {"title": None, "channel": None}
