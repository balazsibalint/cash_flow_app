import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from app.services.pdf_text import Line, PdfDocument, Segment, Word

T = TypeVar("T")

BELOW_MAX_DISTANCE = 30.0  # pt – ennél távolabbi sor már nem a címke értéke
# Csak a legközelebbi, a címke oszlopába eső sor számít: a távolabbiak már más mezőhöz tartoznak
# (pl. egy táblázatfejléc alatti tételsor).
BELOW_MAX_LINES = 1
COLUMN_TOLERANCE = 4.0


@dataclass
class LabelHit:
    line: Line
    segment: Segment
    label_words: list[Word]
    rest_words: list[Word]  # a címke után, ugyanabban a szegmensben

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.label_words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.label_words)

    @property
    def rest_text(self) -> str:
        return " ".join(w.text for w in self.rest_words)


def compile_labels(phrases: list[str]) -> re.Pattern:
    """Fold-olt címkék → regex. A címke a szegmens elején vagy `/` után állhat (kétnyelvű címkék)."""
    alts = sorted({p.strip() for p in phrases}, key=len, reverse=True)
    body = "|".join(r"\s+".join(re.escape(tok) for tok in alt.split()) for alt in alts)
    return re.compile(rf"(?:^|/\s*|\|\s*)(?P<label>{body})(?![a-z0-9])")


def _folded_with_offsets(words: list[Word]) -> tuple[str, list[tuple[int, int]]]:
    parts, spans, pos = [], [], 0
    for w in words:
        f = w.folded
        parts.append(f)
        spans.append((pos, pos + len(f)))
        pos += len(f) + 1
    return " ".join(parts), spans


def find_labels(doc: PdfDocument, pattern: re.Pattern, *, pages: set[int] | None = None) -> list[LabelHit]:
    hits: list[LabelHit] = []
    for line in doc.lines:
        if pages and line.page not in pages:
            continue
        for seg in line.segments:
            text, spans = _folded_with_offsets(seg.words)
            for m in pattern.finditer(text):
                start, end = m.start("label"), m.end("label")
                idx = [i for i, (a, b) in enumerate(spans) if a < end and b > start]
                if not idx:
                    continue
                last = idx[-1]
                hits.append(LabelHit(line, seg, seg.words[idx[0]: last + 1], seg.words[last + 1:]))
    return hits


def _clean_rest(text: str) -> str:
    return re.sub(r"^[\s:./|#-]+", "", text)


def _next_segment(hit: LabelHit) -> Segment | None:
    segs = hit.line.segments
    i = segs.index(hit.segment)
    return segs[i + 1] if i + 1 < len(segs) else None


def words_below(doc: PdfDocument, hit: LabelHit) -> list[list[Word]]:
    """A címke alatti sorokból a címke oszlopába eső szavak, soronként (a legközelebbi elöl)."""
    lines = [ln for ln in doc.lines if ln.page == hit.line.page and ln.index > hit.line.index]
    left = hit.x0 - COLUMN_TOLERANCE * 3
    out: list[list[Word]] = []
    for ln in lines:
        if ln.top - hit.line.bottom > BELOW_MAX_DISTANCE:
            break
        col = [w for w in ln.words if w.x1 > hit.x0 - COLUMN_TOLERANCE and w.x0 < hit.x1 + COLUMN_TOLERANCE]
        if not col:
            continue
        # Az érték a címke oszlopában kezdődő szegmens (ne nyúljon át a bal oldali oszlopba).
        seg = next(s for s in ln.segments if col[0] in s.words)
        words = [w for w in seg.words if w.x0 >= left]
        if words:
            out.append(words)
        if len(out) >= BELOW_MAX_LINES:
            break
    return out


def value_candidates(doc: PdfDocument, hit: LabelHit, parser: Callable[[str], T | None]) -> list[T]:
    """Az első értelmezhető érték: címke utáni szöveg → következő szegmens → alatta lévő sorok."""
    rest = _clean_rest(hit.rest_text)
    if rest and (v := parser(rest)) is not None:
        return [v]
    nxt = _next_segment(hit)
    if nxt is not None and (v := parser(nxt.text)) is not None:
        return [v]
    # Ha a címke után csak szöveg áll (pl. a címke angol fordítása: „/ Invoice date”), az érték alatta lehet.
    if not any(c.isdigit() for c in rest):
        for words in words_below(doc, hit):
            if (v := parser(" ".join(w.text for w in words))) is not None:
                return [v]
    return []


def find_values(doc: PdfDocument, pattern: re.Pattern, parser: Callable[[str], T | None]) -> list[T]:
    """Az összes címke-előfordulás értéke, dokumentumsorrendben."""
    values: list[T] = []
    for hit in find_labels(doc, pattern):
        values.extend(value_candidates(doc, hit, parser))
    return values
