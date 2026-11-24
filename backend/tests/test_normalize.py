from datetime import date
from decimal import Decimal

import pytest

from app.services.extraction.normalize import (
    find_amounts,
    find_currency,
    find_dates,
    find_tax_ids,
    fold,
    is_own_tax_id,
    normalize_company_name,
    normalize_currency,
    normalize_invoice_number,
    normalize_tax_id,
    parse_amount,
    parse_date,
)

# ----------------------------------------------------------------------------- szöveg


def test_fold_lowercases_strips_accents_and_joins_spaced_letters():
    assert fold("S Z Á M L A") == "szamla"
    assert fold("F A C T U R E") == "facture"
    assert fold("Fizetési  határidő ") == "fizetesi hatarido"
    assert fold("Wisła Spółka") == "wisla spolka"
    assert fold("Straße") == "strasse"


# ----------------------------------------------------------------------------- dátum


@pytest.mark.parametrize(
    "text, expected",
    [
        # magyar
        ("2026.03.15.", date(2026, 3, 15)),
        ("2026. 03. 15.", date(2026, 3, 15)),
        ("2026. június 24.", date(2026, 6, 24)),
        ("2026. szept. 8.", date(2026, 9, 8)),
        ("2025.12.31.", date(2025, 12, 31)),
        # ISO
        ("2026-11-13", date(2026, 11, 13)),
        # német / lengyel / olasz / spanyol numerikus
        ("15.03.2026", date(2026, 3, 15)),
        ("09.03.2026", date(2026, 3, 9)),
        ("04/03/2026", date(2026, 3, 4)),
        ("16-05-2026", date(2026, 5, 16)),
        # hónapnévvel
        ("10. März 2026", date(2026, 3, 10)),
        ("5. Jänner 2026", date(2026, 1, 5)),
        ("13 mars 2026", date(2026, 3, 13)),
        ("12 avril 2026", date(2026, 4, 12)),
        ("1 février 2026", date(2026, 2, 1)),
        ("1er février 2026", date(2026, 2, 1)),
        ("21st March 2026", date(2026, 3, 21)),
        ("16 de abril de 2026", date(2026, 4, 16)),
        ("4 marzo 2026", date(2026, 3, 4)),
        ("9 marca 2026", date(2026, 3, 9)),
        ("3 października 2026", date(2026, 10, 3)),
        ("30 January 2026", date(2026, 1, 30)),
        ("1 March 2026", date(2026, 3, 1)),
        ("February 1, 2026", date(2026, 2, 1)),
        ("Sept 3rd, 2026", date(2026, 9, 3)),
        ("Dec 24 2026", date(2026, 12, 24)),
    ],
)
def test_parse_date_formats(text, expected):
    assert parse_date(text) == expected


def test_parse_date_with_surrounding_label():
    assert parse_date("Fizetési határidő: 2026.01.13.") == date(2026, 1, 13)
    assert parse_date("Date d'échéance: 12 avril 2026") == date(2026, 4, 12)
    assert parse_date("Data scadenza: 19/03/2026") == date(2026, 3, 19)


def test_ambiguous_numeric_date_day_first_by_default():
    assert parse_date("04/03/2026") == date(2026, 3, 4)
    assert parse_date("04/03/2026", dayfirst=False) == date(2026, 4, 3)


def test_unambiguous_numeric_date_ignores_dayfirst():
    assert parse_date("03/15/2026") == date(2026, 3, 15)
    assert parse_date("15/03/2026", dayfirst=False) == date(2026, 3, 15)


@pytest.mark.parametrize("text", ["", None, "nincs dátum", "31.02.2026", "2026.13.01.", "Payment terms: net 30 days"])
def test_parse_date_invalid(text):
    assert parse_date(text) is None


def test_find_dates_two_column_header():
    # Kétoszlopos fejlécnél egy sorban több dátum is állhat.
    found = find_dates("NORDWIND SOLUTIONS KFT. 2026. június 24. 2026. július 2.")
    assert [d.value for d in found] == [date(2026, 6, 24), date(2026, 7, 2)]


def test_find_dates_does_not_read_invoice_numbers_as_dates():
    assert find_dates("Számlaszám: KT-2026/006") == []
    assert find_dates("FV/48/03/2026") == []


def test_month_abbreviation_must_be_unambiguous():
    # "ju" lehet június vagy július → nem dátum
    assert parse_date("3 ju 2026") is None
    assert parse_date("3 jun 2026") == date(2026, 6, 3)
    assert parse_date("3 jul 2026") == date(2026, 7, 3)


# ----------------------------------------------------------------------------- összeg


@pytest.mark.parametrize(
    "text, expected",
    [
        ("1 234,56", "1234.56"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1 648 156 Ft", "1648156"),
        ("1 648 156 Ft", "1648156"),
        ("1.493,78 €", "1493.78"),
        ("2 668,00 €", "2668.00"),
        ("£3,465.00", "3465.00"),
        ("$739.00", "739.00"),
        ("4 548,00 PLN", "4548.00"),
        ("1 109 472 HUF", "1109472"),
        ("320,00", "320.00"),
        ("1.234.567", "1234567"),
        ("1,234,567.89", "1234567.89"),
        ("0,500", "0.500"),
        ("12,5", "12.5"),
        ("1'234.50 CHF", "1234.50"),
        ("-1 234,00", "-1234.00"),
        ("(1 234,00)", "-1234.00"),
        ("1 234,00-", "-1234.00"),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == Decimal(expected)


def test_parse_amount_takes_value_after_label():
    assert parse_amount("Fizetendő összesen 1 648 156 Ft") == Decimal("1648156")
    assert parse_amount("ÁFA összesen (27%) 90 936 Ft") == Decimal("90936")
    assert parse_amount("Total due $739.00") == Decimal("739.00")
    assert parse_amount("Totale IVA (0%) 0,00 €") == Decimal("0.00")


def test_dash_separator_is_not_a_minus_sign():
    assert parse_amount("Közúti fuvarozás Budapest – 873 600") == Decimal("873600")
    assert parse_amount("KT-2026/006") == Decimal("6")  # nem negatív


def test_parse_amount_returns_decimal_not_float():
    value = parse_amount("1.493,78")
    assert isinstance(value, Decimal)


@pytest.mark.parametrize("text", ["", None, "nincs összeg", "€"])
def test_parse_amount_invalid(text):
    assert parse_amount(text) is None


def test_find_amounts_on_line_item():
    values = [a.value for a in find_amounts("908,00 908,00 27% 245,16 1 153,16")]
    assert values == [Decimal("908.00"), Decimal("908.00"), Decimal("27"), Decimal("245.16"), Decimal("1153.16")]


# ----------------------------------------------------------------------------- adószám


@pytest.mark.parametrize(
    "raw, key",
    [
        ("26481937-2-43", "HU26481937"),
        ("HU26481937", "HU26481937"),
        ("HU 26481937", "HU26481937"),
        ("21847502-1-42", "HU21847502"),
        ("ATU58392716", "ATU58392716"),
        ("ESB86473921", "ESB86473921"),
        ("FR47829461375", "FR47829461375"),
        ("GB284719356", "GB284719356"),
        ("IT09583720018", "IT09583720018"),
        ("PL5272846193", "PL5272846193"),
        ("84-3920175", "US843920175"),
        ("EIN 84-3920175", "US843920175"),
        ("VAT No.: HU26481937", "HU26481937"),
        ("Adószám: 14829375-2-43", "HU14829375"),
    ],
)
def test_normalize_tax_id(raw, key):
    assert normalize_tax_id(raw) == key


def test_domestic_and_eu_hungarian_tax_ids_share_key():
    assert normalize_tax_id("23918466-2-08") == normalize_tax_id("HU23918466")


@pytest.mark.parametrize("raw", ["", None, "n/a", "Budapest"])
def test_normalize_tax_id_invalid(raw):
    assert normalize_tax_id(raw) is None


def test_find_tax_ids_ignores_ibans_and_words():
    text = (
        "Adószám: 21847502-1-42 · Közösségi adószám: HU21847502\n"
        "IBAN: HU71 1091 8001 2184 7502 0000 0000 SWIFT/BIC: OTPVHUHB\n"
        "DEUTSCHLAND DE89370400440532013000 EIN 84-3920175"
    )
    found = find_tax_ids(text)
    assert [(t.key, t.kind) for t in found] == [
        ("HU21847502", "hu_domestic"),
        ("HU21847502", "eu_vat"),
        ("US843920175", "ein"),
    ]


def test_is_own_tax_id():
    assert is_own_tax_id("HU26481937", "26481937-2-43", "HU26481937")
    assert not is_own_tax_id("HU21847502", "26481937-2-43", "HU26481937")
    assert not is_own_tax_id(None, "26481937-2-43", "HU26481937")


# ----------------------------------------------------------------------------- számlaszám, cégnév, pénznem


@pytest.mark.parametrize(
    "raw, norm",
    [
        ("KT-2026/006", "KT2026006"),
        ("KT-2026-006", "KT2026006"),
        ("NWS/2026/0035", "NWS20260035"),
        ("FV/48/03/2026", "FV48032026"),
        (" inv-us 7782285 ", "INVUS7782285"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_invoice_number(raw, norm):
    assert normalize_invoice_number(raw) == norm


@pytest.mark.parametrize(
    "a, b",
    [
        ("Pannon Irodaszer Kft.", "PANNON IRODASZER KFT."),
        ("Nordwind Solutions Kft.", "NORDWIND SOLUTIONS KFT"),
        ("Wisła Software Sp. z o.o.", "WISŁA SOFTWARE SP. Z O.O."),
        ("Soluciones Ibéricas S.L.", "SOLUCIONES IBERICAS SL"),
        ("Officina Romano S.r.l.", "Officina Romano SRL"),
        ("Hoffmann & Söhne KG", "Hoffmann & Sohne"),
        ("Greenfield Analytics Ltd.", "GREENFIELD ANALYTICS LIMITED"),
    ],
)
def test_company_name_variants_normalize_equal(a, b):
    assert normalize_company_name(a) == normalize_company_name(b)
    assert normalize_company_name(a)


def test_company_name_keeps_distinguishing_words():
    assert normalize_company_name("Kovács és Társa Könyvelőiroda Bt.") == "kovacs es tarsa konyveloiroda"
    assert normalize_company_name("Duna Logisztika Zrt.") != normalize_company_name("Duna Trans Zrt.")


@pytest.mark.parametrize(
    "raw, code",
    [("HUF", "HUF"), ("Ft", "HUF"), ("eur", "EUR"), ("€", "EUR"), ("$", "USD"), ("£", "GBP"), ("zł", "PLN"),
     ("CHF", "CHF"), ("JPY", "JPY"), ("XYZ", None), ("", None)],
)
def test_normalize_currency(raw, code):
    assert normalize_currency(raw) == code


def test_find_currency():
    assert find_currency("Pénznem: HUF") == "HUF"
    assert find_currency("Net à payer TTC 2 668,00 €") == "EUR"
    assert find_currency("Fizetendő összesen 657 352 Ft") == "HUF"
    assert find_currency("Total due £3,465.00") == "GBP"
    assert find_currency("FATTURA TOTALE") is None
