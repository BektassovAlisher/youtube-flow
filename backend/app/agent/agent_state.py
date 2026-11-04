"""LLM clients and the LangGraph state.

Gemini does all the text work; Groq is there for speech recognition (tools/whisper.py) and, with
CHECKS_PROVIDER=groq, for the short checks. The clients are created on first use, so the API starts (and
the library opens) even without the keys; a missing key becomes a readable error on the step that needs it.
Tests replace these functions."""
import operator
from functools import lru_cache
from typing import Annotated, TypedDict

import config
from errors import require_env


def _gemini(**options):
    from langchain_google_genai import ChatGoogleGenerativeAI

    if config.GEMINI_THINKING_LEVEL:
        options["thinking_level"] = config.GEMINI_THINKING_LEVEL
    # Temperature stays at the default: Google advises against lowering it for Gemini 3 models.
    # 6 attempts with growing pauses (about half a minute in all) ride out the free tier's per-minute limit.
    return ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, api_key=require_env("GOOGLE_API_KEY"),
                                  timeout=180, max_retries=6, **options)


@lru_cache(maxsize=1)
def gemini():
    """Summaries, podcast scripts and answers to questions."""
    return _gemini()


@lru_cache(maxsize=1)
def gemini_json():
    """The short checks, answered as JSON: whether the material is educational, key terms, script review."""
    return _gemini(response_mime_type="application/json")


def checker(size: str = "large"):
    """The model for the short checks. `size` picks between Groq's two models when CHECKS_PROVIDER=groq."""
    if config.CHECKS_PROVIDER == "groq":
        return groq_small() if size == "small" else groq_large()
    return gemini_json()


@lru_cache(maxsize=1)
def groq_large():
    from langchain_groq import ChatGroq

    return ChatGroq(model=config.GROQ_MODEL_LARGE, temperature=0, api_key=require_env("GROQ_API_KEY"),
                    request_timeout=60, max_retries=2)


@lru_cache(maxsize=1)
def groq_small():
    from langchain_groq import ChatGroq

    # temperature 0: the same video must not pass the check one time and fail it the next
    return ChatGroq(model=config.GROQ_MODEL_SMALL, temperature=0, api_key=require_env("GROQ_API_KEY"),
                    request_timeout=60, max_retries=2)


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
