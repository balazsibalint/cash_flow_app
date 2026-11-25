"""A teljes kinyerési folyamat (szabály → validáció → LLM-tartalék) tesztjei, hamis LLM-mel."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import get_settings
from app.schemas import ExtractedInvoice, Party
from app.services.extraction import pipeline as p
from app.services.extraction.llm import LlmError, LlmResult
from app.services.pdf_text import load_pdf

from tests.helpers import make_pdf

OWN = p.own_company(get_settings())
PDFS = sorted((Path(__file__).parent / "pdfs").glob("*.pdf"))


class FakeLlm:
    def __init__(self, result: ExtractedInvoice | Exception | None = None):
        self.result = result
        self.calls = []

    def extract(self, text, own, *, file_sha256, partial=None, issues=None):
        self.calls.append({"text": text, "issues": issues, "partial": partial})
        if isinstance(self.result, Exception):
            raise self.result
        return LlmResult(invoice=self.result, model="fake")


def codes(res):
    return [m.code for m in res.messages]


# Szintetikus számla, amelyről a szabályalapú kinyerő nem talál határidőt (nincs címke és fizetési feltétel sem).
NO_DUE_PDF = make_pdf([
    (40, 40, "Valami Kft."), (40, 54, "Adószám: 12345678-2-42"),
    (40, 90, "Bill to"), (40, 104, "Nordwind Solutions Kft."), (40, 118, "Adószám: 26481937-2-43"),
    (300, 90, "Számlaszám: V-2026/7"), (300, 104, "Kiállítás dátuma: 2026.05.04."),
    (300, 118, "Teljesítés dátuma: 2026.05.02."), (300, 132, "Pénznem: HUF"),
    (300, 146, "Utalandó eddig a napig: 2026.06.03."),
    (300, 300, "Total due"), (480, 300, "127 000 Ft"),
])

LLM_OK = ExtractedInvoice(
    doc_type="invoice", invoice_number="V-2026/7",
    seller=Party(name="Valami Kft.", tax_id="12345678-2-42", tax_keys=["HU12345678"]),
    buyer=Party(name="Nordwind Solutions Kft.", tax_id="26481937-2-43", tax_keys=["HU26481937"]),
    issue_date=date(2026, 5, 4), supply_date=date(2026, 5, 2), due_date=date(2026, 6, 3),
    currency="HUF", gross_amount=Decimal("127000"),
)


@pytest.mark.parametrize("pdf", PDFS, ids=[x.name for x in PDFS])
def test_sample_invoices_pass_without_llm(pdf):
    llm = FakeLlm(LLM_OK)
    res = p.process(load_pdf(pdf), OWN, llm=llm, file_sha256="x")
    assert res.status == "ok", res.messages
    assert res.method == "rule"
    assert res.direction in ("incoming", "outgoing")
    assert llm.calls == []  # takarékosság: jó szabályalapú eredménynél nincs LLM-hívás


def test_llm_fallback_fills_missing_due_date():
    llm = FakeLlm(LLM_OK)
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=llm, file_sha256="x")
    assert len(llm.calls) == 1
    assert [m.code for m in llm.calls[0]["issues"]] == ["MISSING_DUE"]
    assert "Valami Kft." in llm.calls[0]["text"]  # a szöveget küldjük, nem a PDF-et
    assert res.status == "ok" and res.method == "llm"
    assert res.invoice.due_date == date(2026, 6, 3)
    assert res.direction == "incoming"
    assert p.LLM_USED in codes(res)


def test_without_llm_the_invoice_goes_to_review():
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=None, file_sha256="x")
    assert res.status == "review"
    assert "MISSING_DUE" in codes(res) and p.LLM_DISABLED in codes(res)
    assert res.status_reason


def test_llm_failure_goes_to_review():
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=FakeLlm(LlmError("időtúllépés")), file_sha256="x")
    assert res.status == "review" and res.llm_called
    assert p.LLM_FAILED in codes(res)


def test_hallucinated_llm_answer_is_not_accepted():
    fake = LLM_OK.model_copy(update={"gross_amount": Decimal("999999")})
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=FakeLlm(fake), file_sha256="x")
    assert res.status == "review"
    assert p.LLM_UNGROUNDED in codes(res)


def test_llm_answer_failing_validation_goes_to_review():
    bad = LLM_OK.model_copy(update={"due_date": date(2026, 1, 1)})  # határidő a kiállítás előtt
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=FakeLlm(bad), file_sha256="x")
    assert res.status == "review"
    # Döntetlen hibaszámnál a szabályalapú eredmény marad, de az LLM hibája is látszik.
    llm_msg = next(m for m in res.messages if m.code == p.LLM_FAILED)
    assert "korábbi, mint a kiállítás" in llm_msg.text


def test_llm_detected_credit_note_is_rejected():
    res = p.process(load_pdf(NO_DUE_PDF), OWN, llm=FakeLlm(LLM_OK.model_copy(update={"doc_type": "credit_note"})),
                    file_sha256="x")
    assert res.status == "rejected"


def test_credit_note_rejected_without_llm_call():
    pdf = make_pdf([(40, 40, "Valami Kft."), (250, 80, "JÓVÁÍRÓ SZÁMLA"), (40, 120, "Bill to"),
                    (40, 134, "Nordwind Solutions Kft."), (40, 148, "Adószám: 26481937-2-43")])
    llm = FakeLlm(LLM_OK)
    res = p.process(load_pdf(pdf), OWN, llm=llm, file_sha256="x")
    assert res.status == "rejected" and "jóváíró" in res.status_reason
    assert llm.calls == []


def test_foreign_invoice_rejected_without_llm_call():
    pdf = make_pdf([(40, 40, "Valami Kft."), (250, 80, "SZÁMLA"), (40, 120, "Bill to"),
                    (40, 134, "Másik Zrt."), (40, 148, "Adószám: 11111111-2-41"),
                    (300, 120, "Számlaszám: X-1"), (300, 300, "Total due"), (480, 300, "1 000 Ft")])
    llm = FakeLlm(LLM_OK)
    res = p.process(load_pdf(pdf), OWN, llm=llm, file_sha256="x")
    assert res.status == "rejected" and "nem szerepel" in res.status_reason
    assert llm.calls == []


def test_negative_total_rejected():
    pdf = make_pdf([
        (40, 40, "Valami Kft."), (40, 54, "Adószám: 12345678-2-42"),
        (40, 90, "Bill to"), (40, 104, "Nordwind Solutions Kft."), (40, 118, "Adószám: 26481937-2-43"),
        (300, 90, "Számlaszám: V-9"), (300, 104, "Kiállítás dátuma: 2026.05.04."),
        (300, 118, "Due date: 2026.05.12."), (300, 132, "Pénznem: HUF"),
        (300, 300, "Total due"), (480, 300, "-5 000 Ft"),
    ])
    res = p.process(load_pdf(pdf), OWN, llm=FakeLlm(LLM_OK), file_sha256="x")
    assert res.status == "rejected"


def test_missing_supply_date_inferred_without_llm():
    pdf = make_pdf([
        (40, 40, "Valami Kft."), (40, 54, "Adószám: 12345678-2-42"),
        (40, 90, "Bill to"), (40, 104, "Nordwind Solutions Kft."), (40, 118, "Adószám: 26481937-2-43"),
        (300, 90, "Számlaszám: V-10"), (300, 104, "Kiállítás dátuma: 2026.05.04."),
        (300, 132, "Pénznem: HUF"), (40, 400, "Fizetési feltétel: 8 nap"),
        (300, 300, "Total due"), (480, 300, "5 000 Ft"),
    ])
    llm = FakeLlm(LLM_OK)
    res = p.process(load_pdf(pdf), OWN, llm=llm, file_sha256="x")
    assert res.status == "ok" and llm.calls == []
    assert res.invoice.supply_date == date(2026, 5, 4) and res.supply_inferred
    assert res.invoice.due_date == date(2026, 5, 12) and res.due_inferred
