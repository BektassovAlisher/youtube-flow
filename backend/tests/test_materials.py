"""Articles and pasted text go through the same pipeline as videos, with paragraphs instead of timestamps."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import jobs
from agent.chat_agent import rag
from api.api import app
from db import cache as repo
from tools import text_sources

URL = "https://habr.com/ru/articles/123456/"
AID = text_sources.article_id(URL)
ARTICLE = (Path(__file__).parent / "fixtures" / "article.html").read_bytes()
PASTED = ("# Что такое градиент\n\n" + "Градиент показывает направление самого быстрого роста функции. " * 6
          + "\n\n## Шаг обучения\n\n" + "Learning rate задаёт длину шага градиентного спуска. " * 6)


@pytest.fixture
def article(monkeypatch):
    import agent.agent as nodes

    calls = []

    def fetch(url):
        calls.append(url)
        return text_sources.extract(ARTICLE, url)

    monkeypatch.setattr(nodes, "fetch_article", fetch)
    return calls


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_article_pipeline(client, llm, youtube, article):
    r = client.post("/videos", json={"url": URL + "?utm_source=telegram"})
    assert r.status_code == 200 and r.json()["video_id"] == AID and r.json()["kind"] == "article"
    jobs.hub.wait(AID, "process", timeout=30)

    video = client.get(f"/videos/{AID}").json()
    assert video["status"] == "ready" and video["title"] == "Градиентный спуск простыми словами"
    assert video["channel"] == "Хабр" and video["image_url"] == "https://habrastorage.org/cover.png"
    assert video["word_count"] > 100 and video["anchors"]["2"].startswith("Представьте")
    assert video["url"] == URL and article == [URL] and youtube["transcript"] == 0

    prompts = dict(llm.calls)
    assert "Сайт: Хабр" in prompts["classify"] and "веб-страница" in prompts["classify"]
    assert "текст статьи" in prompts["summary"] and "[¶2] Представьте" in prompts["summary"]
    assert "## Формула и шаг обучения" in prompts["summary"]  # the original's sections are kept
    assert llm.kinds() == ["classify", "summary", "keywords"]


def test_article_answers_point_at_paragraphs(client, llm, youtube, article):
    client.post("/videos", json={"url": URL})
    jobs.hub.wait(AID, "process", timeout=30)

    async def ask():
        return [e async for e in rag.answer_events(AID, "Что такое learning rate?")]

    events = asyncio.run(ask())
    sources = events[0]["sources"]
    assert all(s["timestamp"].startswith("¶") for s in sources)
    assert all(s["url"].startswith(URL + "#:~:text=") for s in sources)
    qa_prompt = [p for k, p in llm.calls if k == "qa"][-1]
    assert "эту статью" in qa_prompt and "[¶N]" in qa_prompt and "[MM:SS]" not in qa_prompt


def test_not_educational_article(client, llm, youtube, article):
    llm.classification = '{"category": "advertising", "is_suitable": false, "confidence": 0.9, "reason": "реклама"}'
    client.post("/videos", json={"url": URL})
    jobs.hub.wait(AID, "process", timeout=30)
    video = client.get(f"/videos/{AID}").json()
    assert video["status"] == "rejected" and video["classification"]["category"] == "advertising"
    client.post("/videos", json={"url": URL, "force": True})
    jobs.hub.wait(AID, "process", timeout=30)
    assert client.get(f"/videos/{AID}").json()["status"] == "ready"


def test_article_download_error_is_shown(client, llm, youtube, monkeypatch):
    import agent.agent as nodes
    from errors import UserError

    def paywall(url):
        raise UserError(text_sources.PAYWALL)

    monkeypatch.setattr(nodes, "fetch_article", paywall)
    client.post("/videos", json={"url": URL})
    jobs.hub.wait(AID, "process", timeout=30)
    video = client.get(f"/videos/{AID}").json()
    assert video["status"] == "failed" and "подписка" in video["error"]


def test_pasted_text_pipeline(client, llm, youtube):
    r = client.post("/videos", json={"text": PASTED, "title": "  "})
    body = r.json()
    tid = body["video_id"]
    assert r.status_code == 200 and tid.startswith("t-") and body["kind"] == "text"
    assert body["title"] == "Что такое градиент" and body["url"] == ""
    jobs.hub.wait(tid, "process", timeout=30)

    video = client.get(f"/videos/{tid}").json()
    assert video["status"] == "ready" and video["summary"] and video["keywords"]
    assert "classify" not in llm.kinds()  # pasted on purpose: no filtering
    assert "учебного материала" in dict(llm.calls)["summary"]

    source = client.get(f"/videos/{tid}/source").json()["segments"]
    assert source[0]["section"] == "Что такое градиент" and source[-1]["section"] == "Шаг обучения"

    llm.calls.clear()
    again = client.post("/videos", json={"text": PASTED + "\n"}).json()  # same text: served from the database
    assert again["video_id"] == tid and again["jobs"] == [] and llm.calls == []

    async def ask():
        return [e async for e in rag.answer_events(tid, "Что задаёт learning rate?")]

    sources = asyncio.run(ask())[0]["sources"]
    assert sources and all(s["url"].startswith("#p") for s in sources)


def test_pasted_text_title_and_errors(client, llm):
    r = client.post("/videos", json={"text": "Слишком мало."})
    assert r.status_code == 400 and "слишком короткий" in r.json()["detail"]
    r = client.post("/videos", json={"text": PASTED, "title": "Мои заметки"})
    assert r.json()["title"] == "Мои заметки"
    jobs.hub.wait(r.json()["video_id"], "process", timeout=30)


def test_source_is_only_for_pasted_text(client, llm, youtube, article):
    client.post("/videos", json={"url": URL})
    jobs.hub.wait(AID, "process", timeout=30)
    assert client.get(f"/videos/{AID}/source").status_code == 404


def test_library_shows_kinds(client, llm, youtube, article):
    client.post("/videos", json={"url": URL})
    jobs.hub.wait(AID, "process", timeout=30)
    items = client.get("/videos").json()
    assert items[0]["kind"] == "article" and items[0]["image_url"] and items[0]["word_count"]
    assert repo.get_video(AID)["kind"] == "article"


def test_resume_keeps_the_summary_of_pasted_text(client, llm, youtube):
    llm.fail["keywords"] = RuntimeError("429 Resource exhausted")  # the terms fall back to frequent ones
    tid = client.post("/videos", json={"text": PASTED}).json()["video_id"]
    jobs.hub.wait(tid, "process", timeout=30)
    repo.clear_for_regenerate(tid, "summary")
    repo.set_stage(tid, "summary")  # as if the run broke after the transcript
    llm.fail.clear()
    llm.calls.clear()
    client.post(f"/videos/{tid}/resume")
    jobs.hub.wait(tid, "process", timeout=30)
    video = client.get(f"/videos/{tid}").json()
    assert llm.kinds() == ["summary", "keywords"] and video["summary"] and video["keywords"]
