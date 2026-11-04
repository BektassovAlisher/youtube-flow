"""Uploaded PDF, TXT and Markdown files become text materials, page by page for PDFs."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

import jobs
from api.api import app
from errors import UserError
from tools import text_sources as ts

PAGE_1 = ["Gradient descent finds the minimum of a function by taking small steps.",
          "Each step goes against the gradi-", "ent, the direction in which the function grows the fastest.",
          "This simple idea trains almost every neural network used today."]
PAGE_2 = ["The learning rate sets the size of every step of the descent.",
          "Too large a step overshoots the minimum and the training diverges.",
          "Too small a step makes the training slow, so the rate is tuned by experiment."]


def make_pdf(pages: list[list[str]], title: str | None = "Gradient descent notes") -> bytes:
    """A small valid PDF with real text (Helvetica), one content stream per page."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None]
    kids = []
    for lines in pages:
        ops = "BT /F1 11 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
        objects.append(f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objects)} 0 R "
                       f"/Resources << /Font << /F1 FONT 0 R >> >> >>")
        kids.append(len(objects))
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font = len(objects)
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    objects = [o.replace("FONT", str(font)) for o in objects]
    info = None
    if title:
        objects.append(f"<< /Title ({title}) >>")
        info = len(objects)
    out, offsets = BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R" + (f" /Info {info} 0 R" if info else "") + " >>"
    out.write(f"trailer\n{trailer}\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def test_pdf_pages_become_sections():
    doc = ts.parse_document("notes.pdf", make_pdf([PAGE_1, PAGE_2]))
    assert doc["source"] == "pdf" and doc["title"] == "Gradient descent notes" and doc["language"] == "en"
    sections = [s["section"] for s in doc["segments"]]
    assert sections[0] == "Страница 1" and sections[-1] == "Страница 2"
    assert "against the gradient, the direction" in doc["text"]  # the hyphenated word is whole again
    assert "Too small a step" in doc["segments"][-1]["text"]


def test_junk_pdf_title_falls_back_to_the_file_name():
    doc = ts.parse_document("my_lecture_notes.pdf", make_pdf([PAGE_1, PAGE_2], title="Microsoft Word - notes.docx"))
    assert doc["title"] == "my lecture notes"


def test_encrypted_and_scanned_pdfs():
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(BytesIO(make_pdf([PAGE_1, PAGE_2]))))
    writer.encrypt("secret")
    locked = BytesIO()
    writer.write(locked)
    with pytest.raises(UserError, match="защищён паролем"):
        ts.parse_document("locked.pdf", locked.getvalue())

    blank = PdfWriter()
    blank.add_blank_page(width=612, height=792)
    scan = BytesIO()
    blank.write(scan)
    with pytest.raises(UserError, match="похоже, это скан"):
        ts.parse_document("scan.pdf", scan.getvalue())

    with pytest.raises(UserError, match="Не удалось прочитать PDF"):
        ts.parse_document("broken.pdf", b"not a pdf at all, just bytes " * 20)


def test_text_files():
    russian = ("Градиентный спуск ищет минимум функции. " * 12).strip()
    doc = ts.parse_document("конспект.txt", russian.encode("cp1251"))  # an old Windows file
    assert doc["text"].startswith("Градиентный спуск") and doc["language"] == "ru" and doc["source"] == "file"
    assert doc["title"] == "конспект"
    md = "# Шаг обучения\n\n" + "Learning rate задаёт длину шага градиентного спуска. " * 8
    assert ts.parse_document("notes.md", md.encode()).get("title") == "Шаг обучения"


@pytest.mark.parametrize("name, data, hint", [
    ("slides.pptx", b"x" * 500, "PDF, TXT и Markdown"),
    ("empty.txt", b"", "пустой"),
    ("short.txt", "Мало текста.".encode(), "слишком короткий"),
])
def test_document_errors(name, data, hint):
    with pytest.raises(UserError) as e:
        ts.parse_document(name, data)
    assert hint in e.value.message


def test_too_big(monkeypatch):
    monkeypatch.setattr(ts, "MAX_FILE_BYTES", 1000)
    with pytest.raises(UserError, match="слишком большой"):
        ts.parse_document("big.txt", b"a" * 1001)


def test_upload_through_the_api(llm, youtube):
    pdf = make_pdf([PAGE_1, PAGE_2])
    with TestClient(app) as client:
        r = client.post("/videos/upload", files={"file": ("notes.pdf", pdf, "application/pdf")})
        body = r.json()
        assert r.status_code == 200 and body["kind"] == "text" and body["title"] == "Gradient descent notes"
        vid = body["video_id"]
        jobs.hub.wait(vid, "process", timeout=30)
        assert client.get(f"/videos/{vid}").json()["status"] == "ready"
        assert client.get("/videos").json()[0]["source"] == "pdf"
        assert client.get(f"/videos/{vid}/source").json()["segments"][0]["section"] == "Страница 1"

        again = client.post("/videos/upload", files={"file": ("copy.pdf", pdf, "application/pdf")}).json()
        assert again["video_id"] == vid and again["jobs"] == []  # the same document: served from the database

        named = client.post("/videos/upload", data={"title": "Мои заметки"},
                            files={"file": ("other.txt", ("Шаг обучения задаёт скорость. " * 15).encode(), "text/plain")})
        assert named.json()["title"] == "Мои заметки"
        jobs.hub.wait(named.json()["video_id"], "process", timeout=30)

        bad = client.post("/videos/upload", files={"file": ("x.docx", b"PK..." * 100, "application/octet-stream")})
        assert bad.status_code == 400 and "PDF, TXT и Markdown" in bad.json()["detail"]
