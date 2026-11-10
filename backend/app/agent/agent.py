"""Graph nodes. Every node saves its result right away and skips work that is already saved, so a run
cut short (an error, a restart) resumes where it stopped instead of starting over."""
import json
import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from langgraph.config import get_stream_writer

from agent import agent_state as llm
from agent import prompts
from agent.agent_state import GraphState, extract_text
from agent.chat_agent import rag
from db import cache as repo
from errors import UserError
from tools import sources
from tools.chunking_transcript import plain_text, to_timestamped_text
from tools.media import fetch_media
from tools.text_sources import fetch_article, word_count
from tools.youtube_scraper import duration_of, fetch_category, fetch_metadata, get_transcript

log = logging.getLogger(__name__)

HOSTS = ("Алекс", "Марина")
CATEGORIES = {"educational", "entertainment", "news", "random", "music", "gaming", "advertising"}
# YouTube categories that answer the check by themselves; any other category goes to the model as a hint
EDUCATIONAL_ON_YOUTUBE = {"Education": "Образование", "Science & Technology": "Наука и техника"}
GEMINI_CHAR_LIMIT = 60000  # Gemini reads a whole podcast script
TEMPLATE_LABELS = {"содержание раздела", "ключевые понятия и определения", "важные идеи и факты",
                   "примеры и иллюстрации", "связи с другими темами"}


def _emit(**event) -> None:
    try:
        get_stream_writer()(event)
    except Exception:  # noqa: BLE001 — not inside a streaming run (tests calling a node directly)
        pass


def _usage(message) -> None:
    """Reports the tokens of a model answer (a "usage" event) when the model says how many it used."""
    usage = getattr(message, "usage_metadata", None) or {}
    if usage.get("input_tokens") or usage.get("output_tokens"):
        _emit(usage={"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)})


def _ask(model, prompt: str) -> str:
    """One model call: the answer's text, with its tokens reported."""
    result = model.invoke(prompt)
    _usage(result)
    return extract_text(result)


def _stage(video_id: str, stage: str) -> None:
    repo.set_stage(video_id, stage)
    _emit(stage=stage)


def _truncate(text: str, limit: int = GEMINI_CHAR_LIMIT) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... [текст обрезан]"


def _parse_json(raw: str, kind: type):
    text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}" if kind is dict else r"\[.*\]", text, re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if kind is list and isinstance(value, dict):  # {"keywords": [...]} in place of the bare list
        value = next((v for v in value.values() if isinstance(v, list)), value)
    return value if isinstance(value, kind) else None


def load_node(state: GraphState):
    """What earlier runs already produced for this video."""
    video = repo.get_video(state["video_id"])
    if not video:
        return {}
    out = {
        "kind": video["kind"],
        "url": video["url"],
        "anchors": video["anchors"],
        "title": video["title"],
        "channel": video["channel"],
        "language": video["language"] or "ru",
        "force": bool(state.get("force") or video["force"]),
        "indexed": video["indexed"],
    }
    for key in ("classification", "summary", "keywords", "podcast_script"):
        if video.get(key):
            out[key] = video[key]
    segments = repo.load_transcript(state["video_id"])
    if segments:
        out["segments"] = segments
    return out


def _article(state: GraphState):
    video_id = state["video_id"]
    article = fetch_article(state["url"])
    segments, words = article["segments"], word_count(article["segments"])
    repo.save_transcript(video_id, segments, language=article["language"], source="article", duration_sec=None,
                         title=article["title"], channel=article["site"], image_url=article["image"],
                         word_count=words, anchors=article["anchors"])
    _emit(meta={"title": article["title"], "channel": article["site"], "language": article["language"]})
    log.info("%s: статья, %d абзацев, %d слов", video_id, len(segments), words)
    return {"segments": segments, "language": article["language"], "title": article["title"],
            "channel": article["site"], "anchors": article["anchors"], "agent_execution_order": ["transcript"]}


def _media(state: GraphState):
    video_id = state["video_id"]
    rec = fetch_media(state["url"])
    segments = rec["segments"]
    repo.save_transcript(video_id, segments, language=rec["language"], source=rec["source"],
                         duration_sec=rec["duration_sec"], title=rec["title"], channel=rec["channel"],
                         image_url=rec["image"])
    _emit(meta={"title": rec["title"], "channel": rec["channel"], "language": rec["language"]})
    log.info("%s: запись, %d сегментов, источник %s", video_id, len(segments), rec["source"])
    return {"segments": segments, "language": rec["language"], "title": rec["title"], "channel": rec["channel"],
            "agent_execution_order": ["transcript"]}


def transcript_node(state: GraphState):
    """Subtitles (or recognized speech) of a recording, or the text of an article; pasted text arrives with
    the request and is already saved."""
    if state.get("segments"):
        return {}
    video_id = state["video_id"]
    _stage(video_id, "transcript")
    if state.get("kind") == "article":
        return _article(state)
    if state.get("kind") == "media":
        return _media(state)
    with ThreadPoolExecutor(2) as pool:  # title, channel and category arrive while the subtitles download
        meta = pool.submit(fetch_metadata, video_id)
        category = pool.submit(fetch_category, video_id)
        data = get_transcript(video_id)
        meta, category = meta.result(), category.result()
    segments = data["segments"]
    title = data.get("title") or meta["title"] or state.get("title") or f"Видео {video_id}"
    channel = data.get("channel") or meta["channel"]
    duration = duration_of(segments)
    repo.save_transcript(video_id, segments, language=data["language"], source=data["source"],
                         duration_sec=duration, title=title, channel=channel)
    _emit(meta={"title": title, "channel": channel, "language": data["language"], "duration_sec": duration})
    log.info("%s: %d сегментов, %.0f мин, источник %s", video_id, len(segments), duration / 60, data["source"])
    return {"segments": segments, "language": data["language"], "title": title, "channel": channel,
            "youtube_category": category, "agent_execution_order": ["transcript"]}


def _samples(segments: list[dict], size: int = 900) -> str:
    """The start, two middle points and the end: intros are often greetings or ads."""
    text = plain_text(segments)
    if len(text) <= size * 4:
        return text
    picks = []
    for label, fraction in (("Начало", 0.0), ("Первая треть", 0.3), ("Середина", 0.55), ("Конец", 1.0)):
        start = min(int(len(text) * fraction), len(text) - size)
        if start:
            start = text.find(" ", start) + 1
        picks.append(f"[{label}] {text[start:start + size]}")
    return "\n\n".join(picks)


def classify_node(state: GraphState):
    if state.get("classification"):
        return {}
    video_id = state["video_id"]
    if state.get("kind") == "text":  # pasted on purpose: nothing to filter out
        classification = {"category": "unknown", "is_suitable": True, "confidence": 1.0,
                          "reason": "Текст добавлен вручную."}
        repo.save_classification(video_id, classification)
        return {"classification": classification}
    _stage(video_id, "classify")
    youtube_category = state.get("youtube_category")
    if youtube_category in EDUCATIONAL_ON_YOUTUBE:  # the author filed it as educational: no model call needed
        classification = {"category": "educational", "is_suitable": True, "confidence": 0.9,
                          "reason": f"На YouTube видео в категории «{EDUCATIONAL_ON_YOUTUBE[youtube_category]}»."}
        repo.save_classification(video_id, classification)
        log.info("%s: категория YouTube «%s», модель не спрашиваю", video_id, youtube_category)
        return {"classification": classification}
    segments = state["segments"]
    if state.get("kind") == "article":
        prompt = prompts.CLASSIFY_ARTICLE.format(
            title=state.get("title") or "неизвестно", site=state.get("channel") or "неизвестно",
            words=word_count(segments), samples=_samples(segments),
        )
    else:
        prompt = prompts.CLASSIFY.format(
            title=state.get("title") or "неизвестно", channel=state.get("channel") or "неизвестно",
            category=youtube_category or "неизвестно", minutes=round(duration_of(segments) / 60), samples=_samples(segments),
        )
    fallback = {"category": "unknown", "is_suitable": True, "confidence": 0.6, "reason": "классификатор не ответил"}
    try:
        parsed = _parse_json(_ask(llm.gemini_json(), prompt), dict) or {}
    except Exception as e:  # noqa: BLE001 — a failed check must not block the summary
        log.warning("классификатор недоступен: %s", e)
        parsed = {}
    c = {**fallback, **parsed}
    category = str(c.get("category", "unknown")).lower()
    try:
        confidence = min(1.0, max(0.0, float(c.get("confidence", 0.6))))
    except (TypeError, ValueError):
        confidence = 0.6
    classification = {
        "category": category if category in CATEGORIES else "unknown",
        "is_suitable": bool(c.get("is_suitable")),
        "confidence": confidence,
        "reason": str(c.get("reason") or ""),
    }
    repo.save_classification(video_id, classification)
    log.info("%s: %s", video_id, classification)
    return {"classification": classification, "agent_execution_order": ["classify"]}


def route_classify(state: GraphState):
    c = state.get("classification") or {}
    if state.get("force") or (c.get("is_suitable") and c.get("confidence", 1.0) >= 0.6):
        return "start_pipeline"
    return "reject"


def reject_node(state: GraphState):
    repo.reject(state["video_id"])
    _emit(rejected=state.get("classification"))
    return {"rejected": True, "agent_execution_order": ["reject"]}


def start_pipeline_node(state: GraphState):
    return {}


SUMMARY_PAUSES = (5, 15, 30)  # waits before the 2nd, 3rd and 4th attempt of a summary cut off by an overload
_TRANSIENT = re.compile(r"\b(?:429|500|502|503|504)\b|unavailable|high demand|overloaded|resource.exhausted|deadline|timed out", re.I)


def _transient(exc: BaseException) -> bool:
    return bool(_TRANSIENT.search(f"{type(exc).__name__} {exc}"))


def section_count(estimate: float) -> int:
    """How many sections the summary asks for: one per 5-7 minutes or ~800 words. Without a number the model
    wrote 3 sections for an hour-long lecture and lost most of the details."""
    return max(2, min(25, round(estimate)))


def summarize_node(state: GraphState):
    if state.get("summary"):
        return {}
    video_id = state["video_id"]
    _stage(video_id, "summary")
    kind = state.get("kind", "youtube")
    if kind in ("youtube", "media"):
        minutes = round(duration_of(state["segments"]) / 60)
        prompt = prompts.SUMMARY.format(transcript=to_timestamped_text(state["segments"]), minutes=minutes,
                                        sections=section_count(minutes / 6))
    else:
        words = word_count(state["segments"])
        prompt = prompts.SUMMARY_TEXT.format(what="статьи" if kind == "article" else "учебного материала",
                                             text=sources.prompt_text(state["segments"]), words=words,
                                             sections=section_count(words / 800))
    # The SDK retries a request that fails before the answer starts; an overload that breaks the stream midway
    # ("503 UNAVAILABLE ... high demand") is retried here, and the page drops the half-written text first.
    started = time.monotonic()
    for attempt, pause in enumerate((*SUMMARY_PAUSES, None)):
        parts, whole, first = [], None, None
        model = llm.gemini() if attempt == 0 else llm.gemini_backup()  # later attempts go to the fallback model
        try:
            for chunk in model.stream(prompt):  # tokens go straight to the page that waits for the summary
                whole = chunk if whole is None else whole + chunk  # adds up the token counts of the chunks
                text = chunk.text
                if text:
                    first = first if first is not None else time.monotonic() - started
                    parts.append(text)
                    _emit(token=text)
            _usage(whole)
            if first is not None:
                _emit(timing={"first_token": round(first, 2)})  # how long the reader waited for the first words
            break
        except Exception as e:  # noqa: BLE001 — only overloads and timeouts are retried, everything else is raised
            if pause is None or not _transient(e):
                raise
            log.warning("%s: конспект прервался (%s), повтор %d через %d с", video_id, str(e)[:120], attempt + 1, pause)
            if parts:
                _emit(restart=True)
            time.sleep(pause)
    summary = "".join(parts).strip()
    if not summary:
        raise UserError("Модель вернула пустой конспект. Попробуйте ещё раз.", status=503)
    repo.save_summary(video_id, summary)  # saved before anything else can fail
    _emit(summary_saved=True)
    return {"summary": summary, "agent_execution_order": ["summary"]}


def _summary_terms(summary: str) -> tuple[str, list[tuple[str, int]]]:
    headings = [re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]\s*", "", line[3:]).strip()
                for line in summary.splitlines() if line.startswith("## ")]
    counts, first = Counter(), {}
    for i, match in enumerate(re.finditer(r"\*\*([^*\n]{2,60}?)\*\*", summary)):
        term = match.group(1).strip(" :.,;")
        key = term.lower()
        if not term or key in TEMPLATE_LABELS:
            continue
        counts[key] += 1
        first.setdefault(key, (i, term))
    ranked = sorted(counts, key=lambda k: (-counts[k], first[k][0]))
    return "\n".join(headings)[:2000], [(first[k][1], counts[k]) for k in ranked[:80]]


def _clean_keywords(values) -> list[str]:
    seen, out = set(), []
    for v in values or []:
        if not isinstance(v, str):
            continue
        term = v.strip().strip(" .,;:")
        if term and len(term) <= 60 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out[:15]


def keywords_node(state: GraphState):
    """Terms of the whole lecture: picked from the summary's outline, not from the first minutes of the transcript."""
    if state.get("keywords"):
        return {}
    video_id = state["video_id"]
    _stage(video_id, "keywords")
    headings, terms = _summary_terms(state["summary"])
    keywords = []
    if terms:
        prompt = prompts.KEYWORDS.format(headings=headings or "(нет)",
                                         terms=_truncate("\n".join(f"{t} ({n})" for t, n in terms), 3000))
        try:
            keywords = _clean_keywords(_parse_json(_ask(llm.gemini_json(), prompt), list))
        except Exception as e:  # noqa: BLE001
            log.warning("ключевые слова: модель недоступна (%s), беру самые частые термины", e)
    if not keywords:
        keywords = _clean_keywords([t for t, _ in terms])[:12]
    repo.save_keywords(video_id, keywords)
    return {"keywords": keywords, "agent_execution_order": ["keywords"]}


def index_node(state: GraphState):
    """Vector index for questions. A failure here only postpones it: questions rebuild it on demand."""
    if state.get("indexed") or not state.get("segments"):
        return {}
    video_id = state["video_id"]
    kind = state.get("kind", "youtube")
    link_for = sources.link_builder(kind, state.get("url"), state.get("anchors"))
    time_link = sources.time_builder(kind, state.get("url"), video_id)
    try:
        rag.index_video(video_id, state["segments"], link_for, time_link)
        repo.mark_indexed(video_id)
        return {"indexed": True}
    except Exception as e:  # noqa: BLE001
        log.warning("%s: индексация отложена: %s", video_id, e)
        return {"indexed": False}


def script_node(state: GraphState):
    """The podcast script, streamed to the page like the summary. Runs on its own, by a button, not in processing."""
    if state.get("retry_count", 0) > 0:
        _emit(restart=True)  # the editor sent it back: the page drops the previous version
    _emit(stage="script")
    prompt = prompts.SCRIPT.format(summary=state["summary"], keywords=", ".join(state.get("keywords") or []),
                                   host1=HOSTS[0], host2=HOSTS[1])
    if state.get("retry_count", 0) > 0 and state.get("critic_feedback"):
        prompt += prompts.SCRIPT_RETRY.format(feedback=state["critic_feedback"])
    parts, whole = [], None
    for chunk in llm.gemini().stream(prompt):
        whole = chunk if whole is None else whole + chunk
        if chunk.text:
            parts.append(chunk.text)
            _emit(token=chunk.text)
    _usage(whole)
    script = "".join(parts).strip()
    if not script:
        raise UserError("Модель вернула пустой сценарий. Попробуйте ещё раз.", status=503)
    return {"podcast_script": script, "agent_execution_order": ["script"]}


def critic_node(state: GraphState):
    _emit(stage="critic")
    prompt = prompts.CRITIC.format(script=_truncate(state.get("podcast_script", "")),
                                   keywords=", ".join(state.get("keywords") or []))
    try:
        verdict = _parse_json(_ask(llm.gemini_json(), prompt), dict) or {}
    except Exception as e:  # noqa: BLE001 — the editor is optional: keep the script
        log.warning("критик недоступен: %s", e)
        verdict = {}
    verdict = {"is_valid": True, "feedback": "", **verdict}
    log.info("критик: %s", verdict)
    return {"is_valid": bool(verdict["is_valid"]), "critic_feedback": str(verdict["feedback"]),
            "retry_count": state.get("retry_count", 0) + 1, "agent_execution_order": ["critic"]}


def route_critic(state: GraphState):
    if state.get("is_valid") or state.get("retry_count", 0) >= state.get("max_retries", 2):
        return "save_script"
    return "script"


def save_script_node(state: GraphState):
    repo.save_script(state["video_id"], state["podcast_script"])
    _emit(script_saved=True)
    return {"agent_execution_order": ["save_script"]}
