from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from typing import List, Any


def seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def seconds_to_youtube_url(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


class ChukingTranscript:
    def __init__(self, chunk_size: int = 3000, chunk_overlap: int = 200):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        )

    def to_timestamped_text(self, segments: List[Any]) -> str:
        """
        Склеивает все сегменты в одну строку с таймстампами.
        Передаётся напрямую в LLM — один запрос на всё видео.

        Результат:
        [00:01] текст сегмента
        [00:05] следующий сегмент
        """
        lines = []
        for seg in segments:
            text = seg.text if hasattr(seg, "text") else seg.get("text", "")
            start = seg.start if hasattr(seg, "start") else seg.get("start", 0)
            timestamp = seconds_to_timestamp(start)
            lines.append(f"[{timestamp}] {text.strip()}")
        return "\n".join(lines)

    def _build_documents(self, segments: List[Any], video_id: str) -> List[Document]:
        """
        Группируем сегменты по ~500 символов сохраняя таймстамп начала группы.
        Используется только если нужна нарезка на чанки (длинные видео 2+ часа).
        """
        docs = []
        buffer_text = []
        buffer_start = None
        buffer_end = 0
        buffer_chars = 0

        for seg in segments:
            text = seg.text if hasattr(seg, "text") else seg.get("text", "")
            start = seg.start if hasattr(seg, "start") else seg.get("start", 0)
            duration = seg.duration if hasattr(seg, "duration") else seg.get("duration", 0)

            if buffer_start is None:
                buffer_start = start

            buffer_text.append(text.strip())
            buffer_end = start + duration
            buffer_chars += len(text)

            if buffer_chars >= 500:
                docs.append(Document(
                    page_content=" ".join(buffer_text),
                    metadata={
                        "start_seconds": round(buffer_start, 2),
                        "end_seconds": round(buffer_end, 2),
                        "timestamp": seconds_to_timestamp(buffer_start),
                        "youtube_url": seconds_to_youtube_url(video_id, buffer_start),
                    }
                ))
                buffer_text = []
                buffer_start = None
                buffer_chars = 0

        if buffer_text:
            docs.append(Document(
                page_content=" ".join(buffer_text),
                metadata={
                    "start_seconds": round(buffer_start, 2),
                    "end_seconds": round(buffer_end, 2),
                    "timestamp": seconds_to_timestamp(buffer_start),
                    "youtube_url": seconds_to_youtube_url(video_id, buffer_start),
                }
            ))

        return docs

    def split(self, segments: List[Any], video_id: str) -> List[Document]:
        """
        Используй для длинных видео (2+ часа) когда транскрипт
        не влезает в контекст LLM целиком.
        Для обычных видео используй to_timestamped_text().
        """
        docs = self._build_documents(segments, video_id)
        chunks = self.splitter.split_documents(docs)

        total = len(chunks)
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["total_chunks"] = total

        print(f"📦 Chunker: {len(segments)} segments → {total} chunks")
        return chunks