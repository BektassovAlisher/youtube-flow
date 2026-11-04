"""Text materials: articles by link (safe download + main text extraction) and pasted text.

Both become numbered paragraphs [{"n", "section", "text"}] — the text counterpart of timed subtitles:
the summary and the answers point at «¶N», which links to that paragraph."""
import hashlib
import ipaddress
import logging
import re
import socket
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse

import requests

import config
from errors import UserError

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = (5, 20)  # connect, read
MAX_REDIRECTS = 5
MIN_TEXT_CHARS = 300
MAX_TEXT_CHARS = 300_000
PARAGRAPH_CHARS = 1500  # longer blocks are split at sentence ends

NO_TEXT = ("Не удалось найти на странице текст статьи — возможно, сайт показывает его только через JavaScript "
           "или за подпиской. Скопируйте текст и вставьте его вручную.")
PAYWALL = "Сайт не пускает к статье (нужен вход или подписка). Скопируйте текст и вставьте его вручную."
TRACKING = re.compile(r"^(utm_.*|fbclid|gclid|yclid|mc_cid|mc_eid|_hsenc|_hsmi|ref_src|spm)$")


# ---- shared helpers ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    return " ".join(text.split())


def split_long(text: str, limit: int = PARAGRAPH_CHARS) -> list[str]:
    """A wall of text becomes several paragraphs, cut at sentence ends."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?…])\s+", text):
        if len(sentence) > limit * 2:  # a long stretch without sentence ends: cut it by length
            if current:
                parts.append(current)
                current = ""
            parts += [sentence[i:i + limit] for i in range(0, len(sentence), limit)]
        elif current and len(current) + len(sentence) + 1 > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def guess_language(text: str) -> str:
    letters = re.findall(r"[a-zA-Zа-яА-ЯёЁәғқңөұүһіӘҒҚҢӨҰҮҺІ]", text[:20000])
    cyrillic = [c for c in letters if not c.isascii()]
    if len(cyrillic) < len(letters) / 2:
        return "en"
    kazakh = sum(c.lower() in "әғқңөұүһі" for c in cyrillic)
    return "kk" if kazakh > len(cyrillic) * 0.01 else "ru"


def anchor_words(text: str, count: int = 6) -> str:
    """The first words of a paragraph: enough for a #:~:text= link to scroll the original page to it."""
    words = re.sub(r"^[•\-–—*\s]+", "", text).split()[:count]
    return " ".join(words).strip(" ,.;:!?…«»\"'()")


def word_count(segments: list[dict]) -> int:
    return sum(len(s["text"].split()) for s in segments)


def _numbered(blocks: list[tuple[str | None, str]]) -> list[dict]:
    segments, n = [], 0
    for section, text in blocks:
        for part in split_long(text):
            n += 1
            segments.append({"n": n, "section": section, "text": part})
    return segments


# ---- pasted text ------------------------------------------------------------------------------

def text_id(text: str) -> str:
    """The same text pasted twice is the same material (and is served from the database)."""
    return "t-" + hashlib.sha1(_clean(text).lower().encode()).hexdigest()[:12]


def _plain_blocks(text: str) -> list[tuple[str | None, str]]:
    """Paragraphs are separated by blank lines (or by line breaks if there are none); "# Heading" starts a section."""
    raw_blocks = re.split(r"\n\s*\n", text) if re.search(r"\n\s*\n", text) else text.split("\n")
    blocks, section = [], None
    for block in raw_blocks:
        lines = block.strip().split("\n")
        heading = re.match(r"^#{1,6}\s+(.+)$", lines[0].strip())
        if heading:
            section = _clean(heading.group(1))[:200]
            lines = lines[1:]
        body = _clean(" ".join(lines))
        if body:
            blocks.append((section, body))
    return blocks


def _check_length(chars: int, what: str) -> None:
    if chars < MIN_TEXT_CHARS:
        raise UserError(f"{what} слишком короткий: нужно хотя бы {MIN_TEXT_CHARS} символов, чтобы было что конспектировать.")
    if chars > MAX_TEXT_CHARS:
        raise UserError(f"{what} слишком длинный: до {MAX_TEXT_CHARS // 1000} тысяч символов за раз. Разделите его на части.")


def parse_pasted(raw: str) -> list[dict]:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    _check_length(len(text), "Текст")
    return _numbered(_plain_blocks(text))


def title_from_text(raw: str) -> str:
    for line in raw.strip().splitlines():
        line = _clean(line.lstrip("# "))
        if line:
            if len(line) <= 90:
                return line.rstrip(".:")
            words = line.split()[:9]
            return " ".join(words).rstrip(",.:;") + "…"
    return "Текст"


# ---- articles ---------------------------------------------------------------------------------

def canonical_url(raw: str) -> str:
    """Scheme and host lowercased, no fragment, no tracking parameters: one article, one material."""
    s = (raw or "").strip()
    other_scheme = re.match(r"^[a-zA-Z][\w+.-]*:(?!//|\d)", s)  # mailto:, javascript:, data: — but not host:port
    if "://" not in s and not other_scheme:
        s = "https://" + s
    try:
        u = urlparse(s)
        port = u.port
    except ValueError:
        raise UserError("Ссылка выглядит неправильной — проверьте адрес.")
    if u.scheme not in ("http", "https") or not u.hostname:
        raise UserError("Нужна ссылка на страницу, начинающаяся с http:// или https://.")
    netloc = u.hostname.lower() + (f":{port}" if port and port not in (80, 443) else "")
    path = quote(unquote(u.path or "/"), safe="/:@!$&'()*+,;=-._~")  # "%D0%93…" and "Г…" are the same page
    query = urlencode([(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k.lower())])
    return urlunparse((u.scheme.lower(), netloc, path, u.params, query, ""))


def article_id(url: str) -> str:
    return "a-" + hashlib.sha1(url.encode()).hexdigest()[:12]


def check_host(host: str, port: int) -> None:
    """SSRF guard: the server must not be talked into opening localhost, the Docker network or cloud metadata."""
    if config.ALLOW_PRIVATE_URLS:
        return
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        raise UserError("Не удалось найти сайт по этой ссылке — проверьте адрес.")
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UserError("Эта ссылка ведёт во внутреннюю сеть — такие адреса сервер не открывает.")


def download(url: str) -> tuple[str, bytes, str]:
    """(final url, body, content type). Every redirect is checked again, size and time are limited."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8",
                            "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8,*/*;q=0.5"})
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        u = urlparse(current)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise UserError("Сайт перенаправил на неподдерживаемый адрес.")
        check_host(u.hostname, u.port or (443 if u.scheme == "https" else 80))
        try:
            r = session.get(current, allow_redirects=False, timeout=TIMEOUT, stream=True)
        except requests.Timeout:
            raise UserError("Сайт не ответил вовремя. Попробуйте позже или вставьте текст статьи вручную.", status=503)
        except requests.RequestException as e:
            log.info("статья %s: %s", current, e)
            raise UserError("Не удалось открыть страницу. Проверьте ссылку или вставьте текст статьи вручную.", status=503)
        with r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                current = urljoin(current, r.headers["location"])
                continue
            if r.status_code in (401, 402, 403):
                raise UserError(PAYWALL)
            if r.status_code in (404, 410):
                raise UserError("Страница не найдена — проверьте ссылку.")
            if r.status_code == 429:
                raise UserError("Сайт ограничил частоту запросов. Попробуйте позже или вставьте текст вручную.", 503)
            if r.status_code >= 400:
                raise UserError(f"Сайт ответил ошибкой {r.status_code}. Попробуйте позже или вставьте текст вручную.", 502)
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ctype == "application/pdf":
                raise UserError("По ссылке PDF — документы пока не поддерживаются. Скопируйте текст и вставьте его вручную.")
            if ctype and ctype not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise UserError(f"По ссылке не веб-страница, а файл ({ctype}).")
            body = bytearray()
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise UserError("Страница слишком большая (больше 5 МБ).")
            return current, bytes(body), ctype
    raise UserError("Слишком много перенаправлений — откройте статью в браузере и скопируйте адрес оттуда.")


def _block_text(el) -> str:
    if el.tag == "list":
        return "\n".join("• " + _clean("".join(item.itertext())) for item in el.iter("item") if _clean("".join(item.itertext())))
    if el.tag == "table":
        rows = [" | ".join(_clean("".join(cell.itertext())) for cell in row.iter("cell")) for row in el.iter("row")]
        return "\n".join(r for r in rows if r.strip(" |"))
    return _clean("".join(el.itertext()))


def extract(body: bytes, url: str, content_type: str = "text/html") -> dict:
    """Main text of the page (menus, ads, comments and footers dropped) as numbered paragraphs, plus metadata."""
    host = (urlparse(url).hostname or "").removeprefix("www.")
    if content_type == "text/plain":
        text = body.decode("utf-8", errors="replace").replace("\r\n", "\n")
        segments = _numbered(_plain_blocks(text))
        meta = {"title": title_from_text(text), "site": host, "author": None, "image": None}
    else:
        import trafilatura

        doc = trafilatura.bare_extraction(body, url=url, with_metadata=True, include_comments=False,
                                          include_tables=True, include_formatting=False, include_links=False,
                                          include_images=False)
        if doc is None or doc.body is None:
            raise UserError(NO_TEXT)
        blocks, section = [], None
        for el in doc.body:
            text = _block_text(el)
            if not text:
                continue
            if el.tag == "head":
                if text != doc.title:  # the h1 repeats the title
                    section = text[:200]
                continue
            blocks.append((section, text))
        segments = _numbered(blocks)
        meta = {"title": doc.title, "site": doc.sitename or host, "author": doc.author, "image": doc.image}
    chars = sum(len(s["text"]) for s in segments)
    if chars < MIN_TEXT_CHARS:
        raise UserError(NO_TEXT)
    _check_length(chars, "Текст статьи")
    sample = " ".join(s["text"] for s in segments[:40])
    return {
        "segments": segments,
        "title": (meta["title"] or host or "Статья")[:300],
        "site": meta["site"],
        "author": meta["author"],
        "image": meta["image"] if (meta["image"] or "").startswith(("https://", "http://")) else None,
        "language": guess_language(sample),
        "anchors": {str(s["n"]): anchor_words(s["text"]) for s in segments},
    }


def fetch_article(url: str) -> dict:
    final_url, body, content_type = download(url)
    article = extract(body, final_url, content_type)
    log.info("статья %s: %d абзацев, %d слов", final_url, len(article["segments"]), word_count(article["segments"]))
    return article
