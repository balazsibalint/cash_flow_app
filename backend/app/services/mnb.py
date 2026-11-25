import calendar
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExchangeRate, MnbFetch

SOAP_ACTION = '"http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"'
LOOKBACK_DAYS = 10
EXTENDED_LOOKBACK_DAYS = 40


class MnbUnavailable(Exception):
    """Hálózati vagy SOAP-hiba – a számla `pending_fx` státuszt kap (K9)."""


class MnbNoRate(Exception):
    """Az MNB nem jegyzi a devizát (vagy nincs jegyzés a visszatekintési időszakban)."""


@dataclass(frozen=True)
class Quote:
    date: date
    currency: str
    rate: Decimal
    unit: int


@dataclass(frozen=True)
class RateChoice:
    rate: Decimal
    unit: int
    rate_date: date
    provisional: bool  # K8: még nincs jegyzés a teljesítés napjára (jövőbeli / mai nap)


# --------------------------------------------------------------------------- SOAP-kliens


def _envelope(start: date, end: date, currencies: list[str]) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:web="http://www.mnb.hu/webservices/"><soap:Body><web:GetExchangeRates>'
        f"<web:startDate>{start.isoformat()}</web:startDate>"
        f"<web:endDate>{end.isoformat()}</web:endDate>"
        f"<web:currencyNames>{','.join(currencies)}</web:currencyNames>"
        "</web:GetExchangeRates></soap:Body></soap:Envelope>"
    )


def parse_response(xml_text: str | bytes) -> list[Quote]:
    """A SOAP-válasz → jegyzések. A `GetExchangeRatesResult` maga is XML (escape-elt szövegként)."""
    try:
        outer = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise MnbUnavailable(f"az MNB válasza nem értelmezhető XML ({exc})") from exc
    if any(el.tag.endswith("Fault") for el in outer.iter()):
        raise MnbUnavailable("az MNB SOAP-hibát adott vissza")
    result = next((el for el in outer.iter() if el.tag.endswith("GetExchangeRatesResult")), None)
    if result is None:
        raise MnbUnavailable("az MNB válaszából hiányzik a GetExchangeRatesResult elem")
    if not (result.text or "").strip():
        return []
    try:
        inner = ET.fromstring(result.text)
    except ET.ParseError as exc:
        raise MnbUnavailable(f"az MNB árfolyamlistája nem értelmezhető ({exc})") from exc

    quotes = []
    for day in inner.iter("Day"):
        d = date.fromisoformat(day.get("date"))
        for rate in day.iter("Rate"):
            try:
                value = Decimal((rate.text or "").strip().replace(",", "."))
            except InvalidOperation:
                continue
            quotes.append(Quote(d, rate.get("curr"), value, int(rate.get("unit") or 1)))
    return quotes


class MnbClient:
    def __init__(self, url: str, timeout: float = 20, transport: httpx.BaseTransport | None = None):
        self.url = url
        self.timeout = timeout
        self._transport = transport
        self.calls = 0  # diagnosztika / tesztek

    def get_exchange_rates(self, start: date, end: date, currencies: list[str]) -> list[Quote]:
        self.calls += 1
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": SOAP_ACTION}
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                resp = client.post(self.url, content=_envelope(start, end, currencies).encode(), headers=headers)
        except httpx.HTTPError as exc:
            raise MnbUnavailable(f"az MNB szolgáltatás nem érhető el ({type(exc).__name__})") from exc
        if resp.status_code != 200:
            raise MnbUnavailable(f"az MNB szolgáltatás hibát adott (HTTP {resp.status_code})")
        return parse_response(resp.content)


# --------------------------------------------------------------------------- gyorsítótár és kiválasztás


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _subtract(interval: tuple[date, date], covered: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """`interval` azon részei, amelyeket a `covered` intervallumok nem fednek le."""
    start, end = interval
    gaps = []
    cursor = start
    for c_start, c_end in sorted(covered):
        if c_end < cursor:
            continue
        if c_start > end:
            break
        if c_start > cursor:
            gaps.append((cursor, min(end, c_start - timedelta(days=1))))
        cursor = max(cursor, c_end + timedelta(days=1))
        if cursor > end:
            break
    if cursor <= end:
        gaps.append((cursor, end))
    return gaps


_FETCH_LOCK = threading.Lock()  # párhuzamos feltöltéseknél ugyanazt az időszakot ne kérjük le kétszer


class RateService:
    def __init__(self, client: MnbClient, *, now: Callable[[], datetime] | None = None):
        self.client = client
        self._now = now or (lambda: datetime.now(timezone.utc))

    def today(self) -> date:
        return self._now().date()

    def _covered(self, session: Session, currency: str) -> list[tuple[date, date]]:
        """A lekérdezett időszakok. Ha egy lekérés a lekérés napját (vagy későbbit) is tartalmazta,
        az a nap csak aznap számít lefedettnek – másnap újra megnézzük (a jegyzés napközben jelenik meg)."""
        today = self.today()
        out = []
        for f in session.scalars(select(MnbFetch).where(MnbFetch.currency == currency)):
            fetched_on = f.fetched_at.date()
            end = f.end_date
            if end >= fetched_on and fetched_on != today:
                end = fetched_on - timedelta(days=1)
            if end >= f.start_date:
                out.append((f.start_date, end))
        return out

    def ensure_rates(self, session: Session, currency: str, start: date, end: date) -> None:
        end = min(end, self.today())
        if start > end:
            return
        with _FETCH_LOCK:
            for gap_start, gap_end in _subtract((start, end), self._covered(session, currency)):
                quotes = self.client.get_exchange_rates(gap_start, gap_end, [currency])
                for q in quotes:
                    if q.currency == currency:
                        session.merge(ExchangeRate(date=q.date, currency=q.currency, rate=q.rate, unit=q.unit,
                                                   fetched_at=self._now()))
                session.add(MnbFetch(currency=currency, start_date=gap_start, end_date=gap_end,
                                     fetched_at=self._now()))
                session.commit()

    def _latest_on_or_before(self, session: Session, currency: str, day: date) -> ExchangeRate | None:
        return session.scalars(
            select(ExchangeRate)
            .where(ExchangeRate.currency == currency, ExchangeRate.date <= day)
            .order_by(ExchangeRate.date.desc())
            .limit(1)
        ).first()

    def select_rate(self, session: Session, currency: str, supply_date: date) -> RateChoice:
        """A teljesítés napján érvényes MNB-árfolyam (ha aznap nem volt jegyzés, az azt megelőző utolsó)."""
        if currency == "HUF":
            return RateChoice(Decimal("1"), 1, supply_date, False)

        lookup_day = min(supply_date, self.today())
        self.ensure_rates(session, currency, _month_start(lookup_day - timedelta(days=LOOKBACK_DAYS)),
                          _month_end(lookup_day))
        quote = self._latest_on_or_before(session, currency, supply_date)
        if quote is None or (lookup_day - quote.date).days > LOOKBACK_DAYS:
            # Hosszú jegyzésszünet (vagy a hónap eleje előtti időszak): bővebb visszatekintés.
            self.ensure_rates(session, currency, lookup_day - timedelta(days=EXTENDED_LOOKBACK_DAYS), lookup_day)
            quote = self._latest_on_or_before(session, currency, supply_date)
        if quote is None:
            raise MnbNoRate(f"Az MNB nem tesz közzé árfolyamot erre a devizára: {currency}.")

        provisional = supply_date >= self.today() and quote.date < supply_date
        return RateChoice(quote.rate, quote.unit, quote.date, provisional)
