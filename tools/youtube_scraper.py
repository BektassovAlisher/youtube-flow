from youtube_transcript_api import YouTubeTranscriptApi
from dataclasses import dataclass
from typing import List, Any
import re


@dataclass
class TranscriptData:
    """Результат извлечения транскрипта"""
    segments: List[Any]       
    full_text: str            
    metadata: dict            


class YoutubeExtractTool:
    def __init__(self, languages: List[str] = ["ru", "en", "kk"]):
        self.languages = languages

    def extract_video_id(self, url: str) -> str:
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
        if not match:
            raise ValueError(f"Не удалось найти video_id в ссылке: {url}")
        return match.group(1)

    def segments_to_text(self, segments: list) -> str:
        parts = []
        for s in segments:
            text = s.text if hasattr(s, "text") else s.get("text", "")
            parts.append(text)
        return " ".join(parts)

    def get_duration(self, segments: list) -> float:
        if not segments:
            return 0.0
        last = segments[-1]
        start = last.start if hasattr(last, "start") else last.get("start", 0)
        duration = last.duration if hasattr(last, "duration") else last.get("duration", 0)
        return round(start + duration, 2)

    def process_video(self, video_url: str) -> TranscriptData:
        print("🎬 Агент 1: Получаю транскрипт...")

        video_id = self.extract_video_id(video_url)

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id, languages=self.languages)

        segments = list(transcript)
        full_text = self.segments_to_text(segments)
        total_duration = self.get_duration(segments)

        detected_language = getattr(transcript, "language_code", self.languages[0])

        metadata = {
            "video_id": video_id,
            "video_url": video_url,
            "language": detected_language,
            "total_duration_sec": total_duration,
            "segment_count": len(segments),
        }

        print(f"✅ Agent 1: {len(segments)} сегментов, {len(full_text)} кусоков, {round(total_duration/60, 1)} минут")

        return TranscriptData(
            segments=segments,
            full_text=full_text,
            metadata=metadata,
        )