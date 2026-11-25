"""Aggregáció: folytonos hónapok, csak `ok` státusz, partner-rendezés (7. fejezet)."""

from datetime import date
from decimal import Decimal

from app.models import Direction, Invoice, InvoiceStatus, Partner
from app.services.report import _month_range, build_report

_seq = iter(range(10_000))


def add(s, *, partner: Partner | None, direction: Direction, due: date, huf: int,
        status: InvoiceStatus = InvoiceStatus.ok, provisional: bool = False) -> Invoice:
    n = next(_seq)
    inv = Invoice(file_sha256=f"{n:064d}", filename=f"{n}.pdf", status=status, direction=direction,
                  due_date=due, gross_amount=Decimal(huf), currency="HUF", gross_huf=huf,
                  fx_provisional=provisional, partner=partner, invoice_number=f"N-{n}")
    s.add(inv)
    s.flush()
    return inv


def partner(s, key: str, name: str, aliases: dict | None = None) -> Partner:
    p = Partner(tax_key=key, display_name=name, aliases=aliases or {name: 1})
    s.add(p)
    s.flush()
    return p


def test_empty_database(db_session):
    r = build_report(db_session)
    assert r.months == [] and r.partners == []
    assert r.totals == {"incoming_huf": 0, "outgoing_huf": 0}
    assert r.counts["total"] == 0 and r.counts["ok"] == 0


def test_months_are_continuous_with_zeros(db_session):
    a = partner(db_session, "HU11111111", "A Kft.")
    add(db_session, partner=a, direction=Direction.incoming, due=date(2025, 11, 30), huf=100)
    add(db_session, partner=a, direction=Direction.outgoing, due=date(2026, 2, 1), huf=250)
    add(db_session, partner=a, direction=Direction.incoming, due=date(2026, 2, 28), huf=50)
    r = build_report(db_session)
    assert [(m.month, m.incoming_huf, m.outgoing_huf) for m in r.months] == [
        ("2025-11", 100, 0), ("2025-12", 0, 0), ("2026-01", 0, 0), ("2026-02", 50, 250),
    ]


def test_only_ok_invoices_are_counted(db_session):
    a = partner(db_session, "HU11111111", "A Kft.")
    add(db_session, partner=a, direction=Direction.incoming, due=date(2026, 3, 1), huf=100)
    add(db_session, partner=a, direction=Direction.incoming, due=date(2026, 3, 1), huf=1, provisional=True)
    for st in (InvoiceStatus.review, InvoiceStatus.pending_fx, InvoiceStatus.rejected, InvoiceStatus.error):
        add(db_session, partner=a, direction=Direction.incoming, due=date(2026, 6, 1), huf=1_000_000, status=st)
    r = build_report(db_session)
    assert r.totals == {"incoming_huf": 101, "outgoing_huf": 0}
    assert [m.month for m in r.months] == ["2026-03"]  # a nem ok számlák hónapja sem jelenik meg
    assert r.counts == {"ok": 2, "review": 1, "pending_fx": 1, "rejected": 1, "error": 1, "total": 6, "provisional": 1}


def test_partners_sorted_by_turnover_with_aliases(db_session):
    small = partner(db_session, "HU11111111", "Kicsi Kft.")
    big = partner(db_session, "GB284719356", "Big Ltd", {"Big Ltd": 2, "BIG LIMITED": 3})
    mixed = partner(db_session, "HU22222222", "Vegyes Zrt.")
    add(db_session, partner=small, direction=Direction.incoming, due=date(2026, 1, 5), huf=10)
    add(db_session, partner=big, direction=Direction.incoming, due=date(2026, 1, 5), huf=500)
    add(db_session, partner=mixed, direction=Direction.incoming, due=date(2026, 1, 5), huf=100)
    add(db_session, partner=mixed, direction=Direction.outgoing, due=date(2026, 1, 5), huf=300)
    r = build_report(db_session)
    assert [(p.name, p.incoming_huf, p.outgoing_huf) for p in r.partners] == [
        ("Big Ltd", 500, 0), ("Vegyes Zrt.", 100, 300), ("Kicsi Kft.", 10, 0),
    ]
    assert r.partners[0].aliases == ["BIG LIMITED", "Big Ltd"]


def test_partner_without_ok_invoice_is_not_listed(db_session):
    a = partner(db_session, "HU11111111", "A Kft.")
    add(db_session, partner=a, direction=Direction.incoming, due=date(2026, 1, 5), huf=10, status=InvoiceStatus.review)
    assert build_report(db_session).partners == []


def test_month_range_across_year():
    assert _month_range(date(2025, 12, 31), date(2026, 1, 1)) == ["2025-12", "2026-01"]
    assert _month_range(date(2026, 5, 1), date(2026, 5, 31)) == ["2026-05"]
