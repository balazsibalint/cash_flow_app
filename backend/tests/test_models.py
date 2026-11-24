from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import Direction, ExchangeRate, Invoice, InvoiceStatus, Partner
from app.schemas import InvoiceOut


def _invoice(**kw) -> Invoice:
    base = dict(file_sha256="a" * 64, filename="x.pdf", status=InvoiceStatus.ok)
    base.update(kw)
    return Invoice(**base)


def test_decimal_roundtrip_is_exact(db_session):
    # Float-tárolásnál ezek az értékek elveszítenék a pontosságukat.
    amount = Decimal("123456789012.34")
    rate = Decimal("396.920000")
    db_session.add(_invoice(gross_amount=amount, fx_rate=rate))
    db_session.commit()
    db_session.expire_all()

    inv = db_session.query(Invoice).one()
    assert inv.gross_amount == amount
    assert isinstance(inv.gross_amount, Decimal)
    assert inv.fx_rate == rate
    stored = db_session.execute(text("SELECT gross_amount, typeof(gross_amount) FROM invoices")).one()
    assert stored == ("123456789012.34", "text")


def test_decimal_column_rejects_float(db_session):
    db_session.add(_invoice(gross_amount=1.5))
    with pytest.raises(Exception):
        db_session.commit()


def test_enums_stored_as_values(db_session):
    db_session.add(_invoice(status=InvoiceStatus.pending_fx, direction=Direction.incoming))
    db_session.commit()
    row = db_session.execute(text("SELECT status, direction FROM invoices")).one()
    assert row == ("pending_fx", "incoming")


def test_file_hash_is_unique(db_session):
    db_session.add(_invoice())
    db_session.commit()
    db_session.add(_invoice())
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_seller_and_number_unique(db_session):
    db_session.add(_invoice(file_sha256="a" * 64, seller_tax_key="HU21847502", invoice_number_norm="KT2026006"))
    db_session.commit()
    db_session.add(_invoice(file_sha256="b" * 64, seller_tax_key="HU21847502", invoice_number_norm="KT2026006"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_incomplete_rows_do_not_collide(db_session):
    # Hiányos (review/error) számláknál NULL a kulcs – ezek nem ütközhetnek egymással.
    db_session.add(_invoice(file_sha256="a" * 64, status=InvoiceStatus.error))
    db_session.add(_invoice(file_sha256="b" * 64, status=InvoiceStatus.error))
    db_session.commit()
    assert db_session.query(Invoice).count() == 2


def test_partner_relation_and_json_fields(db_session):
    p = Partner(tax_key="HU14829375", display_name="Duna Logisztika Zrt.", aliases={"DUNA LOGISZTIKA ZRT.": 2})
    inv = _invoice(partner=p, messages=[{"code": "INFERRED_DUE", "level": "warning", "text": "x"}])
    db_session.add(inv)
    db_session.commit()
    db_session.expire_all()
    inv = db_session.query(Invoice).one()
    assert inv.partner.tax_key == "HU14829375"
    assert inv.partner.aliases == {"DUNA LOGISZTIKA ZRT.": 2}
    assert inv.messages[0]["code"] == "INFERRED_DUE"


def test_exchange_rate_composite_key(db_session):
    db_session.add(ExchangeRate(date=date(2026, 3, 9), currency="EUR", rate=Decimal("390.12"), unit=1))
    db_session.commit()
    db_session.add(ExchangeRate(date=date(2026, 3, 9), currency="EUR", rate=Decimal("1"), unit=1))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invoice_out_serializes_money_as_string(db_session):
    db_session.add(_invoice(gross_amount=Decimal("1493.78"), fx_rate=Decimal("1E+2"), currency="EUR", gross_huf=583212))
    db_session.commit()
    out = InvoiceOut.model_validate(db_session.query(Invoice).one()).model_dump(mode="json")
    assert out["gross_amount"] == "1493.78"
    assert out["fx_rate"] == "100"  # tudományos jelölés nélkül
    assert out["gross_huf"] == 583212
