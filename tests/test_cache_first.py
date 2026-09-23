"""A processed video is served from the DB for any link form and any age, without touching YouTube or LLMs.

Run: venv/bin/python tests/test_cache_first.py
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

os.environ.update(
    DATABASE_URL=f"sqlite:///{tempfile.mkdtemp()}/test.db",
    GOOGLE_API_KEY="x", GROQ_API_KEY="x", TAVILY_API_KEY="x", ELEVENLABS_API_KEY="x",
)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

import agent.agent as A  # noqa: E402
from agent.agent_node import app as graph  # noqa: E402
from db.cache import save_to_cache  # noqa: E402
from db.database import SessionLocal, Video  # noqa: E402

VID = "IHZwWFHWa-w"
save_to_cache(VID, "Title", f"https://youtu.be/{VID}", "ru", 60.0, "cached summary", ["kw"], "Алекс: hi", "educational")
with SessionLocal() as s:  # well past the old 7-day TTL
    s.query(Video).filter_by(video_id=VID).update({"created_at": datetime.utcnow() - timedelta(days=30)})
    s.commit()

URLS = [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}?si=abc123",
    f"https://www.youtube.com/watch?v={VID}&t=120s",
    f"https://m.youtube.com/watch?feature=share&v={VID}",
    f"https://www.youtube.com/shorts/{VID}",
]


def must_not_run(*_args, **_kwargs):
    raise AssertionError("cache hit must not fetch the transcript")


with patch.object(A.YoutubeExtractTool, "process_video", must_not_run):
    for url in URLS:
        out = graph.invoke({"video_url": url, "skip_audio": True, "retry_count": 0, "agent_execution_order": []})
        assert out["cache_hit"], url
        assert out["summary"] == "cached summary", url
        assert out["video_metadata"]["video_id"] == VID, url

print(f"ok: {len(URLS)} link forms served from cache")
