from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def seconds_to_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, m, s = total // 3600, (total % 3600) // 60, total % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def seconds_to_youtube_url(video_id: str, seconds: float) -> str:
    return f"https://youtu.be/{video_id}?t={int(seconds)}"


def to_timestamped_text(segments: list[dict], every: float = 30.0) -> str:
    """Transcript as paragraphs of ~`every` seconds, one [MM:SS] mark per paragraph.

    A mark on every caption line (a few seconds each) spent ~15-20 % of the prompt on timestamps."""
    paragraphs, current, start = [], [], None
    for seg in segments:
        if start is None:
            start = seg["start"]
        current.append(seg["text"])
        if seg["start"] + seg.get("duration", 0) - start >= every:
            paragraphs.append(f"[{seconds_to_timestamp(start)}] {' '.join(current)}")
            current, start = [], None
    if current:
        paragraphs.append(f"[{seconds_to_timestamp(start)}] {' '.join(current)}")
    return "\n".join(paragraphs)


def plain_text(segments: list[dict]) -> str:
    return " ".join(seg["text"] for seg in segments)


class TranscriptChunker:
    """Pieces of consecutive captions (~500 characters) or paragraphs (~700) for the vector index.

    Every piece has a place label ("12:34" or "¶7"), a link to that place and an `order` key that keeps
    the answers' sources in the order of the material."""

    def __init__(self, target_chars: int = 500, max_chars: int = 1200):
        self.target_chars = target_chars
        # only for unusually long single captions or paragraphs
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chars, chunk_overlap=150, separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
        )

    def split(self, segments: list[dict], video_id: str, link_for=None) -> list[Document]:
        """`link_for(n)` builds the link of paragraph n for text materials; videos link to the second."""
        docs = self._paragraphs(segments, link_for) if segments and "start" not in segments[0] \
            else self._captions(segments, video_id)
        chunks = self.splitter.split_documents(docs)
        for i, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = i
            chunk.metadata["total_chunks"] = len(chunks)
        return chunks

    def _captions(self, segments: list[dict], video_id: str) -> list[Document]:
        docs, buffer, start, end = [], [], None, 0.0

        def flush():
            url = seconds_to_youtube_url(video_id, start)
            docs.append(Document(
                page_content=" ".join(buffer),
                metadata={
                    "start_seconds": round(start, 2),
                    "end_seconds": round(end, 2),
                    "timestamp": seconds_to_timestamp(start),
                    "youtube_url": url,
                    "link": url,
                    "order": round(start, 2),
                },
            ))

        for seg in segments:
            if start is None:
                start = seg["start"]
            buffer.append(seg["text"].strip())
            end = seg["start"] + seg.get("duration", 0)
            if sum(len(t) for t in buffer) >= self.target_chars:
                flush()
                buffer, start = [], None
        if buffer:
            flush()
        return docs

    def _paragraphs(self, segments: list[dict], link_for) -> list[Document]:
        docs, buffer, first, section = [], [], None, None
        target = int(self.target_chars * 1.4)

        def flush():
            docs.append(Document(
                page_content=" ".join(buffer),
                metadata={
                    "timestamp": f"¶{first}",
                    "link": link_for(first) if link_for else "",
                    "order": first,
                    "section": section or "",
                },
            ))

        for seg in segments:
            if buffer and seg.get("section") != section:  # a piece never spans two sections of the original
                flush()
                buffer, first = [], None
            if first is None:
                first, section = seg["n"], seg.get("section")
            buffer.append(seg["text"].strip())
            if sum(len(t) for t in buffer) >= target:
                flush()
                buffer, first = [], None
        if buffer:
            flush()
        return docs
