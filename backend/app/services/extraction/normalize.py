import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

# --------------------------------------------------------------------------- szöveg


_SPECIAL_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ß": "ss", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "æ": "ae"})
_SPACED_LETTERS = re.compile(r"\b(?:[^\W\d_] ){2,}[^\W\d_]\b")


def strip_accents(s: str) -> str:
    s = s.translate(_SPECIAL_FOLD)
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def fold(s: str) -> str:
    """Összehasonlításhoz: kisbetű, ékezet nélkül, egységes szóközök, ritkított szavak összevonva (`S Z Á M L A` → `szamla`)."""
    s = strip_accents(s).replace(" ", " ").replace(" ", " ")
    s = _SPACED_LETTERS.sub(lambda m: m.group(0).replace(" ", ""), s)
    return re.sub(r"\s+", " ", s).strip().lower()


# --------------------------------------------------------------------------- dátum

# Hónapnevek 7 nyelven (+ néhány gyakori változat), ékezet nélkül, kisbetűvel.
# A rövidítéseket prefix-illesztés kezeli (lásd _month_from_token).
_MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("januar", "january", "janvier", "januar", "janner", "enero", "gennaio", "styczen", "stycznia"),
    2: ("februar", "february", "fevrier", "febrero", "febbraio", "luty", "lutego"),
    3: ("marcius", "march", "mars", "marz", "marzo", "marzec", "marca"),
    4: ("aprilis", "april", "avril", "abril", "aprile", "kwiecien", "kwietnia"),
    5: ("majus", "may", "mai", "mayo", "maggio", "maj", "maja"),
    6: ("junius", "june", "juin", "juni", "junio", "giugno", "czerwiec", "czerwca"),
    7: ("julius", "july", "juillet", "juli", "julio", "luglio", "lipiec", "lipca"),
    8: ("augusztus", "august", "aout", "agosto", "sierpien", "sierpnia"),
    9: ("szeptember", "september", "septembre", "septiembre", "settembre", "wrzesien", "wrzesnia"),
    10: ("oktober", "october", "octobre", "octubre", "ottobre", "pazdziernik", "pazdziernika"),
    11: ("november", "novembre", "noviembre", "listopad", "listopada"),
    12: ("december", "decembre", "dezember", "diciembre", "dicembre", "grudzien", "grudnia"),
}
_ALL_MONTH_NAMES = [(name, m) for m, names in _MONTH_NAMES.items() for name in names]


def _month_from_token(token: str) -> int | None:
    """Hónapnév vagy egyértelmű rövidítése (min. 3 betű) → hónap száma."""
    t = fold(token).rstrip(".")
    if len(t) < 3 or not t.isalpha():
        return None
    months = {m for name, m in _ALL_MONTH_NAMES if name.startswith(t)}
    return months.pop() if len(months) == 1 else None


def _mkdate(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000
    try:
        return date(y, m, d)
    except ValueError:
        return None


@dataclass(frozen=True)
class DateMatch:
    value: date
    start: int
    end: int


_W = r"[^\W\d_]+"  # betűkből álló szó (ékezetesen is)
_DATE_PATTERNS: list[tuple[str, re.Pattern]] = [
    # 2026-03-15
    ("iso", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
    # 2026.03.15.  2026. 03. 15.  2026/03/15
    ("ymd", re.compile(r"(?<!\d)(\d{4})\s?[./]\s?(\d{1,2})\s?[./]\s?(\d{1,2})(?!\d)\.?")),
    # 2026. június 24.
    ("y_mon_d", re.compile(rf"(?<!\d)(\d{{4}})\.?\s+({_W})\.?\s+(\d{{1,2}})(?!\d)\.?")),
    # 15.03.2026  04/03/2026  15-03-2026  15.03.26
    ("dmy_num", re.compile(r"(?<![\d.])(\d{1,2})\s?([./-])\s?(\d{1,2})\s?\2\s?(\d{4}|\d{2})(?![\d])")),
    # 10. März 2026  13 mars 2026  16 de abril de 2026  30 January 2026
    ("d_mon_y", re.compile(rf"(?<!\d)(\d{{1,2}})(?:er|st|nd|rd|th)?\.?\s+(?:de\s+)?({_W})\.?,?\s+(?:de\s+)?(\d{{4}})(?!\d)")),
    # February 1, 2026  Feb 1st 2026
    ("mon_d_y", re.compile(rf"\b({_W})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)")),
]


def find_dates(text: str, *, dayfirst: bool = True) -> list[DateMatch]:
    """Az összes felismert dátum a szövegben, pozíció szerint, átfedés nélkül.

    `dayfirst=False` csak amerikai kontextusban kell: ekkor a kétértelmű `04/03/2026` április 3.
    Ha az egyik tag > 12, a sorrend egyértelmű, és a paramétert figyelmen kívül hagyjuk.
    """
    found: list[DateMatch] = []
    for kind, rx in _DATE_PATTERNS:
        for m in rx.finditer(text):
            d: date | None = None
            if kind in ("iso", "ymd"):
                d = _mkdate(int(m[1]), int(m[2]), int(m[3]))
            elif kind == "y_mon_d":
                month = _month_from_token(m[2])
                d = _mkdate(int(m[1]), month, int(m[3])) if month else None
            elif kind == "dmy_num":
                a, b, y = int(m[1]), int(m[3]), int(m[4])
                if a > 12 or (dayfirst and b <= 12):
                    d = _mkdate(y, b, a)
                else:
                    d = _mkdate(y, a, b) or _mkdate(y, b, a)
            elif kind == "d_mon_y":
                month = _month_from_token(m[2])
                d = _mkdate(int(m[3]), month, int(m[1])) if month else None
            elif kind == "mon_d_y":
                month = _month_from_token(m[1])
                d = _mkdate(int(m[3]), month, int(m[2])) if month else None
            if d is not None:
                found.append(DateMatch(d, m.start(), m.end()))

    # Átfedő találatoknál a korábban kezdődő, majd a hosszabb nyer.
    found.sort(key=lambda x: (x.start, -(x.end - x.start)))
    result: list[DateMatch] = []
    for dm in found:
        if not result or dm.start >= result[-1].end:
            result.append(dm)
    return result


def parse_date(s: str | None, *, dayfirst: bool = True) -> date | None:
    """Az első felismerhető dátum a szövegben, vagy None."""
    if not s:
        return None
    matches = find_dates(s, dayfirst=dayfirst)
    return matches[0].value if matches else None


# --------------------------------------------------------------------------- összeg

_GROUP_SPACES = "    '’"
_AMOUNT_RX = re.compile(
    r"(?<![\w.,])"
    # Csak közvetlenül a számhoz tapadó mínusz negatív: a ` – ` gondolatjel szöveges elválasztó.
    r"(?P<neg>[-−](?=\d)|\(\s?)?"
    r"(?P<num>"
    r"\d{1,3}(?:[    '’]\d{3})+(?:[.,]\d{1,4})?"  # 1 234 567,89
    r"|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,4})?"  # 1.234.567,89 / 1,234.56
    r"|\d+(?:[.,]\d+)?"  # 1234,56 / 739.00 / 140000
    r")"
    r"(?P<close>\s?\))?"
    r"(?![\d])"
)


@dataclass(frozen=True)
class AmountMatch:
    value: Decimal
    start: int
    end: int


def _decimal_from_number(num: str) -> Decimal | None:
    s = num
    for ch in _GROUP_SPACES:
        s = s.replace(ch, "")
    commas, dots = s.count(","), s.count(".")
    if commas and dots:
        # Mindkettő szerepel: az utolsó a tizedesjel.
        dec, grp = (",", ".") if s.rfind(",") > s.rfind(".") else (".", ",")
        s = s.replace(grp, "").replace(dec, ".")
    elif commas or dots:
        sep = "," if commas else "."
        if s.count(sep) > 1:
            s = s.replace(sep, "")  # csak ezres tagolás lehet
        else:
            int_part, frac = s.split(sep)
            if len(frac) == 3 and int_part not in ("", "0"):
                s = int_part + frac  # 1.234 / 3,465 → ezres
            else:
                s = f"{int_part}.{frac}"
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def find_amounts(text: str) -> list[AmountMatch]:
    """Összeg-jelöltek a szövegben (szóközzel tagolt számok mohón összefűzve)."""
    out: list[AmountMatch] = []
    for m in _AMOUNT_RX.finditer(text):
        value = _decimal_from_number(m["num"])
        if value is None:
            continue
        neg = m["neg"] or ""
        if neg.startswith("(") and not m["close"]:
            neg = ""
        if neg:
            value = -value
        out.append(AmountMatch(value, m.start(), m.end()))
    return out


def parse_amount(s: str | None) -> Decimal | None:
    """Egy összeg szövegből (pénznem-jelekkel, tagolással); az utolsó összeg-jelölt számít,
    mert a címke után álló érték a sor végén van (`Total due $739.00`)."""
    if not s:
        return None
    s = s.replace("−", "-")
    trailing_minus = bool(re.search(r"\d\s?-\s*$", s))
    matches = find_amounts(s)
    if not matches:
        return None
    value = matches[-1].value
    return -abs(value) if trailing_minus else value


# --------------------------------------------------------------------------- adószám

EU_VAT_PREFIXES = (
    "AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK "
    "GB XI CH NO"
).split()

_TAX_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("hu_domestic", re.compile(r"(?<![\dA-Z])(\d{8})-(\d)-(\d{2})(?![\d])")),
    ("eu_vat", re.compile(rf"(?<![A-Z0-9])({'|'.join(EU_VAT_PREFIXES)})\s?([0-9A-Z]{{8,13}})(?![0-9A-Z])")),
    ("ein", re.compile(r"(?<![\d-])(\d{2})-(\d{7})(?![\d-])")),
]


@dataclass(frozen=True)
class TaxIdMatch:
    raw: str
    key: str
    kind: str  # hu_domestic | eu_vat | ein
    start: int
    end: int


def find_tax_ids(text: str) -> list[TaxIdMatch]:
    """Adószám-jelöltek pozícióval. Az EU VAT-nál legalább 6 számjegy kell (ne legyen szó, pl. `DEUTSCHLAND`)."""
    out: list[TaxIdMatch] = []
    for kind, rx in _TAX_PATTERNS:
        for m in rx.finditer(text):
            if kind == "eu_vat" and sum(c.isdigit() for c in m[2]) < 6:
                continue
            key = normalize_tax_id(m[0], kind_hint=kind)
            if key:
                out.append(TaxIdMatch(m[0], key, kind, m.start(), m.end()))
    out.sort(key=lambda t: t.start)
    return out


def normalize_tax_id(s: str | None, *, kind_hint: str | None = None) -> str | None:
    """Adószám → partnerkulcs. A magyar belföldi és közösségi adószám ugyanarra képződik (`HU` + 8 jegy)."""
    if not s:
        return None
    raw = s.strip().upper()
    if kind_hint is None:
        # Címkével együtt érkező érték (pl. `VAT No.: HU26481937`): a benne felismert adószám számít.
        found = find_tax_ids(raw)
        if found:
            return found[0].key
    if m := re.fullmatch(r"(\d{8})-?(\d)-?(\d{2})", raw.replace(" ", "")):
        return f"HU{m[1]}"
    if kind_hint == "ein" or re.fullmatch(r"\d{2}-\d{7}", raw):
        digits = re.sub(r"\D", "", raw)
        return f"US{digits}" if len(digits) == 9 else None
    compact = re.sub(r"[^0-9A-Z]", "", raw)
    if not compact:
        return None
    if compact[:2] in EU_VAT_PREFIXES and any(c.isdigit() for c in compact[2:]):
        if compact[:2] == "HU":
            return f"HU{compact[2:10]}" if re.fullmatch(r"HU\d{8}(\d{3})?", compact) else compact
        return compact
    return compact if any(c.isdigit() for c in compact) else None


def is_own_tax_id(key: str | None, own_tax_number: str, own_eu_vat: str) -> bool:
    if not key:
        return False
    return key in {normalize_tax_id(own_tax_number), normalize_tax_id(own_eu_vat)}


# --------------------------------------------------------------------------- számlaszám, cégnév

def normalize_invoice_number(s: str | None) -> str | None:
    if not s:
        return None
    norm = re.sub(r"[^A-Z0-9]", "", strip_accents(s).upper())
    return norm or None


_LEGAL_FORMS = [
    # többszavas formák előre (írásjelek nélküli, kisbetűs alakban)
    "sp z o o", "sp zoo", "s r l", "s l", "s a s", "s a", "s p a", "b v", "n v",
    "kft", "zrt", "nyrt", "bt", "kkt", "ev",
    "ltd", "limited", "inc", "llc", "corp", "corporation", "co", "plc", "llp",
    "gmbh", "kg", "ag", "ohg", "ug", "e k",
    "sarl", "sas", "sa", "sl", "slu", "srl", "spa", "snc", "bv", "nv", "oy", "ab", "as", "aps",
]
_LEGAL_RX = re.compile(r"(?:\s(?:" + "|".join(re.escape(f) for f in _LEGAL_FORMS) + r"))+$")


def normalize_company_name(s: str | None) -> str:
    """Tartalék partnerkulcshoz: kisbetű, ékezet és írásjel nélkül, a cégforma levágva."""
    if not s:
        return ""
    t = fold(s).replace("&", " ")
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = _LEGAL_RX.sub("", " " + t).strip()
    return t


# --------------------------------------------------------------------------- pénznem

# Az MNB által jegyzett devizák + HUF.
KNOWN_CURRENCIES = frozenset(
    "HUF EUR USD GBP PLN CHF CZK DKK NOK SEK RON BGN TRY JPY CNY AUD CAD HKD SGD NZD "
    "ILS INR KRW MXN MYR PHP THB ZAR RSD UAH BRL IDR ISK RUB".split()
)
_CURRENCY_SYMBOLS = {
    "ft": "HUF", "forint": "HUF", "huf": "HUF",
    "€": "EUR", "eur": "EUR", "euro": "EUR",
    "$": "USD", "us$": "USD", "usd": "USD",
    "£": "GBP", "gbp": "GBP",
    "zł": "PLN", "zl": "PLN", "pln": "PLN",
    "chf": "CHF", "kč": "CZK", "kc": "CZK",
}


def normalize_currency(s: str | None) -> str | None:
    """ISO-kód vagy szimbólum → ISO 4217 kód (csak ismert devizára)."""
    if not s:
        return None
    t = s.strip().rstrip(".").lower()
    if t in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[t]
    code = t.upper()
    return code if code in KNOWN_CURRENCIES else None


def find_currency(text: str) -> str | None:
    """Az első egyértelmű pénznem-jelölés a szövegben (ISO-kód, majd szimbólum)."""
    for m in re.finditer(r"(?<![A-Z])([A-Z]{3})(?![A-Z])", text):
        if m[1] in KNOWN_CURRENCIES:
            return m[1]
    for sym, code in (("€", "EUR"), ("£", "GBP"), ("zł", "PLN"), ("$", "USD")):
        if sym in text:
            return code
    if re.search(r"\d\s?Ft\b", text):
        return "HUF"
    return None
