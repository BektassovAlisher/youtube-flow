"""All settings come from the environment (.env in the project root for local runs)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # backend/


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


DATABASE_URL = os.getenv("DATABASE_URL")

GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"
# how long Gemini 3 thinks before answering: minimal | low | medium | high; empty keeps the model's default
_THINKING = (os.getenv("GEMINI_THINKING_LEVEL") or "").strip().lower()
GEMINI_THINKING_LEVEL = _THINKING if _THINKING in ("minimal", "low", "medium", "high") else None
# the short checks (is the material educational, key terms, podcast script review): gemini by default,
# groq to send them to Groq's gpt-oss models and spend fewer Gemini requests
CHECKS_PROVIDER = "groq" if (os.getenv("CHECKS_PROVIDER") or "").strip().lower() == "groq" else "gemini"
GROQ_MODEL_LARGE = os.getenv("GROQ_MODEL_LARGE") or "openai/gpt-oss-120b"
GROQ_MODEL_SMALL = os.getenv("GROQ_MODEL_SMALL") or "openai/gpt-oss-20b"
WHISPER_MODEL = os.getenv("WHISPER_MODEL") or "whisper-large-v3-turbo"

# same model as before (sentence-transformers), served through ONNX by fastembed: no torch needed
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
FASTEMBED_CACHE_PATH = os.getenv("FASTEMBED_CACHE_PATH") or None  # Docker bakes the model into /opt/models
VECTOR_DIR = os.getenv("VECTOR_DIR") or str(PROJECT_ROOT / "vector_storage" / "chroma_db")

# background processing
MAX_CONCURRENT_JOBS = max(1, _int("MAX_CONCURRENT_JOBS", 3))
TTS_CONCURRENCY = max(1, _int("TTS_CONCURRENCY", 2))  # ElevenLabs allows 2+ parallel requests on every plan

# subtitles fallback: speech recognition through Groq Whisper when a video has no subtitles
WHISPER_FALLBACK = _bool("WHISPER_FALLBACK", True)
WHISPER_MAX_MINUTES = _int("WHISPER_MAX_MINUTES", 180)
YOUTUBE_PROXY_URL = os.getenv("YOUTUBE_PROXY_URL") or None

# articles: the server opens links people send, so internal addresses are refused unless explicitly allowed
# (e.g. a company wiki on the same network — only when the API is not reachable by strangers)
ALLOW_PRIVATE_URLS = _bool("ALLOW_PRIVATE_URLS", False)

# access control: when API_TOKEN is set, every POST/DELETE needs "Authorization: Bearer <API_TOKEN>"
API_TOKEN = os.getenv("API_TOKEN") or None
LIMIT_VIDEOS_PER_HOUR = _int("LIMIT_VIDEOS_PER_HOUR", 20)
LIMIT_AUDIO_PER_HOUR = _int("LIMIT_AUDIO_PER_HOUR", 10)
LIMIT_QUESTIONS_PER_HOUR = _int("LIMIT_QUESTIONS_PER_HOUR", 120)
