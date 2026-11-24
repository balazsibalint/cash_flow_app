import io
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from app.services.extraction.normalize import fold

LINE_TOLERANCE = 3.0
MIN_SEGMENT_GAP = 6.0


class PdfReadError(Exception):
    """A fájl nem olvasható PDF-ként, vagy nincs benne kinyerhető szöveg."""


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    page: int
    order: int  # sorszám a tartalomfolyamban

    @property
    def folded(self) -> str:
        return fold(self.text)


@dataclass
class Segment:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)


@dataclass
class Line:
    words: list[Word]
    page: int
    index: int  # globális sorindex (oldalakon át)
    segments: list[Segment] = field(default_factory=list)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Page:
    number: int
    width: float
    height: float
    lines: list[Line]


@dataclass
class PdfDocument:
    pages: list[Page]
    full_text: str

    @property
    def lines(self) -> list[Line]:
        return [ln for p in self.pages for ln in p.lines]

    @property
    def layout_text(self) -> str:
        """A rekonstruált sorok szövege (oldalanként), az egymásra nyomtatott szövegnél is olvasható."""
        parts = []
        for p in self.pages:
            parts.append(f"--- oldal {p.number} ---")
            parts.extend(ln.text for ln in p.lines)
        return "\n".join(parts)


def _overlaps(words: list[Word]) -> bool:
    ws = sorted(words, key=lambda w: w.x0)
    for a, b in zip(ws, ws[1:]):
        overlap = a.x1 - b.x0
        if overlap > 0.3 * min(a.x1 - a.x0, b.x1 - b.x0):
            return True
    return False


def _segments(words: list[Word]) -> list[Segment]:
    segs: list[list[Word]] = [[words[0]]]
    for prev, w in zip(words, words[1:]):
        gap = w.x0 - prev.x1
        threshold = max(MIN_SEGMENT_GAP, 1.0 * max(prev.size, w.size))
        if gap > threshold:
            segs.append([w])
        else:
            segs[-1].append(w)
    return [Segment(s) for s in segs]


def build_lines(words: list[Word], page: int, start_index: int = 0) -> list[Line]:
    """Szavak → sorok (és szegmensek). Tisztán geometriai, teszteléshez PDF nélkül is hívható."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and w.top - lines[-1][0].top <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])

    out: list[Line] = []
    for i, lw in enumerate(lines):
        ordered = sorted(lw, key=lambda w: w.order) if _overlaps(lw) else sorted(lw, key=lambda w: w.x0)
        line = Line(words=ordered, page=page, index=start_index + i)
        line.segments = _segments(ordered)
        out.append(line)
    return out


def load_pdf(source: bytes | str | Path) -> PdfDocument:
    """PDF beolvasása. Hibás vagy szöveg nélküli fájlnál `PdfReadError`."""
    try:
        fp = io.BytesIO(source) if isinstance(source, bytes) else source
        with pdfplumber.open(fp) as pdf:
            pages: list[Page] = []
            texts: list[str] = []
            index = 0
            order = 0
            for pno, pg in enumerate(pdf.pages, start=1):
                raw = pg.extract_words(
                    x_tolerance=1.5, y_tolerance=3, use_text_flow=True, extra_attrs=["size"]
                )
                words = []
                for r in raw:
                    words.append(
                        Word(r["text"], r["x0"], r["x1"], r["top"], r["bottom"], round(r["size"], 1), pno, order)
                    )
                    order += 1
                lines = build_lines(words, pno, index) if words else []
                index += len(lines)
                pages.append(Page(pno, float(pg.width), float(pg.height), lines))
                texts.append(pg.extract_text() or "")
    except Exception as exc:  # pdfminer sokféle kivételt dob sérült fájlra
        raise PdfReadError(f"A fájl nem olvasható PDF-ként: {exc}") from exc

    if not any(p.lines for p in pages):
        raise PdfReadError("A PDF nem tartalmaz kinyerhető szöveget (lehet, hogy szkennelt kép).")
    return PdfDocument(pages=pages, full_text="\n".join(texts))
