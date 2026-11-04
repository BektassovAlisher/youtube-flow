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

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
GROQ_MODEL_LARGE = os.getenv("GROQ_MODEL_LARGE", "openai/gpt-oss-120b")
GROQ_MODEL_SMALL = os.getenv("GROQ_MODEL_SMALL", "openai/gpt-oss-20b")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "whisper-large-v3-turbo")

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

# access control: when API_TOKEN is set, every POST/DELETE needs "Authorization: Bearer <API_TOKEN>"
API_TOKEN = os.getenv("API_TOKEN") or None
LIMIT_VIDEOS_PER_HOUR = _int("LIMIT_VIDEOS_PER_HOUR", 20)
LIMIT_AUDIO_PER_HOUR = _int("LIMIT_AUDIO_PER_HOUR", 10)
LIMIT_QUESTIONS_PER_HOUR = _int("LIMIT_QUESTIONS_PER_HOUR", 120)
