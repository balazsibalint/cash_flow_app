import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.schemas import ExtractedInvoice, Party
from app.services.extraction import labels
from app.services.extraction.doctype import detect_doc_type
from app.services.extraction.layout import LabelHit, find_labels, value_candidates
from app.services.extraction.normalize import (
    find_currency,
    find_tax_ids,
    fold,
    normalize_company_name,
    normalize_currency,
    normalize_tax_id,
    parse_amount,
    parse_date,
)
from app.services.pdf_text import Line, PdfDocument

BUYER_BLOCK_MAX_GAP = 22.0  # pt – ennél nagyobb függőleges rés lezárja a vevő blokkját
BUYER_BLOCK_MAX_LINES = 10

# --------------------------------------------------------------------------- értelmezők


_INVOICE_NO_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/\-._]*[A-Za-z0-9]|[0-9]")


def parse_invoice_number(text: str) -> str | None:
    if ":" in text:
        text = text.rsplit(":", 1)[1]
    for tok in text.split():
        tok = tok.strip(".,;()")
        if _INVOICE_NO_TOKEN.fullmatch(tok) and any(c.isdigit() for c in tok) and len(tok) >= 2:
            return tok
    return None


_PERCENT = re.compile(r"\(?\s*\d+(?:[.,]\d+)?\s?%\s*\)?")


def parse_money(text: str) -> Decimal | None:
    """Összeg egy értékmezőből; az ÁFA-kulcsot (`(27%)`) előtte eltávolítjuk."""
    return parse_amount(_PERCENT.sub(" ", text))


def parse_currency(text: str) -> str | None:
    for tok in re.split(r"[\s/:]+", text):
        if code := normalize_currency(tok.strip(".,()")):
            return code
    return None


_TERMS = [
    re.compile(r"(\d{1,3})\s*(?:nap|napon|days?|tage?n?|jours?|dias|giorni|dni)(?![a-z])"),
    re.compile(r"(?:net|netto|netto)\s*(\d{1,3})(?!\d)"),
]


def parse_payment_terms(text: str) -> int | None:
    t = fold(text)
    for rx in _TERMS:
        if m := rx.search(t):
            days = int(m[1])
            return days if 0 <= days <= 365 else None
    return None


# --------------------------------------------------------------------------- segédek


def _first(values: list):
    return values[0] if values else None


def _most_common(values: list):
    if not values:
        return None
    counts = Counter(values)
    best = max(counts.values())
    # holtversenynél a később előforduló (a többoldalas számla összesítője a végén van)
    return next(v for v in reversed(values) if counts[v] == best)


def _excluded_line(line: Line) -> bool:
    t = fold(line.text)
    return any(k in t for k in labels.EXCLUDE_AMOUNT_LINE)


def _values(doc: PdfDocument, field: str, parser, *, skip_excluded: bool = False) -> list:
    out = []
    for hit in find_labels(doc, labels.RX[field]):
        if skip_excluded and _excluded_line(hit.line):
            continue
        out.extend(value_candidates(doc, hit, parser))
    return out


# --------------------------------------------------------------------------- felek


@dataclass
class _Block:
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _buyer_hit(doc: PdfDocument) -> LabelHit | None:
    first_page = doc.pages[0]
    for key in ("buyer", "buyer_weak"):
        hits = [
            h for h in find_labels(doc, labels.RX[key], pages={1})
            if h.line.top < first_page.height * 0.6
            and not re.match(r"^\W*(no|nr|id|number|#|nummer|n°)\b", fold(h.rest_text))
        ]
        if hits:
            return min(hits, key=lambda h: (h.line.index, h.x0))
    return None


def _buyer_block(doc: PdfDocument, hit: LabelHit) -> _Block:
    page = doc.pages[hit.line.page - 1]
    segs = hit.line.segments
    i = segs.index(hit.segment)
    right = segs[i + 1].x0 if i + 1 < len(segs) else page.width * 0.55
    left = hit.x0 - 10

    lines: list[str] = []
    rest = re.sub(r"^[\s:/-]+", "", hit.rest_text)
    if rest:
        lines.append(rest)
    prev_top = hit.line.top
    for ln in page.lines:
        if ln.index <= hit.line.index:
            continue
        words = [w for w in ln.words if w.x0 >= left and w.x0 < right - 2]
        if not words:
            continue
        if ln.top - prev_top > BUYER_BLOCK_MAX_GAP or len(lines) >= BUYER_BLOCK_MAX_LINES:
            break
        lines.append(" ".join(w.text for w in words))
        prev_top = ln.top
    return _Block(lines)


def _is_title_or_label(text: str) -> bool:
    t = fold(text).strip(" :")
    if not t or t in labels.DOCUMENT_TITLES:
        return True
    return any(rx.search(t) for rx in labels.RX.values())


def _seller_name(doc: PdfDocument, before_line_index: int | None) -> str | None:
    for ln in doc.pages[0].lines:
        if before_line_index is not None and ln.index >= before_line_index:
            break
        for seg in ln.segments:
            text = seg.text.strip()
            if len(text) < 3 or _is_title_or_label(text) or find_tax_ids(text):
                continue
            if sum(c.isalpha() for c in text) < 3:
                continue
            return text
    return None


_KIND_PRIORITY = {"hu_domestic": 0, "eu_vat": 1, "ein": 2}


def _party(name: str | None, text: str) -> Party:
    found = find_tax_ids(text)
    keys = list(dict.fromkeys(t.key for t in found))
    display = min(found, key=lambda t: _KIND_PRIORITY.get(t.kind, 9)).raw if found else None
    return Party(name=name, tax_id=display, tax_keys=keys)


def _parties(doc: PdfDocument) -> tuple[Party, Party]:
    hit = _buyer_hit(doc)
    if hit is None:
        # Nincs vevő-címke: a felek szétválasztását a validáció / LLM-tartalék végzi.
        return Party(name=_seller_name(doc, None)), Party()

    block = _buyer_block(doc, hit)
    buyer_name = next((l for l in block.lines if not _is_title_or_label(l) and not find_tax_ids(l)), None)
    buyer = _party(buyer_name, block.text)

    page1 = doc.pages[0]
    header = "\n".join(ln.text for ln in page1.lines if ln.index < hit.line.index)
    seller = _party(_seller_name(doc, hit.line.index), header)
    if not seller.tax_keys:
        # Tartalék: a lábléc adószámai, a vevőé kivételével.
        last = doc.pages[-1]
        footer = "\n".join(ln.text for ln in last.lines if ln.top > last.height * 0.8)
        cand = _party(None, footer)
        keys = [k for k in cand.tax_keys if k not in buyer.tax_keys]
        if keys:
            seller = Party(name=seller.name, tax_id=cand.tax_id, tax_keys=keys)
    # A vevő blokkjába esett eladói adószámot ne tulajdonítsuk a vevőnek.
    buyer.tax_keys = [k for k in buyer.tax_keys if k not in seller.tax_keys] or buyer.tax_keys
    return seller, buyer


# --------------------------------------------------------------------------- fő függvény


def _us_context(doc: PdfDocument) -> bool:
    head = fold("\n".join(ln.text for ln in doc.pages[0].lines[:12]))
    return bool(re.search(r"united states|\busa\b|\bein\b", head))


def extract(doc: PdfDocument) -> ExtractedInvoice:
    dayfirst = not _us_context(doc)

    def date_parser(s: str):
        return parse_date(s, dayfirst=dayfirst)

    seller, buyer = _parties(doc)

    gross_c = _values(doc, "gross", parse_money, skip_excluded=True)
    net_c = _values(doc, "net", parse_money, skip_excluded=True)
    vat_c = _values(doc, "vat", parse_money, skip_excluded=True)
    net = _most_common(net_c)
    vat = _most_common(vat_c)
    gross = None
    if net is not None and vat is not None:
        gross = next((g for g in reversed(gross_c) if g == net + vat), None)
    if gross is None:
        gross = _most_common(gross_c)

    currency = _first(_values(doc, "currency", parse_currency))
    if currency is None:
        gross_lines = [h.line.text for h in find_labels(doc, labels.RX["gross"])]
        currency = find_currency("\n".join(gross_lines)) or find_currency(doc.full_text)

    return ExtractedInvoice(
        doc_type=detect_doc_type(doc),
        invoice_number=_first(_values(doc, "invoice_number", parse_invoice_number)),
        seller=seller,
        buyer=buyer,
        issue_date=_first(_values(doc, "issue_date", date_parser)),
        supply_date=_first(_values(doc, "supply_date", date_parser)),
        due_date=_first(_values(doc, "due_date", date_parser)),
        payment_terms_days=_first(_values(doc, "payment_terms", parse_payment_terms)),
        currency=currency,
        net_amount=net,
        vat_amount=vat,
        gross_amount=gross,
    )


# --------------------------------------------------------------------------- irány


def determine_direction(inv: ExtractedInvoice, own_keys: set[str], own_name: str) -> str | None:
    """`outgoing`, ha a mi cégünk a kiállító; `incoming`, ha a vevő; különben None."""
    seller_own = bool(own_keys & set(inv.seller.tax_keys))
    buyer_own = bool(own_keys & set(inv.buyer.tax_keys))
    if seller_own != buyer_own:
        return "outgoing" if seller_own else "incoming"
    if not seller_own and not buyer_own:
        own = normalize_company_name(own_name)
        s = normalize_company_name(inv.seller.name) == own
        b = normalize_company_name(inv.buyer.name) == own
        if s != b:
            return "outgoing" if s else "incoming"
    return None


def own_tax_keys(own_tax_number: str, own_eu_vat: str) -> set[str]:
    return {k for k in (normalize_tax_id(own_tax_number), normalize_tax_id(own_eu_vat)) if k}
