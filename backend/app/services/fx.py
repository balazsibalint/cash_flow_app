from decimal import ROUND_HALF_UP, Decimal


def to_huf(amount: Decimal, rate: Decimal, unit: int = 1) -> int:
    if not isinstance(amount, Decimal) or not isinstance(rate, Decimal):
        raise TypeError("Az átváltás csak Decimal értékekkel végezhető (float pontatlan).")
    if unit <= 0:
        raise ValueError("Az árfolyam egységének pozitívnak kell lennie.")
    return int((amount * rate / Decimal(unit)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
