"""Teszt-segédek: szintetikus dokumentumok PDF nélkül (szavakból) és valódi PDF-ként (reportlab)."""

import io

from app.services.pdf_text import Page, PdfDocument, Word, build_lines

PAGE_W, PAGE_H = 595.0, 842.0


def make_doc(rows: list[tuple[float, list[tuple[float, str]]]], size: float = 9.0) -> PdfDocument:
    """`rows`: [(top, [(x0, "szó vagy több szó"), ...]), ...] – a megadott x-től kezdve, normál szóközökkel."""
    words: list[Word] = []
    order = 0
    char_w = size * 0.5
    for top, items in rows:
        for x0, text in items:
            x = x0
            for tok in text.split():
                width = len(tok) * char_w
                words.append(Word(tok, x, x + width, top, top + size, size, 1, order))
                order += 1
                x += width + size * 0.3
    lines = build_lines(words, 1)
    return PdfDocument(pages=[Page(1, PAGE_W, PAGE_H, lines)], full_text="\n".join(ln.text for ln in lines))


def make_pdf(items: list[tuple[float, float, str]] | None, size: float = 9.0, draw_only: bool = False,
             user_password: str | None = None) -> bytes:
    """Valódi PDF: `items` = [(x, top, szöveg)], a koordináták felülről mérve (mint a pdfplumber-nél).

    `user_password`: titkosított PDF ezzel a megnyitási jelszóval (`""` = csak tulajdonosi jelszó, megnyitható).
    Figyelem: a beépített Helvetica csak Latin-1 karaktereket tud – az `ő`/`ű` betűk elvesznek,
    ezért a szintetikus PDF-ekben ilyen betűt tartalmazó címkét ne használj (pl. „Vevő” helyett „Bill to”).
    """
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    encrypt = StandardEncryption(user_password, ownerPassword="owner") if user_password is not None else None
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H), encrypt=encrypt)
    if draw_only:
        c.rect(50, 50, 200, 100, fill=1)
    for x, top, text in items or []:
        c.setFont("Helvetica", size)
        c.drawString(x, PAGE_H - top - size, text)
    c.showPage()
    c.save()
    return buf.getvalue()
