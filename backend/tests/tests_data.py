from conftest import SCRIPT, SEGMENTS, SUMMARY
from db import cache as repo


def seed_video(video_id: str, transcript: bool = True, script: bool = True) -> None:
    """A fully processed video, as the pipeline would leave it."""
    repo.begin_processing(video_id, f"https://www.youtube.com/watch?v={video_id}")
    if transcript:
        repo.save_transcript(video_id, SEGMENTS, language="ru", source="manual", duration_sec=1200.0,
                             title="Нейросети", channel="Канал")
    repo.save_classification(video_id, {"category": "educational", "is_suitable": True, "confidence": 0.9,
                                        "reason": "лекция"})
    repo.save_summary(video_id, SUMMARY)
    repo.save_keywords(video_id, ["градиентный спуск", "нейрон", "вес"])
    if script:
        repo.save_script(video_id, SCRIPT)
    repo.finish(video_id)
