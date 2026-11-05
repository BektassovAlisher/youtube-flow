import asyncio

import pytest
from langchain_core.documents import Document

from agent.chat_agent import rag
from db import cache as repo
from errors import UserError
from tests_data import seed_video

VID = "RRRRRRRRRRR"


@pytest.fixture(autouse=True)
def fresh_index():
    rag.delete_video_index(VID)  # collections live on disk across tests, the database does not


def collect(video_id, question, history=None, charge=None):
    async def go():
        return [e async for e in rag.answer_events(video_id, question, history, charge)]

    return asyncio.run(go())


def test_tokenizer_matches_word_forms():
    assert rag.tokenize("Что такое нейронные сети?") == rag.tokenize("нейронная сеть")
    assert rag.tokenize("Learning rates") == rag.tokenize("learning rate")
    assert rag.tokenize("что такое это и в видео") == []


def test_bm25_finds_inflected_words():
    seed_video(VID)
    filler = ["Сегодня поговорим о погоде и о планах на выходные.", "Кофе лучше пить без сахара.",
              "Поезд прибывает на третий путь.", "В саду распустились розы.", "Футбольный матч перенесли."]
    segments = [{"start": i * 60.0, "duration": 5, "text": t * 12} for i, t in enumerate(filler)]
    segments.append({"start": 600.0, "duration": 5, "text": "Нейронная сеть состоит из слоёв нейронов с весами. " * 12})
    rag.index_video(VID, segments)
    index, docs = rag._lexical_index(VID)
    scores = index.get_scores(rag.tokenize("Что такое нейронные сети?"))
    best = max(range(len(docs)), key=lambda i: scores[i])
    assert "Нейронная сеть" in docs[best].page_content and scores[best] > 0


def test_retrieve_is_chronological():
    seed_video(VID)
    docs = rag.retrieve(VID, "градиентный спуск", k=4)
    starts = [d.metadata["start_seconds"] for d in docs]
    assert starts == sorted(starts) and len(docs) == 4


def test_old_index_is_reembedded(monkeypatch):
    seed_video(VID, transcript=False)
    old = rag._chroma().create_collection(rag._collection_name(VID))  # as written by the previous version
    old.add(ids=["a", "b"], documents=["первый фрагмент", "второй фрагмент"], embeddings=[[0.1] * 384, [0.2] * 384],
            metadatas=[{"chunk_index": 0, "start_seconds": 0, "timestamp": "00:00"},
                       {"chunk_index": 1, "start_seconds": 30, "timestamp": "00:30"}])
    rag.ensure_index(VID)
    collection = rag._chroma().get_collection(rag._collection_name(VID))
    assert collection.metadata["embedder"] == rag.EMBEDDER_ID and collection.count() == 2
    assert repo.get_video(VID)["indexed"]


def test_no_transcript_and_no_index():
    seed_video(VID, transcript=False)
    rag.delete_video_index(VID)
    with pytest.raises(UserError, match="нет текста для поиска"):
        rag.ensure_index(VID)


def test_answer_is_streamed_then_cached(llm):
    seed_video(VID)
    charged = []
    events = collect(VID, "Что такое вес?", charge=lambda: charged.append(1))
    assert [e["type"] for e in events][0] == "sources" and events[-1] == {"type": "done", "cached": False}
    assert "".join(e["text"] for e in events if e["type"] == "token").startswith("Вес")
    prompt = dict(llm.calls)["qa"]
    assert "## Обзор лекции" in prompt and "## [10:00] Обучение" in prompt  # the summary outline is in the context
    assert "Вопросы для самопроверки" not in prompt

    llm.calls.clear()
    again = collect(VID, "  что такое ВЕС ", charge=lambda: charged.append(1))
    assert again[-1] == {"type": "done", "cached": True} and llm.calls == []
    assert charged == [1]  # cached answers are free


def test_follow_up_questions_use_history_and_skip_cache(llm):
    seed_video(VID)
    collect(VID, "Что такое вес?")
    llm.calls.clear()
    events = collect(VID, "А подробнее?", history=[{"q": "Что такое вес?", "a": "Число для входа."}])
    assert events[-1]["cached"] is False
    prompt = dict(llm.calls)["qa"]
    assert "ПРЕДЫДУЩИЕ ВОПРОСЫ" in prompt and "Число для входа." in prompt
    assert repo.get_answer(VID, rag.question_key("А подробнее?")) is None


def test_summary_outline():
    from conftest import SUMMARY

    outline = rag.summary_outline(SUMMARY)
    assert "Лекция о том, как обучаются" in outline and "## [00:00] Нейроны и веса" in outline
    assert "Обучение — это поиск минимума" in outline
    assert "функция активации" not in outline.lower()  # section bodies are left out
    assert "Что такое вес нейрона" not in outline


def test_rrf_prefers_documents_found_by_both():
    a, b, c = (Document(page_content=t, metadata={"chunk_index": i}) for i, t in enumerate("abc"))
    assert rag.reciprocal_rank_fusion([[a, b], [b, c]], k=2)[0] is b


@pytest.mark.parametrize("raw, clean", [
    ("Привет! Отличный вопрос, который как раз бьет в самую суть нашего материала. Вес — это число.", "Вес — это число."),
    ("Привет! Отличный вопрос. Давай разберемся с циклом ReAct.", "Давай разберемся с циклом ReAct."),
    ("Здравствуйте! Хороший вопрос! Градиент показывает направление.", "Градиент показывает направление."),
    ("Вес — это число. Отличный вопрос лектор задал в конце.", "Вес — это число. Отличный вопрос лектор задал в конце."),
    ("Приветствие в начале лекции длится минуту.", "Приветствие в начале лекции длится минуту."),
])
def test_greeting_and_compliment_are_cut(raw, clean):
    assert rag.strip_preamble(raw) == clean


def test_greeting_is_cut_from_streamed_and_cached_answers(llm, monkeypatch):
    seed_video(VID)
    monkeypatch.setattr(llm, "_answer", lambda prompt: "Привет! Отличный вопрос. Вес — это число, на которое умножается вход [00:00].")
    events = collect(VID, "Что такое вес?")
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text.startswith("Вес — это число") and "Привет" not in text
    assert not repo.get_answer(VID, rag.question_key("Что такое вес?"))["answer"].startswith("Привет")

    repo.save_answer(VID, rag.question_key("Старый ответ?"), "Старый ответ?", "Привет! Хороший вопрос. Ответ.", [])
    cached = collect(VID, "Старый ответ?")
    assert "".join(e["text"] for e in cached if e["type"] == "token") == "Ответ."
