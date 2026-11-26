"""Kinyerési tesztek.

1. Szerkezeti tesztek a minta-PDF-eken (tests/pdfs): minden kötelező mező megvan, nettó + ÁFA = bruttó,
   a mi cégünk pontosan az egyik oldalon áll. Konkrét értékeket NEM rögzítenek.
2. Referencia-tesztek: a felhasználó által kézzel készített tests/expected.json (ha még nincs, kimarad).
3. Szintetikus PDF-ek: ismeretlen elrendezés, hibás fájl, szöveg nélküli PDF.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.services.extraction.doctype import CREDIT_NOTE
from app.services.extraction.normalize import (
    normalize_company_name,
    normalize_invoice_number,
    normalize_tax_id,
)
from app.services.extraction.rules import determine_direction, extract, own_tax_keys
from app.services.pdf_text import PdfReadError, load_pdf

from tests.helpers import make_pdf

TESTS = Path(__file__).parent
PDFS = sorted((TESTS / "pdfs").glob("*.pdf"))
EXPECTED_FILE = TESTS / "expected.json"
EXPECTED = json.loads(EXPECTED_FILE.read_text(encoding="utf-8")) if EXPECTED_FILE.exists() else {}

S = get_settings()
OWN = own_tax_keys(S.own_tax_number, S.own_eu_vat)


def _extract(path: Path):
    inv = extract(load_pdf(path))
    return inv, determine_direction(inv, OWN, S.own_company_name)


# ----------------------------------------------------------------------------- 1. szerkezeti


@pytest.mark.parametrize("pdf", PDFS, ids=[p.name for p in PDFS])
def test_sample_invoice_is_complete_and_consistent(pdf):
    inv, direction = _extract(pdf)
    assert inv.doc_type == "invoice"
    for field in ("invoice_number", "issue_date", "supply_date", "due_date", "currency", "gross_amount",
                  "net_amount", "vat_amount"):
        assert getattr(inv, field) is not None, field
    assert inv.seller.name and inv.buyer.name
    assert inv.seller.tax_keys and inv.buyer.tax_keys
    assert inv.net_amount + inv.vat_amount == inv.gross_amount
    assert inv.issue_date <= inv.due_date
    assert direction in ("incoming", "outgoing")
    partner = inv.buyer if direction == "outgoing" else inv.seller
    assert not set(partner.tax_keys) & OWN


def test_sample_set_covers_both_directions_and_multi_page():
    results = [_extract(p) for p in PDFS]
    assert {d for _, d in results} == {"incoming", "outgoing"}
    assert any(len(load_pdf(p).pages) > 1 for p in PDFS)


def test_printed_huf_vat_and_rate_are_not_used_as_total():
    # A kétnyelvű kimenő sablon forintos ÁFA-t és saját árfolyamot is feltüntet – ez nem végösszeg.
    for pdf in PDFS:
        text = load_pdf(pdf).full_text.lower()
        if "forintban" in text:
            inv, _ = _extract(pdf)
            assert inv.currency != "HUF"
            assert inv.gross_amount == inv.net_amount + inv.vat_amount
            break
    else:
        pytest.skip("nincs ilyen minta a tests/pdfs alatt")


# ----------------------------------------------------------------------------- 2. referencia (expected.json)


def _norm(field: str, value):
    if value is None:
        return None
    if field in ("seller_tax", "buyer_tax"):
        return normalize_tax_id(str(value))
    if field == "invoice_number":
        return normalize_invoice_number(str(value))
    if field in ("seller_name", "buyer_name"):
        return normalize_company_name(str(value))
    if field.endswith("_date"):
        return date.fromisoformat(str(value))
    if field == "gross_amount":
        return Decimal(str(value))
    return value


@pytest.mark.skipif(not EXPECTED, reason="tests/expected.json még nincs elkészítve")
@pytest.mark.parametrize("filename", sorted(EXPECTED), ids=sorted(EXPECTED))
def test_matches_expected(filename):
    inv, direction = _extract(TESTS / "pdfs" / filename)
    actual = {
        "invoice_number": inv.invoice_number,
        "seller_name": inv.seller.name,
        "seller_tax": inv.seller.tax_id,
        "buyer_name": inv.buyer.name,
        "buyer_tax": inv.buyer.tax_id,
        "issue_date": inv.issue_date,
        "supply_date": inv.supply_date,
        "due_date": inv.due_date,
        "currency": inv.currency,
        "gross_amount": inv.gross_amount,
        "direction": direction,
    }
    for field, expected in EXPECTED[filename].items():
        assert _norm(field, actual.get(field)) == _norm(field, expected), field


# ----------------------------------------------------------------------------- 3. szintetikus


def test_unknown_layout_with_weak_buyer_label_and_chf():
    pdf = make_pdf([
        (40, 40, "ACME Widgets GmbH"),
        (40, 54, "VAT ID: DE123456789"),
        (380, 40, "TAX INVOICE"),
        (380, 90, "Invoice number: AW-77/2026"),
        (380, 104, "Invoice date: 03.02.2026"),
        (380, 118, "Delivery date: 01.02.2026"),
        (380, 132, "Payment due: 17.02.2026"),
        (380, 146, "Currency: CHF"),
        (40, 90, "Customer:"),
        (40, 104, "Nordwind Solutions Kft."),
        (40, 118, "Infopark setany 7., Budapest"),
        (40, 132, "VAT: HU26481937"),
        (300, 300, "Total net"), (480, 300, "1'000.00"),
        (300, 314, "Total VAT"), (480, 314, "81.00"),
        (300, 328, "Amount due"), (480, 328, "1'081.00"),
    ])
    inv = extract(load_pdf(pdf))
    assert inv.invoice_number == "AW-77/2026"
    assert inv.seller.name == "ACME Widgets GmbH"
    assert inv.seller.tax_keys == ["DE123456789"]
    assert inv.buyer.name == "Nordwind Solutions Kft."
    assert inv.issue_date == date(2026, 2, 3)
    assert inv.supply_date == date(2026, 2, 1)
    assert inv.due_date == date(2026, 2, 17)
    assert inv.currency == "CHF"
    assert (inv.net_amount, inv.vat_amount, inv.gross_amount) == (Decimal("1000.00"), Decimal("81.00"), Decimal("1081.00"))
    assert determine_direction(inv, OWN, S.own_company_name) == "incoming"


def test_payment_terms_without_due_date():
    pdf = make_pdf([
        (40, 40, "Valami Kft."), (40, 54, "Adószám: 12345678-2-42"),
        (40, 90, "Bill to"), (40, 104, "Nordwind Solutions Kft."), (40, 118, "Adószám: 26481937-2-43"),
        (300, 90, "Számlaszám: V-1"), (300, 104, "Kiállítás dátuma: 2026.05.04."),
        (40, 400, "Fizetési feltétel: 15 nap"),
    ])
    inv = extract(load_pdf(pdf))
    assert inv.due_date is None
    assert inv.payment_terms_days == 15


def test_credit_note_is_recognised():
    pdf = make_pdf([(40, 40, "Valami Kft."), (250, 80, "CREDIT NOTE"), (40, 120, "Bill to"),
                    (40, 134, "Nordwind Solutions Kft.")])
    assert extract(load_pdf(pdf)).doc_type == CREDIT_NOTE


def test_corrupt_pdf_raises_read_error():
    with pytest.raises(PdfReadError):
        load_pdf(b"%PDF-1.4\nthis is not really a pdf")


def test_pdf_without_text_raises_read_error():
    with pytest.raises(PdfReadError):
        load_pdf(make_pdf(None, draw_only=True))


def test_password_protected_pdf_has_specific_message():
    with pytest.raises(PdfReadError, match="jelszóval védett"):
        load_pdf(make_pdf([(40, 40, "Szamlaszam: X-1")], user_password="titok"))


def test_owner_password_only_pdf_is_readable():
    # Csak jogosultság-korlátozás (üres megnyitási jelszó): a szöveg kiolvasható.
    doc = load_pdf(make_pdf([(40, 40, "Szamlaszam: X-1")], user_password=""))
    assert "Szamlaszam" in doc.full_text
