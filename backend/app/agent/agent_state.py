"""LLM clients and the LangGraph state.

Gemini (config.GEMINI_MODEL) does all the text work; Groq is used only for speech recognition
(tools/whisper.py). The clients are created on first use, so the API starts (and
the library opens) even without the keys; a missing key becomes a readable error on the step that needs it.
Tests replace these functions."""
import operator
from functools import lru_cache
from typing import Annotated, TypedDict

import config
from errors import require_env


def _chat(model: str, retries: int, **options):
    from langchain_google_genai import ChatGoogleGenerativeAI

    if config.GEMINI_THINKING_LEVEL:
        options["thinking_level"] = config.GEMINI_THINKING_LEVEL
    # Temperature stays at the default: Google advises against lowering it for Gemini 3 models.
    return ChatGoogleGenerativeAI(model=model, api_key=require_env("GOOGLE_API_KEY"), timeout=180,
                                  max_retries=retries, **options)


def _gemini(**options):
    """The main model, with the fallback model behind it when one is configured.

    With a fallback the main model gets 2 quick attempts and an overloaded request moves on to the fallback
    (which keeps the full 6 attempts, about half a minute of pauses); without one the main model keeps all 6."""
    if not config.GEMINI_FALLBACK_MODEL:
        return _chat(config.GEMINI_MODEL, 6, **options)
    return _chat(config.GEMINI_MODEL, 2, **options).with_fallbacks([_chat(config.GEMINI_FALLBACK_MODEL, 6, **options)])


@lru_cache(maxsize=1)
def gemini():
    """Summaries, podcast scripts and answers to questions."""
    return _gemini()


@lru_cache(maxsize=1)
def gemini_json():
    """The short checks, answered as JSON: whether the material is educational, key terms, script review."""
    return _gemini(response_mime_type="application/json")


@lru_cache(maxsize=1)
def gemini_backup():
    """For a summary whose stream broke midway: the fallback model alone (the main one if there is none)."""
    return _chat(config.GEMINI_FALLBACK_MODEL or config.GEMINI_MODEL, 6)


class GraphState(TypedDict, total=False):
    video_id: str
    kind: str  # youtube | article | text
    url: str
    anchors: dict | None  # articles: paragraph number -> first words, for links into the original
    force: bool  # process even if the classifier says the material is not educational
    title: str | None
    channel: str | None
    language: str
    segments: list[dict]  # video: [{start, duration, text}]; text materials: [{n, section, text}]
    youtube_category: str | None  # the category on YouTube, when the watch page gave it
    classification: dict
    rejected: bool
    summary: str
    keywords: list[str]
    podcast_script: str
    critic_feedback: str
    retry_count: int
    max_retries: int
    is_valid: bool
    indexed: bool
    agent_execution_order: Annotated[list[str], operator.add]


def extract_text(result) -> str:
    return result.text
