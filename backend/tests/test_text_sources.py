import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import config
from errors import UserError
from tools import sources, text_sources as ts

ARTICLE = (Path(__file__).parent / "fixtures" / "article.html").read_bytes()


# ---- links ------------------------------------------------------------------------------------

def test_canonical_url_drops_tracking_and_fragment():
    assert ts.canonical_url("Habr.com/ru/articles/123/?utm_source=tg&page=2&fbclid=x#comments") == \
        "https://habr.com/ru/articles/123/?page=2"
    assert ts.article_id("https://habr.com/a") == ts.article_id(ts.canonical_url("https://HABR.com/a#top"))


@pytest.mark.parametrize("link, kind", [
    ("https://www.youtube.com/watch?v=aircAruvnKk", "youtube"),
    ("youtu.be/aircAruvnKk", "youtube"),
    ("aircAruvnKk", "youtube"),
    ("https://habr.com/ru/articles/123456/", "article"),
    ("ru.wikipedia.org/wiki/Градиентный_спуск", "article"),
    ("https://vk.com/@team-article", "article"),  # vk articles are fine, vk videos are not
])
def test_detect_url(link, kind):
    detected_kind, material_id, url = sources.detect_url(link)
    assert detected_kind == kind
    assert url.startswith("https://")
    assert material_id.startswith("a-") if kind == "article" else len(material_id) == 11


@pytest.mark.parametrize("link, hint", [
    ("", "Вставьте ссылку"),
    ("какой-то текст", "Вставьте ссылку"),
    ("https://vimeo.com/123", "vimeo.com пока не поддерживаются"),
    ("https://vk.com/video-1_2", "vk.com пока не поддерживаются"),
    ("https://www.youtube.com/@channel", "канал"),
    ("mailto:someone@example.com", "http:// или https://"),
])
def test_detect_url_explains_errors(link, hint):
    with pytest.raises(UserError) as e:
        sources.detect_url(link)
    assert hint in e.value.message


def test_fragment_links():
    assert sources.fragment_url("https://a.ru/x", "Градиентный спуск — это") == \
        "https://a.ru/x#:~:text=%D0%93%D1%80%D0%B0%D0%B4%D0%B8%D0%B5%D0%BD%D1%82%D0%BD%D1%8B%D0%B9%20%D1%81%D0%BF%D1%83%D1%81%D0%BA%20%E2%80%94%20%D1%8D%D1%82%D0%BE"
    assert sources.fragment_url("https://a.ru/x", "mini-batch") == "https://a.ru/x#:~:text=mini%2Dbatch"  # "-" is syntax
    assert sources.link_builder("text", "", None)(7) == "#p7"
    assert sources.link_builder("youtube", "u", None) is None


# ---- SSRF guard -------------------------------------------------------------------------------

@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "172.18.0.5", "192.168.1.1", "169.254.169.254",
                                     "100.64.0.1", "::1", "fd00::1", "::ffff:10.0.0.1", "0.0.0.0"])
def test_internal_addresses_are_refused(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (address, 80))])
    with pytest.raises(UserError, match="внутреннюю сеть"):
        ts.check_host("evil.example", 80)


def test_public_address_is_allowed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))])
    ts.check_host("example.com", 443)


def test_unknown_host(monkeypatch):
    def fail(*a, **k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(UserError, match="Не удалось найти сайт"):
        ts.check_host("nope.invalid", 443)


# ---- download ---------------------------------------------------------------------------------

class Site(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        routes = {
            "/article": (200, "text/html; charset=utf-8", ARTICLE),
            "/paywall": (403, "text/html", b"<html>subscribe</html>"),
            "/missing": (404, "text/html", b"not found"),
            "/doc.pdf": (200, "application/pdf", b"%PDF-1.7"),
            "/huge": (200, "text/html", b"<p>" + b"x" * (ts.MAX_BYTES + 10)),
            "/empty": (200, "text/html", b"<html><body><nav>menu</nav><div id=app></div><script>load()</script></body></html>"),
        }
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/article")
            self.end_headers()
            return
        if self.path == "/to-internal":
            self.send_response(301)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/article")
            self.end_headers()
            return
        status, ctype, body = routes.get(self.path, (404, "text/plain", b""))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://localhost:{server.server_port}"
    server.shutdown()


@pytest.fixture
def allow_local(monkeypatch):
    monkeypatch.setattr(config, "ALLOW_PRIVATE_URLS", True)


def test_article_is_downloaded_and_extracted(site, allow_local):
    article = ts.fetch_article(f"{site}/moved")  # redirects are followed
    assert article["title"] == "Градиентный спуск простыми словами"
    assert article["site"] == "Хабр" and article["author"] == "Иван Петров"
    assert article["image"] == "https://habrastorage.org/cover.png" and article["language"] == "ru"
    texts = " ".join(s["text"] for s in article["segments"])
    assert "Представьте, что вы стоите на склоне" in texts
    for junk in ("Мы используем cookies", "10 лучших ноутбуков", "Пользовательское соглашение", "Главная"):
        assert junk not in texts  # menus, banners, sidebars and footers are dropped
    sections = [s["section"] for s in article["segments"]]
    assert "Формула и шаг обучения" in sections and sections[0] is None
    bullets = next(s["text"] for s in article["segments"] if s["text"].startswith("•"))
    assert bullets.count("•") == 2
    assert article["anchors"]["2"] == "Представьте, что вы стоите на склоне"
    assert [s["n"] for s in article["segments"]] == list(range(1, len(article["segments"]) + 1))


def test_local_site_is_refused_by_default(site):
    with pytest.raises(UserError, match="внутреннюю сеть"):
        ts.download(f"{site}/article")


def test_redirect_to_internal_address_is_checked_again(site, monkeypatch):
    original = ts.check_host
    monkeypatch.setattr(ts, "check_host", lambda host, port: None if host == "localhost" else original(host, port))
    with pytest.raises(UserError, match="внутреннюю сеть"):
        ts.download(f"{site}/to-internal")


@pytest.mark.parametrize("path, hint", [
    ("/paywall", "нужен вход или подписка"),
    ("/missing", "Страница не найдена"),
    ("/doc.pdf", "PDF"),
    ("/huge", "слишком большая"),
    ("/empty", "Не удалось найти на странице текст"),
])
def test_site_problems_are_explained(site, allow_local, path, hint):
    with pytest.raises(UserError) as e:
        ts.fetch_article(site + path)
    assert hint in e.value.message


# ---- pasted text ------------------------------------------------------------------------------

def test_pasted_text_becomes_numbered_paragraphs():
    text = ("# Введение\n\n" + "Нейросеть — это функция с параметрами. " * 3 + "\n\n" + "Обучение подбирает веса. " * 90
            + "\n\n## Итоги\nГлавное — практика и терпение. Повторяйте каждый день.")
    segments = ts.parse_pasted(text)
    assert segments[0] == {"n": 1, "section": "Введение", "text": ("Нейросеть — это функция с параметрами. " * 3).strip()}
    assert all(len(s["text"]) <= ts.PARAGRAPH_CHARS for s in segments)  # the long paragraph was split at sentences
    assert segments[-1]["section"] == "Итоги" and segments[-1]["text"].startswith("Главное")
    assert [s["n"] for s in segments] == list(range(1, len(segments) + 1))
    assert ts.title_from_text(text) == "Введение"
    assert ts.text_id(text) == ts.text_id("  " + text.replace("\n\n", "\n\n\n") + " ")


def test_pasted_text_limits():
    with pytest.raises(UserError, match="слишком короткий"):
        ts.parse_pasted("Коротко.")
    with pytest.raises(UserError, match="слишком длинный"):
        ts.parse_pasted("слово " * 60_000)


def test_language_guess():
    assert ts.guess_language("Градиентный спуск ищет минимум функции.") == "ru"
    assert ts.guess_language("Gradient descent finds the minimum.") == "en"
    assert ts.guess_language("Нейрондық желі деген не? Бұл үлгі өзі үйренеді.") == "kk"
