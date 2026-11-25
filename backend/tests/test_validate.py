from datetime import date
from decimal import Decimal

import pytest

from app.schemas import ExtractedInvoice, Party
from app.services.extraction import validate as v

OWN = v.OwnCompany("Nordwind Solutions Kft.", frozenset({"HU26481937"}))


def _inv(**kw) -> ExtractedInvoice:
    base = dict(
        doc_type="invoice",
        invoice_number="KT-2026/006",
        seller=Party(name="Kovács és Társa Bt.", tax_id="21847502-1-42", tax_keys=["HU21847502"]),
        buyer=Party(name="Nordwind Solutions Kft.", tax_id="26481937-2-43", tax_keys=["HU26481937"]),
        issue_date=date(2026, 1, 5),
        supply_date=date(2025, 12, 31),
        due_date=date(2026, 1, 13),
        currency="HUF",
        net_amount=Decimal("336800"),
        vat_amount=Decimal("90936"),
        gross_amount=Decimal("427736"),
    )
    base.update(kw)
    return ExtractedInvoice(**base)


def codes(msgs):
    return [m.code for m in msgs]


def test_valid_invoice_has_no_messages():
    assert v.validate(_inv(), OWN) == []


@pytest.mark.parametrize("field", ["invoice_number", "issue_date", "supply_date", "currency", "gross_amount"])
def test_missing_required_field(field):
    msgs = v.validate(_inv(**{field: None}), OWN)
    assert v.MISSING_FIELD in codes(msgs)
    assert v.has_errors(msgs)


def test_missing_partner_name_and_tax():
    msgs = v.validate(_inv(seller=Party()), OWN)
    assert v.MISSING_FIELD in codes(msgs)


def test_partner_with_name_only_is_enough():
    assert v.validate(_inv(seller=Party(name="Valami Kft.")), OWN) == []


def test_missing_due_date():
    assert codes(v.validate(_inv(due_date=None), OWN)) == [v.MISSING_DUE]


def test_unknown_currency():
    assert codes(v.validate(_inv(currency="XYZ"), OWN)) == [v.UNKNOWN_CURRENCY]


def test_sum_mismatch():
    assert codes(v.validate(_inv(gross_amount=Decimal("427000")), OWN)) == [v.SUM_MISMATCH]


def test_sum_tolerance_huf_one_forint_eur_one_cent():
    assert v.validate(_inv(gross_amount=Decimal("427737")), OWN) == []
    eur = dict(currency="EUR", net_amount=Decimal("908.00"), vat_amount=Decimal("245.16"))
    assert v.validate(_inv(gross_amount=Decimal("1153.16"), **eur), OWN) == []
    assert codes(v.validate(_inv(gross_amount=Decimal("1153.18"), **eur), OWN)) == [v.SUM_MISMATCH]


def test_gross_only_invoice_is_valid():
    assert v.validate(_inv(net_amount=None, vat_amount=None), OWN) == []


def test_due_before_issue():
    assert codes(v.validate(_inv(due_date=date(2026, 1, 1)), OWN)) == [v.DATE_ORDER]


def test_supply_far_from_issue():
    assert codes(v.validate(_inv(supply_date=date(2024, 6, 1)), OWN)) == [v.DATE_ORDER]


def test_own_company_on_neither_side():
    buyer = Party(name="Más Kft.", tax_keys=["HU11111111"])
    assert codes(v.validate(_inv(buyer=buyer), OWN)) == [v.OWN_COMPANY_SIDE]


def test_own_company_on_both_sides():
    seller = Party(name="Nordwind Solutions Kft.", tax_keys=["HU26481937"])
    assert codes(v.validate(_inv(seller=seller), OWN)) == [v.OWN_COMPANY_SIDE]


def test_direction_by_tax_and_by_name_fallback():
    assert v.direction_of(_inv(), OWN) == "incoming"
    no_tax = _inv(buyer=Party(name="NORDWIND SOLUTIONS KFT"))
    assert v.direction_of(no_tax, OWN) == "incoming"


def test_negative_total_is_rejection_code():
    msgs = v.validate(_inv(net_amount=None, vat_amount=None, gross_amount=Decimal("-1000")), OWN)
    assert v.NEGATIVE_TOTAL in codes(msgs)
    assert v.NEGATIVE_TOTAL in v.REJECT_CODES


def test_inference_supply_from_issue():
    inv, notes = v.apply_inference(_inv(supply_date=None))
    assert inv.supply_date == date(2026, 1, 5)
    assert codes(notes) == [v.INFERRED_SUPPLY]
    assert notes[0].level == "warning"


def test_inference_due_from_payment_terms():
    inv, notes = v.apply_inference(_inv(due_date=None, payment_terms_days=8))
    assert inv.due_date == date(2026, 1, 13)
    assert codes(notes) == [v.INFERRED_DUE]
    assert v.validate(inv, OWN) == []


def test_inference_does_not_override_existing_dates():
    original = _inv(payment_terms_days=30)
    inv, notes = v.apply_inference(original)
    assert inv == original and notes == []
