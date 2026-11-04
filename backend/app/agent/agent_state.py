"""LLM clients and the LangGraph state.

The clients are created on first use, so the API starts (and the library opens) even without the keys;
a missing key becomes a readable error on the step that needs it. Tests replace these functions."""
import operator
from functools import lru_cache
from typing import Annotated, TypedDict

import config
from errors import require_env


@lru_cache(maxsize=1)
def gemini():
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, api_key=require_env("GOOGLE_API_KEY"),
                                  timeout=180, max_retries=2)


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
