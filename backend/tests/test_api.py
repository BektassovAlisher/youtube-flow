import json

import pytest
from fastapi.testclient import TestClient

import config
import jobs
from api.api import app
from db import cache as repo
from tests_data import seed_video

VID = "IHZwWFHWa-w"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def ndjson(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_processed_video_is_served_from_db_for_any_link(client, youtube, llm):
    seed_video(VID)
    for url in [f"https://www.youtube.com/watch?v={VID}", f"https://youtu.be/{VID}?si=abc123",
                f"https://www.youtube.com/watch?v={VID}&t=120s", f"https://m.youtube.com/watch?feature=share&v={VID}",
                f"https://www.youtube.com/shorts/{VID}"]:
        r = client.post("/videos", json={"video_url": url})
        assert r.status_code == 200 and r.json()["video_id"] == VID and r.json()["jobs"] == []
    assert youtube["transcript"] == 0 and llm.calls == []


def test_new_video_returns_at_once_and_streams_progress(client, youtube, llm):
    r = client.post("/videos", json={"video_url": f"https://youtu.be/{VID}"})
    assert r.status_code == 200
    body = r.json()
    assert body["video_id"] == VID and body["status"] in ("processing", "ready")

    events = ndjson(client.get(f"/videos/{VID}/events"))
    assert events[0]["type"] == "snapshot" and events[-1] == {"type": "idle"}
    jobs.hub.wait(VID, "process", timeout=30)
    video = client.get(f"/videos/{VID}").json()
    assert video["status"] == "ready" and video["summary"] and video["podcast_script"] and video["jobs"] == []


@pytest.mark.parametrize("link, hint", [
    ("просто слова", "Вставьте ссылку на видео, подкаст или статью"),
    ("https://www.youtube.com/playlist?list=PL1", "плейлист"),
    ("ftp://example.com/file", "http:// или https://"),
])
def test_bad_link_is_a_400_in_russian(client, link, hint):
    r = client.post("/videos", json={"url": link})
    assert r.status_code == 400 and hint in r.json()["detail"]


def test_unknown_video_404(client):
    assert client.get("/videos/XXXXXXXXXXX").status_code == 404


def test_token_protects_changes_but_not_reading(client, monkeypatch, youtube, llm):
    seed_video(VID)
    monkeypatch.setattr(config, "API_TOKEN", "secret")
    assert client.get(f"/videos/{VID}").status_code == 200
    assert client.get("/videos").status_code == 200
    r = client.delete(f"/videos/{VID}")
    assert r.status_code == 401 and "войти" in r.json()["detail"]
    assert client.delete(f"/videos/{VID}", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.delete(f"/videos/{VID}", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert repo.get_video(VID) is None


def test_hourly_limit_for_new_videos(client, monkeypatch, youtube, llm):
    monkeypatch.setattr(config, "LIMIT_VIDEOS_PER_HOUR", 2)
    for vid in ("AAAAAAAAAA1", "AAAAAAAAAA2"):
        assert client.post("/videos", json={"video_url": vid}).status_code == 200
        jobs.hub.wait(vid, "process", timeout=30)
    r = client.post("/videos", json={"video_url": "AAAAAAAAAA3"})
    assert r.status_code == 429 and "Слишком много запросов" in r.json()["detail"]
    # already processed videos are free
    assert client.post("/videos", json={"video_url": "AAAAAAAAAA1"}).status_code == 200


def test_library_pagination_and_search(client):
    for i, title in enumerate(["Градиентный спуск", "Линейная алгебра", "Python для начинающих"]):
        vid = f"LIB{i:08d}"
        seed_video(vid)
        repo.save_transcript(vid, [], language="ru", source="manual", duration_sec=60, title=title, channel="Канал")
    r = client.get("/videos", params={"limit": 2})
    assert r.headers["x-total-count"] == "3" and len(r.json()) == 2
    found = client.get("/videos", params={"q": "python"}).json()
    assert [v["title"] for v in found] == ["Python для начинающих"]


def test_audio_job_and_range_requests(client, monkeypatch):
    seed_video(VID)
    import tools.audio_generator as ag

    fake = bytes(range(256)) * 40  # 10 240 bytes
    monkeypatch.setattr(ag, "generate_podcast_audio", lambda script, on_progress=None, client=None: fake)
    r = client.post(f"/videos/{VID}/audio")
    assert r.status_code == 202 and r.json()["job"]["kind"] == "audio"
    jobs.hub.wait(VID, "audio", timeout=30)
    assert client.get(f"/videos/{VID}").json()["audio_ready"] is True
    assert client.post(f"/videos/{VID}/audio").json()["from_cache"] is True

    full = client.get(f"/videos/{VID}/audio")
    assert full.status_code == 200 and full.content == fake and full.headers["accept-ranges"] == "bytes"
    part = client.get(f"/videos/{VID}/audio", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and part.content == fake[100:200]
    assert part.headers["content-range"] == f"bytes 100-199/{len(fake)}"
    tail = client.get(f"/videos/{VID}/audio", headers={"Range": "bytes=-10"})
    assert tail.content == fake[-10:]
    assert client.get(f"/videos/{VID}/audio", headers={"Range": "bytes=99999-"}).status_code == 416
    etag = full.headers["etag"]
    assert client.get(f"/videos/{VID}/audio", headers={"If-None-Match": etag}).status_code == 304


def test_questions_stream_and_cache(client, llm):
    seed_video(VID)
    r = client.post(f"/videos/{VID}/qa/stream", json={"question": "Что такое вес?"})
    events = ndjson(r)
    assert events[0]["type"] == "sources" and events[-1] == {"type": "done", "cached": False}
    r = client.post(f"/videos/{VID}/qa", json={"question": "Что такое вес?"})
    assert r.json()["cached"] is True and r.json()["answer"].startswith("Вес")


def test_question_errors_arrive_inside_the_stream(client, llm, monkeypatch):
    seed_video(VID)
    monkeypatch.setattr(config, "LIMIT_QUESTIONS_PER_HOUR", 1)
    client.post(f"/videos/{VID}/qa", json={"question": "Первый вопрос"})
    events = ndjson(client.post(f"/videos/{VID}/qa/stream", json={"question": "Второй вопрос"}))
    assert events[-1]["type"] == "error" and "Слишком много запросов" in events[-1]["message"]


def test_regenerate_script(client, llm, youtube):
    seed_video(VID)
    r = client.post(f"/videos/{VID}/regenerate", json={"part": "script"})
    assert r.status_code == 200
    jobs.hub.wait(VID, "process", timeout=30)
    assert llm.kinds() == ["script", "critic"]
    assert repo.get_video(VID)["podcast_script"]


def test_rejected_video_offers_processing_anyway(client, llm, youtube):
    llm.classification = '{"category": "music", "is_suitable": false, "confidence": 0.9, "reason": "клип"}'
    client.post("/videos", json={"video_url": VID})
    jobs.hub.wait(VID, "process", timeout=30)
    r = client.post("/videos", json={"video_url": VID})
    assert r.json()["status"] == "rejected" and r.json()["classification"]["reason"] == "клип"
    client.post("/videos", json={"video_url": VID, "force": True})
    jobs.hub.wait(VID, "process", timeout=30)
    assert client.get(f"/videos/{VID}").json()["status"] == "ready"


def test_compat_generate(client, llm, youtube):
    r = client.post("/generate", json={"video_url": f"https://youtu.be/{VID}"})
    body = r.json()
    assert r.status_code == 200 and body["video_id"] == VID and body["summary"] and not body["rejected"]


def test_recommendations_are_cached(client, monkeypatch):
    seed_video(VID)
    from tools import recommendations

    calls = []

    def search(query, sites):
        calls.append(query)
        return [{"title": "Курс", "url": f"https://stepik.org/{len(calls)}"}]

    monkeypatch.setattr(recommendations, "_search", search)
    first = client.post(f"/videos/{VID}/recommend").json()
    assert first["from_cache"] is False and first["courses"] and first["books"]
    assert any("градиентный спуск" in q for q in calls)
    second = client.post(f"/videos/{VID}/recommend").json()
    assert second["from_cache"] is True and len(calls) == 2
    assert client.get(f"/videos/{VID}").json()["recommendation"]["courses"]
