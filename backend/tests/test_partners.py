"""Partnerkulcs, összevonás és megjelenített név (5.7, K13)."""

from decimal import Decimal

from sqlalchemy import func, select

from app.models import Direction, Invoice, InvoiceStatus, Partner
from app.schemas import Party
from app.services import partners as pt

OWN = frozenset({"HU26481937"})
_seq = iter(range(10_000))


def invoice(s, partner: Partner, seller_name: str) -> Invoice:
    n = next(_seq)
    inv = Invoice(file_sha256=f"{n:064d}", filename="x.pdf", status=InvoiceStatus.ok, direction=Direction.incoming,
                  seller_name=seller_name, gross_amount=Decimal("1"), partner=partner)
    s.add(inv)
    s.flush()
    return inv


def test_domestic_and_eu_tax_ids_give_same_key():
    assert pt.party_tax_key(Party(tax_id="12345678-2-42")) == pt.party_tax_key(Party(tax_id="HU12345678")) == "HU12345678"


def test_own_key_is_excluded_from_counterparty():
    party = Party(tax_id="26481937-2-43", tax_keys=["HU26481937", "HU12345678"])
    assert pt.party_tax_key(party, exclude=OWN) == "HU12345678"
    assert pt.party_tax_key(Party(tax_id="HU26481937", tax_keys=["HU26481937"]), exclude=OWN) is None


def test_counterparty_by_direction():
    seller, buyer = Party(name="S"), Party(name="B")
    assert pt.counterparty(seller, buyer, "incoming") is seller
    assert pt.counterparty(seller, buyer, "outgoing") is buyer


def test_name_only_partner_is_merged_into_tax_partner(db_session):
    by_name = pt.find_or_create(db_session, None, "Valami Kft.")
    assert by_name.tax_key == "NAME:valami"
    invoice(db_session, by_name, "Valami Kft.")

    by_tax = pt.find_or_create(db_session, "HU12345678", "VALAMI KFT")
    invoice(db_session, by_tax, "VALAMI KFT")
    pt.refresh(db_session, by_tax)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Partner)) == 1
    assert len(by_tax.invoices) == 2
    # később érkező, adószám nélküli számla is ehhez a partnerhez kerül (névváltozat alapján)
    assert pt.find_or_create(db_session, None, "Valami kft") is by_tax


def test_display_name_is_most_common_then_earliest(db_session):
    p = pt.find_or_create(db_session, "HU12345678", "Első Kft.")
    invoice(db_session, p, "Első Kft.")
    invoice(db_session, p, "ELSŐ KFT.")
    pt.refresh(db_session, p)
    assert p.display_name == "Első Kft."  # holtverseny → a legkorábbi
    invoice(db_session, p, "ELSŐ KFT.")
    pt.refresh(db_session, p)
    assert p.display_name == "ELSŐ KFT." and p.aliases == {"Első Kft.": 1, "ELSŐ KFT.": 2}


def test_orphan_partner_is_deleted_on_refresh(db_session):
    p = pt.find_or_create(db_session, "HU12345678", "X Kft.")
    pt.refresh(db_session, p)
    db_session.commit()
    assert db_session.scalar(select(func.count()).select_from(Partner)) == 0


def test_missing_key_and_name_gives_unknown_partner(db_session):
    p = pt.find_or_create(db_session, None, None)
    assert p.tax_key == pt.UNKNOWN_KEY and p.display_name == pt.UNKNOWN_NAME
