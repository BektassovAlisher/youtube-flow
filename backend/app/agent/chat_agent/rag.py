"""Questions about a video: hybrid retrieval over the transcript (vectors + BM25) and a streamed answer."""
import asyncio
import logging
import re
import threading
from collections import OrderedDict
from typing import AsyncIterator, Callable

import snowballstemmer
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from rank_bm25 import BM25Okapi

import config
from agent import agent_state as llm
from db import cache as repo
from errors import UserError
from tools import sources
from tools.chunking_transcript import TranscriptChunker

log = logging.getLogger(__name__)


# ---- embeddings ---------------------------------------------------------------------------------

class FastEmbedEmbeddings(Embeddings):
    """paraphrase-multilingual-MiniLM-L12-v2 through ONNX Runtime: the same model as before, without torch.
    Loaded on first use (and warmed up in the background at startup), not at import time."""

    def __init__(self, model_name: str, cache_dir: str | None):
        self.model_name, self.cache_dir = model_name, cache_dir
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                try:
                    self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)
                except Exception as e:  # noqa: BLE001
                    log.error("модель эмбеддингов не загрузилась: %s", e)
                    raise UserError("Модель для поиска по видео не загрузилась (нет доступа к HuggingFace?). "
                                    "Вопросы по видео временно недоступны.", status=503)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load().embed(list(texts), batch_size=32)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


EMBEDDER_ID = f"fastembed:{config.EMBEDDING_MODEL}"
_embeddings: Embeddings = FastEmbedEmbeddings(config.EMBEDDING_MODEL, config.FASTEMBED_CACHE_PATH)


def set_embeddings(embeddings: Embeddings, embedder_id: str | None = None) -> None:
    """Tests swap in a fake model."""
    global _embeddings, EMBEDDER_ID
    _embeddings = embeddings
    if embedder_id:
        EMBEDDER_ID = embedder_id


def warm_up() -> None:
    try:
        _embeddings.embed_query("прогрев")
        log.info("модель эмбеддингов загружена")
    except Exception as e:  # noqa: BLE001
        log.warning("прогрев модели эмбеддингов не удался: %s", e)


# ---- vector store -------------------------------------------------------------------------------

_client = None
_client_lock = threading.Lock()


def _chroma():
    global _client
    with _client_lock:
        if _client is None:
            import chromadb
            from chromadb.config import Settings

            _client = chromadb.PersistentClient(path=config.VECTOR_DIR, settings=Settings(anonymized_telemetry=False))
        return _client


def _collection_name(video_id: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", video_id).strip("._-") or "vid"
    if not name[0].isalnum():
        name = "v" + name
    if not name[-1].isalnum():
        name += "0"
    return name.ljust(3, "0")[:512]


def _store(video_id: str) -> Chroma:
    return Chroma(client=_chroma(), collection_name=_collection_name(video_id), embedding_function=_embeddings,
                  collection_metadata={"embedder": EMBEDDER_ID})


def _existing(video_id: str):
    try:
        return _chroma().get_collection(_collection_name(video_id))
    except Exception:  # noqa: BLE001 — chromadb raises NotFoundError (ValueError in older versions)
        return None


def _drop(video_id: str) -> None:
    try:
        _chroma().delete_collection(_collection_name(video_id))
    except Exception:  # noqa: BLE001
        pass
    _forget(video_id)


def _add(video_id: str, docs: list[Document]) -> None:
    _drop(video_id)  # a fresh collection: no stale chunks from a previous transcript or model
    if docs:
        _store(video_id).add_documents(docs, ids=[f"{video_id}_{i}" for i in range(len(docs))])


def index_video(video_id: str, segments: list[dict], link_for=None) -> int:
    docs = TranscriptChunker().split(segments, video_id, link_for)
    _add(video_id, docs)
    log.info("RAG: %s — %d фрагментов", video_id, len(docs))
    return len(docs)


def delete_video_index(video_id: str) -> None:
    _drop(video_id)


def ensure_index(video_id: str) -> Chroma:
    """Index built with the current model: reuses it, re-embeds an old one, or builds it from the stored transcript."""
    collection = _existing(video_id)
    if collection is not None and (collection.metadata or {}).get("embedder") == EMBEDDER_ID and collection.count():
        return _store(video_id)
    segments = repo.load_transcript(video_id)
    if segments:
        video = repo.get_video(video_id) or {}
        index_video(video_id, segments,
                    sources.link_builder(video.get("kind", "youtube"), video.get("url"), video.get("anchors")))
    elif collection is not None and collection.count():
        # indexed by an older version (other embedding model) and the transcript was not stored back then
        data = collection.get(include=["documents", "metadatas"])
        docs = [Document(page_content=d, metadata=m or {}) for d, m in zip(data["documents"], data["metadatas"])]
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
        _add(video_id, docs)
        log.info("RAG: %s переиндексирован под %s", video_id, EMBEDDER_ID)
    else:
        raise UserError("Для этого видео нет транскрипта для поиска — перегенерируйте конспект.", status=409)
    repo.mark_indexed(video_id)
    return _store(video_id)


# ---- lexical search -----------------------------------------------------------------------------

_WORD = re.compile(r"[0-9a-zа-яәғқңөұүһі]+")
_CYRILLIC = re.compile(r"[а-яәғқңөұүһі]")
STOPWORDS = set("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще
нет о из ему теперь когда даже ну ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж
тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем
всех никогда можно при об другой хоть после над больше тот через эти нас про всего них какая много разве эту моя
свою этой перед лучше чуть том такой им более всегда между это такое такая такие почему какие каким объясни
расскажи видео ролик лекции лекция автор
the a an is are was were be been to of in on for and or what how why which who whom does do did it its this that
these those with as by from about explain tell video lecture
""".split())
_local = threading.local()


def _stemmers():
    if not hasattr(_local, "ru"):  # snowball stemmers keep state between calls: one per thread
        _local.ru = snowballstemmer.stemmer("russian")
        _local.en = snowballstemmer.stemmer("english")
    return _local.ru, _local.en


def tokenize(text: str) -> list[str]:
    """Lowercased, stop words dropped, Russian/English words stemmed: «нейронные сети» matches «нейронная сеть»."""
    ru, en = _stemmers()
    out = []
    for word in _WORD.findall(text.lower().replace("ё", "е")):
        if word in STOPWORDS or (len(word) < 2 and not word.isdigit()):
            continue
        out.append(ru.stemWord(word) if _CYRILLIC.search(word) else en.stemWord(word) if word.isascii() else word)
    return out


_bm25: OrderedDict[str, tuple[BM25Okapi, list[Document]]] = OrderedDict()
_bm25_lock = threading.Lock()
_BM25_CACHE_SIZE = 64


def _forget(video_id: str) -> None:
    with _bm25_lock:
        _bm25.pop(video_id, None)


def _lexical_index(video_id: str):
    with _bm25_lock:
        if video_id in _bm25:
            _bm25.move_to_end(video_id)
            return _bm25[video_id]
    collection = _existing(video_id)
    if collection is None:
        return None
    data = collection.get(include=["documents", "metadatas"])
    docs = [Document(page_content=d, metadata=m or {}) for d, m in zip(data["documents"], data["metadatas"])]
    tokens = [tokenize(d.page_content) for d in docs]
    if not docs or not any(tokens):
        return None
    entry = (BM25Okapi(tokens), docs)
    with _bm25_lock:
        _bm25[video_id] = entry
        while len(_bm25) > _BM25_CACHE_SIZE:
            _bm25.popitem(last=False)
    return entry


def _key(doc: Document) -> str:
    return str(doc.metadata.get("chunk_index", doc.page_content))


def reciprocal_rank_fusion(rankings: list[list[Document]], k: int, c: int = 60) -> list[Document]:
    scores: dict[str, list] = {}
    for docs in rankings:
        for rank, doc in enumerate(docs):
            entry = scores.setdefault(_key(doc), [0.0, doc])
            entry[0] += 1 / (rank + c)
    return [doc for _, doc in sorted(scores.values(), key=lambda e: e[0], reverse=True)[:k]]


def retrieve(video_id: str, query: str, k: int = 5) -> list[Document]:
    store = ensure_index(video_id)
    semantic = store.similarity_search(query, k=k * 2)
    lexical = []
    entry = _lexical_index(video_id)
    terms = tokenize(query)
    if entry and terms:
        index, docs = entry
        scores = index.get_scores(terms)
        best = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:k * 2]
        lexical = [docs[i] for i in best if scores[i] > 0]  # only pieces that really share words with the question
    fused = reciprocal_rank_fusion([semantic, lexical], k=k)
    # in the order of the material, as the prompt asks (old video indexes have no "order", only the start time)
    return sorted(fused, key=lambda d: d.metadata.get("order", d.metadata.get("start_seconds", 0)))


# ---- answering ----------------------------------------------------------------------------------

QA_PROMPT = """Ты — преподаватель, который отлично знает {material}. Ответь на вопрос слушателя.

---КРАТКО О МАТЕРИАЛЕ (из конспекта)---
{outline}
---ФРАГМЕНТЫ {fragments}---
{context}
---КОНЕЦ---
{history}
Вопрос: {question}

Как отвечать:
- Опирайся на фрагменты, а на общие вопросы («о чём это», «главные выводы») — на краткое содержание.
- {places}
- Если в материале этого нет — скажи прямо, затем коротко ответь из общих знаний, без ссылок на места.
- Обзор → структура и 3–5 главных идей. Сравнение → плюсы и минусы и вывод автора. «Как сделать» → шаги и \
предупреждения автора. «Что такое» → простое объяснение с аналогией.
- Стиль живой и дружелюбный, не энциклопедический. 2–5 абзацев, короче — если вопрос простой.
- Английские технические термины оставляй на английском. Отвечай на языке вопроса.
"""

PROMPT_PARTS = {
    "youtube": {"material": "это видео", "fragments": "ТРАНСКРИПТА",
                "places": "Таймкоды [MM:SS] бери только из фрагментов выше и ставь в порядке их появления в видео. "
                          "Не придумывай таймкоды."},
    "article": {"material": "эту статью", "fragments": "СТАТЬИ",
                "places": "Ссылки на абзацы [¶N] бери только из меток фрагментов выше и ставь в порядке текста. "
                          "Не придумывай номера."},
    "text": {"material": "этот текст", "fragments": "ТЕКСТА",
             "places": "Ссылки на абзацы [¶N] бери только из меток фрагментов выше и ставь в порядке текста. "
                       "Не придумывай номера."},
}


def summary_outline(summary: str, limit: int = 6000) -> str:
    """Overview, section titles and conclusions of the summary: enough for questions about the whole video."""
    if not summary:
        return "(конспекта нет)"
    out = []
    for block in re.split(r"(?m)^(?=## )", summary):
        head, _, body = block.partition("\n")
        if not head.startswith("## "):
            continue
        title = head[3:].lower()
        if "обзор" in title or "вывод" in title:
            out.append(f"{head}\n{body.strip()}")
        elif not any(w in title for w in ("самопроверк", "глоссарий", "ключевые понятия")):
            out.append(head)
    return "\n".join(out)[:limit]


def question_key(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower()).strip(" ?!.…")


def _context(docs: list[Document]) -> str:
    return "\n\n".join(f"[{d.metadata.get('timestamp', '')}]\n{d.page_content}" for d in docs) or "(ничего не найдено)"


def _history(history: list[dict]) -> str:
    turns = [h for h in history[-3:] if h.get("q") and h.get("a")]
    if not turns:
        return ""
    lines = "\n".join(f"Вопрос: {h['q']}\nОтвет: {h['a'][:800]}" for h in turns)
    return f"\n---ПРЕДЫДУЩИЕ ВОПРОСЫ В ЭТОМ ДИАЛОГЕ---\n{lines}\n"


async def answer_events(video_id: str, question: str, history: list[dict] | None = None,
                        charge: Callable[[], None] | None = None) -> AsyncIterator[dict]:
    """{"type": "sources"} → {"type": "token"}… → {"type": "done"}. Answers without history are cached:
    the quiz and the suggested questions cost one LLM call per video, not one per click."""
    q = (question or "").strip()
    if not q:
        raise UserError("Задайте вопрос.")
    if len(q) > 1000:
        raise UserError("Вопрос слишком длинный — сократите его до 1000 символов.")
    history = history or []
    key = question_key(q)
    if not history:
        cached = await asyncio.to_thread(repo.get_answer, video_id, key)
        if cached:
            yield {"type": "sources", "sources": cached["sources"]}
            yield {"type": "token", "text": cached["answer"]}
            yield {"type": "done", "cached": True}
            return
    if charge:
        charge()  # rate limit counts only answers that call the model
    video = await asyncio.to_thread(repo.get_video, video_id)
    if video is None:
        raise UserError("Видео не найдено.", status=404)
    retrieval_query = " ".join([h["q"] for h in history[-1:] if h.get("q")] + [q])
    docs = await asyncio.to_thread(retrieve, video_id, retrieval_query, 5)
    found = [{"timestamp": d.metadata.get("timestamp", ""), "url": d.metadata.get("link") or d.metadata.get("youtube_url", "")}
             for d in docs]
    yield {"type": "sources", "sources": found}

    prompt = QA_PROMPT.format(**PROMPT_PARTS.get(video["kind"], PROMPT_PARTS["youtube"]),
                              outline=summary_outline(video["summary"]), context=_context(docs),
                              history=_history(history), question=q)
    parts = []
    async for chunk in llm.gemini().astream(prompt):
        text = chunk.text
        if text:
            parts.append(text)
            yield {"type": "token", "text": text}
    answer = "".join(parts).strip()
    if not answer:
        raise UserError("Модель не вернула ответ. Попробуйте ещё раз.", status=503)
    if not history:
        await asyncio.to_thread(repo.save_answer, video_id, key, q, answer, found)
    yield {"type": "done", "cached": False}
