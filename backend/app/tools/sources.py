"""Kinds of material and how to point at a place inside each of them.

youtube — timed subtitles, places are [MM:SS] and link to youtu.be/<id>?t=<sec>
media   — video/audio from other sites or a media file: [MM:SS], linking to the original at that second
article — paragraphs of a web page, places are [¶N] and link to the original page via #:~:text=
text    — pasted paragraphs, places are [¶N] and link to the paragraph on the material page (#pN)"""
from typing import Callable
from urllib.parse import quote, urlparse  # noqa: F401  (urlparse: used by detect_url)

from errors import UserError
from tools import media, text_sources
from tools.chunking_transcript import seconds_to_youtube_url
from tools.youtube_scraper import HOSTS as YOUTUBE_HOSTS
from tools.youtube_scraper import VIDEO_ID, parse_video_id, watch_url

KINDS = ("youtube", "media", "article", "text")


def detect_url(raw: str) -> tuple[str, str, str]:
    """(kind, material id, url to store) for a link typed by a person."""
    s = (raw or "").strip()
    if VIDEO_ID.match(s):  # a bare 11-character YouTube id
        return "youtube", s, watch_url(s)
    first = s.split("/")[0]
    if not s or ("://" not in s and "." not in first and ":" not in first):
        raise UserError("Вставьте ссылку на видео, подкаст или статью.")
    try:
        host = (urlparse(s if "://" in s else "https://" + s).hostname or "").lower().removeprefix("www.")
    except ValueError:
        raise UserError("Ссылка выглядит неправильной — проверьте адрес.")
    if host in YOUTUBE_HOSTS:
        video_id = parse_video_id(s)
        return "youtube", video_id, watch_url(video_id)
    url = text_sources.canonical_url(s)
    if media.is_media_url(url):
        return "media", media.media_id(url), url
    return "article", text_sources.article_id(url), url


def fragment_url(url: str, words: str | None) -> str:
    """Link that opens the page scrolled to the words and highlights them (text fragments)."""
    if not words:
        return url
    return f"{url}#:~:text={quote(words, safe='').replace('-', '%2D')}"


def link_builder(kind: str, url: str | None, anchors: dict | None) -> Callable[[int], str] | None:
    """Paragraph number → link, for text materials; None for videos (their links come from the time)."""
    if kind == "article":
        return lambda n: fragment_url(url or "", (anchors or {}).get(str(n)))
    if kind == "text":
        return lambda n: f"#p{n}"
    return None


def time_builder(kind: str, url: str | None, video_id: str) -> Callable[[float], str]:
    """Second → link, for timed materials."""
    if kind == "media":
        return lambda sec: media.time_link(url or "", sec)
    return lambda sec: seconds_to_youtube_url(video_id, sec)


def prompt_text(segments: list[dict]) -> str:
    """Paragraphs as "[¶N] text", with the original section headings: the text counterpart of [MM:SS]."""
    out, section = [], None
    for seg in segments:
        if seg.get("section") and seg["section"] != section:
            section = seg["section"]
            out.append(f"\n## {section}")
        out.append(f"[¶{seg['n']}] {seg['text']}")
    return "\n".join(out).strip()
