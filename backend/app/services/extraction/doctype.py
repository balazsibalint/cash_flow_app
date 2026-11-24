import re

from app.services.extraction.normalize import fold, strip_accents
from app.services.pdf_text import PdfDocument

HEADER_FRACTION = 0.35

INVOICE = "invoice"
CREDIT_NOTE = "credit_note"
PROFORMA = "proforma"
ADVANCE = "advance_invoice"

_KEYWORDS: dict[str, list[str]] = {
    CREDIT_NOTE: [
        "jovairo szamla", "jovairo", "sztorno szamla", "sztorno", "storno", "helyesbito szamla", "helyesbito",
        "credit note", "credit memo", "creditnote",
        "gutschrift", "stornorechnung", "rechnungskorrektur", "korrekturrechnung",
        "facture d'avoir", "avoir",
        "nota de credito", "factura rectificativa", "factura de abono", "abono",
        "nota di credito", "nota credito",
        "faktura korygujaca", "korekta",
    ],
    PROFORMA: [
        "dijbekero", "proforma", "pro forma", "pro-forma", "vorkasse", "facture proforma", "factura proforma",
    ],
    ADVANCE: [
        "elolegszamla", "eloleg szamla", "elolegbekero", "advance invoice", "advance payment invoice",
        "prepayment invoice", "deposit invoice",
        "anzahlungsrechnung", "vorauszahlungsrechnung", "abschlagsrechnung",
        "facture d'acompte", "factura de anticipo", "fattura d'acconto", "fattura di acconto",
        "faktura zaliczkowa",
    ],
}
_RX = {
    kind: re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(k) for k in sorted(kws, key=len, reverse=True)) + r")(?![a-z0-9])")
    for kind, kws in _KEYWORDS.items()
}


_SPACED_RUN = re.compile(r"(?<![^\W\d_])(?:[^\W\d_] ){2,}[^\W\d_](?![^\W\d_])")


def _header_raw(doc: PdfDocument) -> str:
    if not doc.pages:
        return ""
    page = doc.pages[0]
    limit = page.height * HEADER_FRACTION
    return "\n".join(ln.text for ln in page.lines if ln.top <= limit)


def header_text(doc: PdfDocument) -> str:
    return fold(_header_raw(doc))


def detect_doc_type(doc: PdfDocument) -> str:
    raw = _header_raw(doc)
    text = fold(raw)
    # Ritkított címeknél (`J Ó V Á Í R Ó  S Z Á M L A`) a szóhatár elveszik: ezeket szóköz nélkül vizsgáljuk.
    runs = [m.group(0).replace(" ", "") for m in _SPACED_RUN.finditer(strip_accents(raw).lower())]
    for kind in (CREDIT_NOTE, PROFORMA, ADVANCE):
        if _RX[kind].search(text):
            return kind
        compact = [re.sub(r"[\s'-]", "", k) for k in _KEYWORDS[kind]]
        if any(k in run for run in runs for k in compact):
            return kind
    return INVOICE


DOC_TYPE_LABELS_HU = {
    CREDIT_NOTE: "jóváíró / sztornó / helyesbítő számla",
    PROFORMA: "díjbekérő / proforma számla",
    ADVANCE: "előlegszámla",
}
