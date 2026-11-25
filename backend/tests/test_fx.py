from decimal import Decimal

import pytest

from app.services.fx import to_huf


@pytest.mark.parametrize(
    "amount, rate, unit, expected",
    [
        ("1153.16", "396.92", 1, 457712),  # 457 712,2672 → lefelé
        ("100.00", "385.855", 1, 38586),  # 38 585,5 → 0,5-től felfelé
        ("10.00", "385.8549", 1, 3859),  # 3858,549 → felfelé (≥ 0,5)
        ("1.00", "385.4999", 1, 385),  # 385,4999 → lefelé
        ("427736", "1", 1, 427736),  # HUF
        ("1000", "231.45", 100, 2315),  # JPY: 100 egységre jegyzett, 2314,5 → felfelé
    ],
)
def test_to_huf_rounding(amount, rate, unit, expected):
    assert to_huf(Decimal(amount), Decimal(rate), unit) == expected


def test_to_huf_rejects_float():
    with pytest.raises(TypeError):
        to_huf(1153.16, Decimal("396.92"))


def test_to_huf_rejects_invalid_unit():
    with pytest.raises(ValueError):
        to_huf(Decimal("1"), Decimal("1"), 0)
