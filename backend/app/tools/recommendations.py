"""Courses and books on the topic of a video, through Tavily search on known course and book sites."""
import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from db import cache as repo
from errors import require_env

log = logging.getLogger(__name__)

COURSE_SITES = {
    "ru": ["stepik.org", "openedu.ru", "practicum.yandex.ru", "skillbox.ru", "netology.ru", "intuit.ru",
           "coursera.org", "edx.org", "udemy.com", "khanacademy.org"],
    "en": ["coursera.org", "edx.org", "udemy.com", "khanacademy.org", "udacity.com", "freecodecamp.org",
           "ocw.mit.edu", "futurelearn.com", "classcentral.com"],
}
BOOK_SITES = {
    "ru": ["litres.ru", "labirint.ru", "chitai-gorod.ru", "ozon.ru", "piter.com", "dmkpress.com", "alpinabook.ru",
           "mann-ivanov-ferber.ru", "goodreads.com"],
    "en": ["goodreads.com", "oreilly.com", "manning.com", "nostarch.com", "pragprog.com", "springer.com",
           "books.google.com", "amazon.com"],
}
SKIP_HOSTS = ("youtube.com", "youtu.be")


def _parse(raw) -> list[dict]:
    results = raw.get("results", []) if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    out = []
    for r in results:
        url = r.get("url") if isinstance(r, dict) else None
        if url and not (urlparse(url).hostname or "").removeprefix("www.").endswith(SKIP_HOSTS):
            out.append({"title": r.get("title") or url, "url": url})
    return out


def _search(query: str, sites: list[str]) -> list[dict]:
    from langchain_tavily import TavilySearch

    tool = TavilySearch(max_results=6, topic="general")
    found = _parse(tool.invoke({"query": query, "include_domains": sites}))
    if len(found) < 3:  # too narrow for this topic: widen to the whole web
        found += _parse(tool.invoke({"query": query}))
    unique = {}
    for item in found:
        unique.setdefault(item["url"].rstrip("/"), item)
    return list(unique.values())[:5]


def find(video: dict) -> dict:
    require_env("TAVILY_API_KEY")
    topic = ", ".join(video.get("keywords", [])[:3]) or (video.get("title") or "")
    lang = "en" if video.get("language") == "en" else "ru"
    courses_q = f"online course {topic}" if lang == "en" else f"онлайн-курс {topic}"
    books_q = f"book {topic}" if lang == "en" else f"книга {topic}"
    with ThreadPoolExecutor(2) as pool:  # both searches at once
        courses = pool.submit(_search, courses_q, COURSE_SITES[lang])
        books = pool.submit(_search, books_q, BOOK_SITES[lang])
        rec = {"courses": courses.result(), "books": books.result()}
    if rec["courses"] or rec["books"]:
        repo.save_recommendation(video["video_id"], rec)
    else:
        log.info("%s: рекомендаций не нашлось, не кэширую", video["video_id"])
    return rec
