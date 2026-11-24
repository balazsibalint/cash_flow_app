import pytest

from app.services.extraction.doctype import ADVANCE, CREDIT_NOTE, INVOICE, PROFORMA, detect_doc_type

from tests.helpers import make_doc


def _doc_with_title(title: str, body_line: str = "Szolgáltatás 1 db 1 000 Ft"):
    return make_doc([
        (40, [(40, "Valami Kft.")]),
        (80, [(250, title)]),
        (600, [(40, body_line)]),
    ])


@pytest.mark.parametrize(
    "title, kind",
    [
        ("SZÁMLA", INVOICE),
        ("INVOICE", INVOICE),
        ("J Ó V Á Í R Ó  S Z Á M L A", CREDIT_NOTE),
        ("Sztornó számla", CREDIT_NOTE),
        ("Helyesbítő számla", CREDIT_NOTE),
        ("CREDIT NOTE", CREDIT_NOTE),
        ("Gutschrift", CREDIT_NOTE),
        ("Facture d'avoir", CREDIT_NOTE),
        ("Factura rectificativa", CREDIT_NOTE),
        ("Nota di credito", CREDIT_NOTE),
        ("Faktura korygująca", CREDIT_NOTE),
        ("DÍJBEKÉRŐ", PROFORMA),
        ("Proforma Invoice", PROFORMA),
        ("Pro-forma Rechnung", PROFORMA),
        ("Előlegszámla", ADVANCE),
        ("Anzahlungsrechnung", ADVANCE),
        ("Faktura zaliczkowa", ADVANCE),
    ],
)
def test_detects_document_type_from_title(title, kind):
    assert detect_doc_type(_doc_with_title(title)) == kind


def test_keyword_in_line_items_does_not_reject():
    doc = _doc_with_title("SZÁMLA", "Előleg beszámítása – sztornó díj nélkül 1 db 1 000 Ft")
    assert detect_doc_type(doc) == INVOICE
