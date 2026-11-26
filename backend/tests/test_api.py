"""Feltöltés, dedup, státuszok, törlés, PDF-kiszolgálás és riport – HTTP-n át, mockolt MNB-vel, LLM nélkül."""

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db, get_ingest, get_pdf_dir
from app.config import get_settings
from app.db import Base, make_engine
from app.main import app
from app.models import ExchangeRate, Invoice, Partner
from app.services.extraction.pipeline import own_company
from app.services.ingest import IngestService

from tests.helpers import make_pdf
from tests.test_mnb import FakeMnb, service, weekday_quotes

PDFS = sorted((Path(__file__).parent / "pdfs").glob("*.pdf"))
TODAY = date(2026, 11, 25)
CURRENCIES = ("EUR", "USD", "GBP", "PLN")


def invoice_pdf(number="V-2026/7", *, seller="Valami Kft.", seller_tax="12345678-2-42", buyer="Nordwind Solutions Kft.",
                buyer_tax="26481937-2-43", issue="2026.05.04.", supply="2026.05.02.", due="2026.06.03.",
                currency="EUR", total="1 000,00 EUR", extra: str | None = None) -> bytes:
    items = [
        (40, 40, seller), (40, 54, f"Adószám: {seller_tax}"),
        (40, 90, "Bill to"), (40, 104, buyer), (40, 118, f"Adószám: {buyer_tax}"),
        (300, 90, f"Számlaszám: {number}"), (300, 104, f"Kiállítás dátuma: {issue}"),
        (300, 118, f"Teljesítés dátuma: {supply}"), (300, 132, f"Due date: {due}"),
        (300, 146, f"Pénznem: {currency}"), (300, 300, "Total due"), (480, 300, total),
    ]
    if extra:
        items.append((40, 500, extra))
    return make_pdf(items)


@pytest.fixture
def env(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    quotes = [q for c in CURRENCIES for q in weekday_quotes(c, date(2025, 11, 1), TODAY - timedelta(days=1))]
    fake = FakeMnb(quotes)
    rates = service(fake, TODAY)
    pdf_dir = tmp_path / "pdfs"
    ingest = IngestService(session_factory, pdf_dir, own_company(get_settings()), llm=None, rates=rates,
                           retry_interval_seconds=0)

    def _db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_ingest] = lambda: ingest
    app.dependency_overrides[get_pdf_dir] = lambda: pdf_dir
    try:
        with TestClient(app) as client:
            yield SimpleNamespace(client=client, ingest=ingest, fake=fake, rates=rates, sf=session_factory, pdf_dir=pdf_dir)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def upload(env, data: bytes, name: str = "szamla.pdf") -> httpx.Response:
    return env.client.post("/api/invoices", files={"file": (name, data, "application/pdf")})


def count(env, model) -> int:
    with env.sf() as s:
        return s.scalar(select(func.count()).select_from(model))


# ----------------------------------------------------------------------------- feltöltés és státuszok


def test_upload_creates_invoice_with_huf_amount(env):
    r = upload(env, invoice_pdf(), "v7.pdf")
    assert r.status_code == 200
    body = r.json()
    assert body["result"] == "created", body
    inv = body["invoice"]
    assert inv["status"] == "ok" and inv["direction"] == "incoming"
    assert inv["gross_amount"] == "1000.00" and inv["currency"] == "EUR"
    # A teljesítés (2026-05-02) szombat → a pénteki (05-01) jegyzés: 390 + 1/100
    assert inv["fx_rate_date"] == "2026-05-01" and inv["fx_rate"] == "390.01" and inv["fx_unit"] == 1
    assert inv["gross_huf"] == 390010 and isinstance(inv["gross_huf"], int)
    assert inv["partner"]["display_name"] == "Valami Kft." and inv["partner"]["tax_key"] == "HU12345678"
    assert (env.pdf_dir / f"{_sha(env, inv['id'])}.pdf").is_file()


def _sha(env, invoice_id: int) -> str:
    with env.sf() as s:
        return s.get(Invoice, invoice_id).file_sha256


def test_same_file_again_is_duplicate_without_processing(env):
    data = invoice_pdf()
    first = upload(env, data).json()
    n_requests = len(env.fake.requests)
    second = upload(env, data, "masik_nev.pdf").json()
    assert second["result"] == "duplicate"
    assert second["invoice"]["id"] == first["invoice"]["id"]
    assert len(env.fake.requests) == n_requests
    assert count(env, Invoice) == 1


def test_other_file_with_same_seller_and_number_is_duplicate(env):
    upload(env, invoice_pdf("V-2026/7"))
    r = upload(env, invoice_pdf("V-2026-7", extra="Másolat"), "copy.pdf").json()  # más bájtok, azonos kulcs
    assert r["result"] == "duplicate" and "kihagytuk" in r["message"]
    assert count(env, Invoice) == 1
    assert len(list(env.pdf_dir.glob("*.pdf"))) == 1  # a kihagyott fájl PDF-je nem marad meg


def test_same_number_from_other_seller_is_not_duplicate(env):
    upload(env, invoice_pdf("V-1"))
    r = upload(env, invoice_pdf("V-1", seller="Masik Bt.", seller_tax="87654321-1-41")).json()
    assert r["result"] == "created"
    assert count(env, Invoice) == 2


@pytest.mark.parametrize("data", [b"", b"hello world", b"<html>not a pdf</html>"])
def test_non_pdf_is_rejected_with_400_and_not_saved(env, data):
    r = upload(env, data, "level.txt")
    assert r.status_code == 400 and r.json()["detail"]
    assert count(env, Invoice) == 0


def test_too_large_file_is_413(env, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    r = upload(env, invoice_pdf())
    assert r.status_code == 413
    assert count(env, Invoice) == 0


def test_corrupt_pdf_is_error_and_app_keeps_working(env):
    r = upload(env, b"%PDF-1.4\n garbage garbage", "torott.pdf").json()
    assert r["result"] == "error" and r["invoice"]["status"] == "error"
    assert r["invoice"]["status_reason"] == "A fájl nem olvasható PDF-ként (sérült vagy hiányos fájl)."
    assert env.client.get("/api/health").json()["status"] == "ok"
    assert upload(env, invoice_pdf()).json()["result"] == "created"


def test_unexpected_exception_is_isolated(env, monkeypatch):
    import app.services.ingest as ingest_mod

    def boom(*_a, **_k):
        raise RuntimeError("bug")

    monkeypatch.setattr(ingest_mod, "process", boom)
    r = upload(env, invoice_pdf()).json()
    assert r["result"] == "error" and "Váratlan hiba" in r["message"]
    monkeypatch.undo()
    assert upload(env, invoice_pdf("V-2")).json()["result"] == "created"


def test_foreign_invoice_is_rejected_and_saved(env):
    pdf = invoice_pdf(buyer="Masik Zrt.", buyer_tax="11111111-2-41")
    r = upload(env, pdf).json()
    assert r["result"] == "rejected" and r["invoice"]["status"] == "rejected"
    assert r["invoice"]["partner"] is None and r["invoice"]["gross_huf"] is None
    assert upload(env, pdf).json()["result"] == "duplicate"  # nem fut újra


def test_credit_note_is_rejected(env):
    pdf = make_pdf([(40, 40, "Valami Kft."), (250, 80, "CREDIT NOTE"), (40, 120, "Bill to"),
                    (40, 134, "Nordwind Solutions Kft."), (40, 148, "Adószám: 26481937-2-43")])
    r = upload(env, pdf).json()
    assert r["result"] == "rejected" and r["invoice"]["doc_type"] == "credit_note"


def test_invoice_without_due_date_goes_to_review_without_llm(env):
    pdf = make_pdf([
        (40, 40, "Valami Kft."), (40, 54, "Adószám: 12345678-2-42"),
        (40, 90, "Bill to"), (40, 104, "Nordwind Solutions Kft."), (40, 118, "Adószám: 26481937-2-43"),
        (300, 90, "Számlaszám: V-2026/9"), (300, 104, "Kiállítás dátuma: 2026.05.04."),
        (300, 132, "Pénznem: HUF"), (300, 300, "Total due"), (480, 300, "127 000 Ft"),
    ])
    r = upload(env, pdf).json()
    assert r["result"] == "review" and r["message"].startswith("Ellenőrzendő")
    assert r["invoice"]["gross_huf"] is None
    assert env.client.get("/api/report").json()["totals"] == {"incoming_huf": 0, "outgoing_huf": 0}


def test_unquoted_currency_goes_to_review(env):
    r = upload(env, invoice_pdf(currency="CHF", total="1 000,00 CHF")).json()
    assert r["result"] == "review" and "CHF" in r["invoice"]["status_reason"]


# ----------------------------------------------------------------------------- árfolyam: K8, K9


def test_mnb_outage_gives_pending_fx_and_next_upload_retries(env):
    env.fake.fail = httpx.ConnectError("down")
    r = upload(env, invoice_pdf("V-1")).json()
    assert r["result"] == "created" and r["invoice"]["status"] == "pending_fx"
    assert "MNB" in r["message"] and r["invoice"]["gross_huf"] is None

    env.fake.fail = None
    upload(env, invoice_pdf("V-2"))  # a feltöltés elején újrapróbál
    invoices = {i["invoice_number"]: i for i in env.client.get("/api/invoices").json()}
    first = invoices["V-1"]
    assert first["status"] == "ok" and first["gross_huf"] == 390010
    assert "FX_UNAVAILABLE" not in [m["code"] for m in first["messages"]]


def test_mnb_outage_stops_retrying_after_first_failure(env):
    env.fake.fail = httpx.ConnectError("down")
    upload(env, invoice_pdf("V-1", supply="2026.05.02."))
    upload(env, invoice_pdf("V-2", supply="2026.07.02."))
    before = len(env.fake.requests)
    env.ingest.retry_fx(force=True)
    assert len(env.fake.requests) == before + 1  # nem kérdezünk számlánként, ha az MNB nem érhető el


def test_future_supply_date_is_provisional_and_later_finalised(env):
    r = upload(env, invoice_pdf("V-3", issue="2026.11.20.", supply="2026.12.04.", due="2026.12.20.")).json()
    inv = r["invoice"]
    assert r["result"] == "created" and "ideiglenes" in r["message"]
    assert inv["fx_provisional"] and inv["fx_rate_date"] == "2026-11-24"
    assert "FX_PROVISIONAL" in [m["code"] for m in inv["messages"]]
    assert env.client.get("/api/report").json()["counts"]["provisional"] == 1

    # Később megjelenik a teljesítés napjára szóló jegyzés.
    env.rates.clock["now"] += timedelta(days=15)
    env.fake.quotes += weekday_quotes("EUR", TODAY, date(2026, 12, 9))
    env.ingest.retry_fx(force=True)
    inv = env.client.get("/api/invoices").json()[0]
    assert not inv["fx_provisional"] and inv["fx_rate_date"] == "2026-12-04"
    assert inv["gross_huf"] == 390040
    assert "FX_PROVISIONAL" not in [m["code"] for m in inv["messages"]]


# ----------------------------------------------------------------------------- partnerek


def test_domestic_and_eu_tax_id_map_to_same_partner(env):
    upload(env, invoice_pdf("V-1", seller="Valami Kft."))
    upload(env, invoice_pdf("V-2", seller="VALAMI Kft.", seller_tax="HU12345678"))
    upload(env, invoice_pdf("V-3", seller="VALAMI Kft.", seller_tax="HU12345678"))
    assert count(env, Partner) == 1
    partner = env.client.get("/api/report").json()["partners"][0]
    assert partner["name"] == "VALAMI Kft."  # a leggyakoribb írásmód (K13)
    assert partner["aliases"] == ["VALAMI Kft.", "Valami Kft."]
    assert partner["incoming_huf"] == 3 * 390010  # három azonos összegű számla


def test_outgoing_invoice_partner_is_the_buyer(env):
    r = upload(env, invoice_pdf("NW-1", seller="Nordwind Solutions Kft.", seller_tax="26481937-2-43",
                                buyer="Vevo Kft.", buyer_tax="22222222-2-42")).json()
    inv = r["invoice"]
    assert inv["direction"] == "outgoing" and inv["partner"]["tax_key"] == "HU22222222"


# ----------------------------------------------------------------------------- lista, PDF, törlés


def test_list_is_newest_first_and_pdf_is_served(env):
    data = invoice_pdf("V-1")
    upload(env, data)
    upload(env, invoice_pdf("V-2"))
    items = env.client.get("/api/invoices").json()
    assert [i["invoice_number"] for i in items] == ["V-2", "V-1"]

    r = env.client.get(f"/api/invoices/{items[1]['id']}/pdf")
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert env.client.get("/api/invoices/9999/pdf").status_code == 404


def test_delete_one_removes_pdf_and_orphan_partner(env):
    a = upload(env, invoice_pdf("V-1")).json()["invoice"]
    b = upload(env, invoice_pdf("V-2")).json()["invoice"]
    c = upload(env, invoice_pdf("X-1", seller="Masik Bt.", seller_tax="87654321-1-41")).json()["invoice"]
    sha_c = _sha(env, c["id"])

    assert env.client.delete(f"/api/invoices/{c['id']}").status_code == 204
    assert not (env.pdf_dir / f"{sha_c}.pdf").exists()
    assert count(env, Partner) == 1  # a Masik Bt. árva lett

    assert env.client.delete(f"/api/invoices/{a['id']}").status_code == 204
    assert count(env, Partner) == 1  # a Valami Kft.-nek még van számlája
    assert env.client.delete(f"/api/invoices/{a['id']}").status_code == 404
    assert [i["id"] for i in env.client.get("/api/invoices").json()] == [b["id"]]

    # törlés után ugyanaz a fájl újra feltölthető
    assert upload(env, invoice_pdf("V-1")).json()["result"] == "created"


def test_delete_all_keeps_rate_cache(env):
    upload(env, invoice_pdf("V-1"))
    upload(env, invoice_pdf("V-2"))
    rates = count(env, ExchangeRate)
    assert rates > 0
    assert env.client.delete("/api/invoices").status_code == 204
    assert env.client.get("/api/invoices").json() == []
    assert count(env, Partner) == 0 and list(env.pdf_dir.glob("*.pdf")) == []
    assert count(env, ExchangeRate) == rates
    n = len(env.fake.requests)
    assert upload(env, invoice_pdf("V-1")).json()["result"] == "created"
    assert len(env.fake.requests) == n  # a cache-ből


# ----------------------------------------------------------------------------- a fixture-számlák végig


def test_all_fixture_invoices_are_processed_and_reported(env):
    results = [upload(env, p.read_bytes(), p.name).json() for p in PDFS]
    assert [r["result"] for r in results] == ["created"] * len(PDFS), [r["message"] for r in results]
    assert all(r["invoice"]["status"] == "ok" and r["invoice"]["gross_huf"] for r in results)

    # MNB-takarékosság: devizánként hónapra kerekített lekérések, egy nap sem kétszer
    seen = set()
    for start, end, curr in env.fake.requests:
        days = {(curr, start + timedelta(days=i)) for i in range((end - start).days + 1)}
        assert not days & seen
        seen |= days

    report = env.client.get("/api/report").json()
    months = [m["month"] for m in report["months"]]
    assert months == sorted(months) and len(months) == len(set(months))
    total = sum(r["invoice"]["gross_huf"] for r in results)
    assert report["totals"]["incoming_huf"] + report["totals"]["outgoing_huf"] == total
    assert sum(m["incoming_huf"] + m["outgoing_huf"] for m in report["months"]) == total
    assert sum(p["incoming_huf"] + p["outgoing_huf"] for p in report["partners"]) == total
    assert report["counts"]["ok"] == len(PDFS) == report["counts"]["total"]

    again = [upload(env, p.read_bytes(), p.name).json()["result"] for p in PDFS]
    assert again == ["duplicate"] * len(PDFS)


def test_parallel_uploads_of_same_new_partner(env):
    """4 párhuzamos feltöltés (K10) ugyanattól az új partnertől: nincs UNIQUE-ütközés, egy partner jön létre."""
    from concurrent.futures import ThreadPoolExecutor

    pdfs = [invoice_pdf(f"P-{i}", seller="Uj Partner Kft.", seller_tax="33333333-2-42") for i in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda d: env.ingest.ingest("p.pdf", d), pdfs))
    assert [r.result for r in results] == ["created"] * 12, [r.message for r in results]
    assert count(env, Partner) == 1 and count(env, Invoice) == 12
