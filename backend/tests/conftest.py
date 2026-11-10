"""Tests run without network and API keys: SQLite, a fake embedding model, fake LLMs and a fake YouTube."""
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="videoflow-tests-")
os.environ.update(
    DATABASE_URL=f"sqlite:///{TMP}/test.db",
    VECTOR_DIR=f"{TMP}/chroma",
    GOOGLE_API_KEY="test", GROQ_API_KEY="test", TAVILY_API_KEY="test", ELEVENLABS_API_KEY="test",
    HF_HUB_OFFLINE="1", WHISPER_FALLBACK="1", API_TOKEN="",
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import pytest  # noqa: E402
from langchain_core.embeddings import DeterministicFakeEmbedding  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402

from agent import agent_state  # noqa: E402
from agent.chat_agent import rag  # noqa: E402
from db.database import Base, engine, migrate  # noqa: E402

rag.set_embeddings(DeterministicFakeEmbedding(size=384), "fake:test")
migrate()

SUMMARY = """## Обзор лекции

Лекция о том, как обучаются **нейронные сети**.

---

## [00:00] Нейроны и веса

**Содержание раздела:**
У каждого **нейрона** есть **веса**, а **функция активации** решает, что передать дальше.

## [10:00] Обучение

**Содержание раздела:**
**Градиентный спуск** уменьшает **функцию потерь**; шаг задаёт **learning rate**. **Градиентный спуск** — основа.

## Все ключевые понятия (сводный глоссарий)
- **Нейрон**: элемент сети.

## Главные выводы лекции
- Обучение — это поиск минимума функции потерь.

## Вопросы для самопроверки
1. Что такое вес нейрона?
2. Зачем нужен градиентный спуск?
"""
SCRIPT = "Алекс: Что такое нейрон?\nМарина: Это элемент сети с весами.\nАлекс: А градиентный спуск?\nМарина: Поиск минимума."


class FakeChat:
    """Answers by prompt type; records every prompt. `fail` maps a prompt type to an exception to raise."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.fail: dict[str, Exception] = {}
        self.critic_verdicts = ['{"is_valid": true, "feedback": "Одобрено"}']
        self.keywords = '["градиентный спуск", "нейрон", "функция потерь", "learning rate", "вес"]'
        self.classification = '{"category": "educational", "is_suitable": true, "confidence": 0.95, "reason": "лекция"}'

    def _kind(self, prompt: str) -> str:
        for key, kind in (("учебных конспектов", "summary"), ("сценарист", "script"), ("классификатор", "classify"),
                          ("подходит ли веб-страница", "classify"),
                          ("Выбери 10-15", "keywords"), ("строгий редактор", "critic"), ("преподаватель", "qa")):
            if key in prompt:
                return kind
        return "other"

    def _answer(self, prompt) -> str:
        prompt = str(prompt)
        kind = self._kind(prompt)
        self.calls.append((kind, prompt))
        if kind in self.fail:
            raise self.fail.pop(kind)
        if kind == "critic":
            return self.critic_verdicts.pop(0) if len(self.critic_verdicts) > 1 else self.critic_verdicts[0]
        return {"summary": SUMMARY, "script": SCRIPT, "classify": self.classification, "keywords": self.keywords,
                "qa": "Вес — это число, на которое умножается вход [00:00]."}.get(kind, "")

    def kinds(self) -> list[str]:
        return [k for k, _ in self.calls]

    def invoke(self, prompt, config=None):
        return AIMessage(content=self._answer(prompt), usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})

    def stream(self, prompt, config=None):
        text = self._answer(prompt)
        pieces = [text[i:i + 40] for i in range(0, len(text), 40)]
        for i, piece in enumerate(pieces):  # like the real API: the token counts come with the last chunk
            usage = {"input_tokens": 1000, "output_tokens": 300, "total_tokens": 1300} if i == len(pieces) - 1 else None
            yield AIMessageChunk(content=piece, usage_metadata=usage)

    async def astream(self, prompt, config=None):
        for chunk in self.stream(prompt):
            yield chunk


SEGMENTS = [
    {"start": i * 6.0, "duration": 6.0,
     "text": f"фраза {i}: нейронная сеть учится, градиентный спуск обновляет веса нейрона"}
    for i in range(200)
]


@pytest.fixture
def llm(monkeypatch):
    fake = FakeChat()
    for name in ("gemini", "gemini_json", "gemini_backup"):
        monkeypatch.setattr(agent_state, name, lambda fake=fake: fake)
    return fake


@pytest.fixture
def youtube(monkeypatch):
    """Fake subtitles and metadata; counts how often YouTube would have been asked."""
    import agent.agent as nodes

    calls = {"transcript": 0, "metadata": 0, "category": None}  # set "category" to what the watch page says

    def get_transcript(video_id):
        calls["transcript"] += 1
        return {"segments": SEGMENTS, "language": "ru", "source": "manual"}

    def fetch_metadata(video_id, timeout=5):
        calls["metadata"] += 1
        return {"title": f"Лекция {video_id}", "channel": "Канал"}

    monkeypatch.setattr(nodes, "get_transcript", get_transcript)
    monkeypatch.setattr(nodes, "fetch_metadata", fetch_metadata)
    monkeypatch.setattr(nodes, "fetch_category", lambda video_id, timeout=5: calls["category"])
    return calls


@pytest.fixture(autouse=True)
def clean_db():
    from api.security import limiter

    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    limiter.reset()
    yield
