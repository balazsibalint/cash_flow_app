"""MNB-kliens, gyorsítótár és árfolyam-kiválasztás – mockolt HTTP-vel (a tests/mnb alatt egy valódi MNB-válasz)."""

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

import httpx
import pytest
from sqlalchemy import func, select

from app.models import ExchangeRate, MnbFetch
from app.services.mnb import MnbClient, MnbNoRate, MnbUnavailable, Quote, RateService, parse_response

REAL_MARCH = (Path(__file__).parent / "mnb" / "rates_2026_03.xml").read_bytes()


def soap(days: dict[str, list[tuple[str, str, int]]]) -> bytes:
    """Szintetikus MNB-válasz: {"2026-03-09": [("EUR", "385,12", 1)], ...}."""
    inner = "<MNBExchangeRates>" + "".join(
        f'<Day date="{d}">' + "".join(f'<Rate unit="{u}" curr="{c}">{v}</Rate>' for c, v, u in rates) + "</Day>"
        for d, rates in days.items()
    ) + "</MNBExchangeRates>"
    return (
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"><s:Body>'
        '<GetExchangeRatesResponse xmlns="http://www.mnb.hu/webservices/"><GetExchangeRatesResult>'
        f"{escape(inner)}</GetExchangeRatesResult></GetExchangeRatesResponse></s:Body></s:Envelope>"
    ).encode()


class FakeMnb:
    """Az MNB-t utánzó transport: a kért időszakra és devizára a `quotes` jegyzéseit adja vissza."""

    def __init__(self, quotes: list[Quote] | None = None, fail: Exception | int | None = None):
        self.quotes = quotes or []
        self.fail = fail
        self.requests: list[tuple[date, date, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        start = date.fromisoformat(re.search(r"<web:startDate>(.*?)<", body)[1])
        end = date.fromisoformat(re.search(r"<web:endDate>(.*?)<", body)[1])
        curr = re.search(r"<web:currencyNames>(.*?)<", body)[1]
        self.requests.append((start, end, curr))
        assert request.headers["SOAPAction"].endswith('/GetExchangeRates"')
        if isinstance(self.fail, Exception):
            raise self.fail
        if isinstance(self.fail, int):
            return httpx.Response(self.fail, text="error")
        days: dict[str, list] = {}
        for q in self.quotes:
            if start <= q.date <= end and q.currency in curr.split(","):
                days.setdefault(q.date.isoformat(), []).append((q.currency, str(q.rate).replace(".", ","), q.unit))
        return httpx.Response(200, content=soap(days))


def weekday_quotes(currency: str, start: date, end: date, *, skip: set[date] = frozenset(),
                   base: str = "390", unit: int = 1) -> list[Quote]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5 and d not in skip:
            out.append(Quote(d, currency, Decimal(base) + Decimal(d.day) / 100, unit))
        d += timedelta(days=1)
    return out


def service(fake: FakeMnb, today: date) -> RateService:
    clock = {"now": datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc)}
    svc = RateService(MnbClient("http://mnb.test/arfolyamok.asmx", transport=httpx.MockTransport(fake)),
                      now=lambda: clock["now"])
    svc.clock = clock  # a tesztek léptethetik az időt
    return svc


# ----------------------------------------------------------------------------- válasz-feldolgozás


def test_parses_real_mnb_response():
    quotes = parse_response(REAL_MARCH)
    eur = {q.date: q for q in quotes if q.currency == "EUR"}
    assert {q.currency for q in quotes} == {"EUR", "USD", "GBP", "PLN"}
    assert date(2026, 3, 7) not in eur and date(2026, 3, 8) not in eur  # hétvége: nincs jegyzés
    assert eur[date(2026, 3, 31)].rate == Decimal("385.85")  # tizedesvessző → Decimal
    assert all(q.unit == 1 for q in quotes)


def test_parses_unit_and_empty_result():
    quotes = parse_response(soap({"2026-03-09": [("JPY", "231,45", 100)]}))
    assert quotes == [Quote(date(2026, 3, 9), "JPY", Decimal("231.45"), 100)]
    assert parse_response(soap({})) == []


@pytest.mark.parametrize("body", [b"not xml", b"<a><b/></a>",
                                  b'<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
                                  b"<s:Body><s:Fault><faultstring>x</faultstring></s:Fault></s:Body></s:Envelope>"])
def test_invalid_responses_raise_unavailable(body):
    with pytest.raises(MnbUnavailable):
        parse_response(body)


# ----------------------------------------------------------------------------- kiválasztás


def test_rate_on_quote_day(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 2, 1), date(2026, 3, 31)))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 3, 9))
    assert (choice.rate_date, choice.rate, choice.provisional) == (date(2026, 3, 9), Decimal("390.09"), False)


def test_weekend_uses_previous_friday(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 2, 1), date(2026, 3, 31)))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 3, 8))  # vasárnap
    assert choice.rate_date == date(2026, 3, 6)


def test_holiday_streak_uses_last_quote_before(db_session):
    # Húsvét 2026: nagypéntek (ápr. 3.) és húsvéthétfő (ápr. 6.) – nincs jegyzés.
    holidays = {date(2026, 4, 3), date(2026, 4, 6)}
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 3, 1), date(2026, 4, 30), skip=holidays))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 4, 6))
    assert choice.rate_date == date(2026, 4, 2)


def test_first_days_of_month_look_back_into_previous_month(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2025, 12, 1), date(2026, 1, 31), skip={date(2026, 1, 1), date(2026, 1, 2)}))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 1, 3))
    assert choice.rate_date == date(2025, 12, 31)


def test_unit_is_respected_in_choice(db_session):
    fake = FakeMnb(weekday_quotes("JPY", date(2026, 3, 1), date(2026, 3, 31), base="231", unit=100))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "JPY", date(2026, 3, 10))
    assert choice.unit == 100


def test_huf_needs_no_request(db_session):
    fake = FakeMnb()
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "HUF", date(2026, 3, 9))
    assert (choice.rate, choice.unit, choice.rate_date, choice.provisional) == (Decimal("1"), 1, date(2026, 3, 9), False)
    assert fake.requests == []


def test_future_supply_date_is_provisional(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 10, 1), date(2026, 11, 24)))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 12, 4))
    assert choice.rate_date == date(2026, 11, 24) and choice.provisional
    assert all(end <= date(2026, 11, 25) for _, end, _ in fake.requests)  # jövőre nem kérdezünk


def test_today_before_publication_is_provisional(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 10, 1), date(2026, 11, 24)))
    choice = service(fake, date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 11, 25))
    assert choice.rate_date == date(2026, 11, 24) and choice.provisional


def test_unquoted_currency_raises_no_rate(db_session):
    with pytest.raises(MnbNoRate):
        service(FakeMnb(), date(2026, 11, 25)).select_rate(db_session, "XAU", date(2026, 3, 9))


@pytest.mark.parametrize("fail", [httpx.ConnectError("down"), 500, 404])
def test_unavailable_mnb_raises_and_records_nothing(db_session, fail):
    with pytest.raises(MnbUnavailable):
        service(FakeMnb(fail=fail), date(2026, 11, 25)).select_rate(db_session, "EUR", date(2026, 3, 9))
    assert db_session.scalar(select(func.count()).select_from(MnbFetch)) == 0


# ----------------------------------------------------------------------------- gyorsítótár


def test_second_lookup_in_same_period_makes_no_request(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 2, 1), date(2026, 3, 31)))
    svc = service(fake, date(2026, 11, 25))
    svc.select_rate(db_session, "EUR", date(2026, 3, 9))
    n = len(fake.requests)
    svc.select_rate(db_session, "EUR", date(2026, 3, 20))
    svc.select_rate(db_session, "EUR", date(2026, 3, 9))
    assert len(fake.requests) == n


def test_only_missing_interval_is_requested(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 2, 1), date(2026, 4, 30)))
    svc = service(fake, date(2026, 11, 25))
    svc.select_rate(db_session, "EUR", date(2026, 3, 20))  # márc. (+ febr. vége)
    before = list(fake.requests)
    svc.select_rate(db_session, "EUR", date(2026, 4, 15))  # csak április hiányzik
    new = fake.requests[len(before):]
    assert new == [(date(2026, 4, 1), date(2026, 4, 30), "EUR")]


def test_no_day_currency_is_requested_twice(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2025, 12, 1), date(2026, 10, 31)))
    svc = service(fake, date(2026, 11, 25))
    for month in range(1, 11):
        for day in (1, 9, 17, 28):
            svc.select_rate(db_session, "EUR", date(2026, month, day))
    days = []
    for start, end, _ in fake.requests:
        days += [start + timedelta(days=i) for i in range((end - start).days + 1)]
    assert len(days) == len(set(days))
    assert len(fake.requests) <= 11  # havonta legfeljebb egy hívás


def test_currencies_are_cached_separately(db_session):
    quotes = weekday_quotes("EUR", date(2026, 2, 1), date(2026, 3, 31)) + weekday_quotes("USD", date(2026, 2, 1), date(2026, 3, 31))
    fake = FakeMnb(quotes)
    svc = service(fake, date(2026, 11, 25))
    svc.select_rate(db_session, "EUR", date(2026, 3, 9))
    svc.select_rate(db_session, "USD", date(2026, 3, 9))
    assert {c for _, _, c in fake.requests} == {"EUR", "USD"}
    assert db_session.scalar(select(func.count()).select_from(ExchangeRate).where(ExchangeRate.currency == "USD")) > 0


def test_today_is_refetched_only_on_the_next_day(db_session):
    fake = FakeMnb(weekday_quotes("EUR", date(2026, 10, 1), date(2026, 11, 26)))
    svc = service(fake, date(2026, 11, 25))
    svc.select_rate(db_session, "EUR", date(2026, 11, 25))
    n = len(fake.requests)
    svc.select_rate(db_session, "EUR", date(2026, 11, 25))
    assert len(fake.requests) == n  # aznap nem kérdezzük újra

    svc.clock["now"] += timedelta(days=1)  # másnap
    choice = svc.select_rate(db_session, "EUR", date(2026, 11, 26))
    new = fake.requests[n:]
    assert new and new[0][0] == date(2026, 11, 25)  # a tegnapi nap is újra, a mai jegyzés miatt
    assert choice.rate_date == date(2026, 11, 26) and not choice.provisional
