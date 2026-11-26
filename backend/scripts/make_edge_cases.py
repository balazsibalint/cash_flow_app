"""Szintetikus próbacsomag a robusztusság ellenőrzéséhez és a bemutatóhoz.

Hibás és szokatlan fájlokat állít elő (sérült, szöveg nélküli, jelszavas, idegen, jóváíró, díjbekérő, negatív
végösszegű, hiányos dátumú, jövőbeli teljesítésű számla, nem PDF, üres fájl). Mindegyikhez megadja a várt
eredményt; a `tests/test_edge_cases.py` ugyanezt a csomagot futtatja le a teljes HTTP-folyamaton.

A saját cég adatai a konfigurációból (`OWN_*`) jönnek. A dátumok a futtatás napjához igazodnak
(a jövőbeli teljesítés így mindig ideiglenes árfolyamot kap).

Futtatás (a fájlok a backend/edge_cases/ mappába kerülnek):
    docker compose -f docker-compose.dev.yml run --rm app python -m scripts.make_edge_cases edge_cases
"""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from app.config import get_settings
from tests.helpers import make_pdf


@dataclass(frozen=True)
class EdgeCase:
    filename: str
    description: str
    data: bytes
    # Ha a szerver már a feltöltést elutasítja: a HTTP-státusz; különben a számla várt státusza.
    http_status: int | None = None
    status: str | None = None
    provisional: bool = False
    warnings: tuple[str, ...] = ()


def _d(value: date) -> str:
    return value.strftime("%Y.%m.%d.")


def _invoice(number: str, *, title: str | None = None, seller: str = "Minta Szolgaltato Kft.",
             seller_tax: str = "12345678-2-42", buyer: str | None = None, buyer_tax: str | None = None,
             issue: date | None = None, supply: date | None = None, due: date | None = None,
             terms: str | None = None, currency: str = "HUF", total: str = "127 000 Ft",
             user_password: str | None = None) -> bytes:
    """Egyszerű, címkés elrendezésű számla. Csak Latin-1 betűk (a beépített betűkészlet miatt: „Vevő” → „Bill to”)."""
    s = get_settings()
    items = [] if title is None else [(40, 16, title)]
    items += [
        (40, 40, seller), (40, 54, f"Adószám: {seller_tax}"),
        (40, 90, "Bill to"), (40, 104, buyer or s.own_company_name), (40, 118, f"Adószám: {buyer_tax or s.own_tax_number}"),
        (300, 90, f"Számlaszám: {number}"),
    ]
    rows = [("Kiállítás dátuma", issue), ("Teljesítés dátuma", supply), ("Due date", due)]
    top = 104
    for label, value in rows:
        if value is not None:
            items.append((300, top, f"{label}: {_d(value)}"))
            top += 14
    if terms:
        items.append((300, top, f"Fizetési feltétel: {terms}"))
        top += 14
    items += [(300, top, f"Pénznem: {currency}"), (300, 300, "Total due"), (480, 300, total)]
    return make_pdf(items, user_password=user_password)


def build_cases(today: date | None = None) -> list[EdgeCase]:
    today = today or date.today()
    issue = today - timedelta(days=20)
    ok = dict(issue=issue, supply=issue - timedelta(days=2), due=issue + timedelta(days=30))
    valid = _invoice("EC-2026/01", **ok)
    return [
        EdgeCase("01_serult.pdf", "Félbevágott PDF (hiányzik a vége)", valid[: len(valid) // 2], status="error"),
        EdgeCase("02_szoveg_nelkul.pdf", "Csak rajz, nincs kinyerhető szöveg (mint egy szkennelt kép)",
                 make_pdf(None, draw_only=True), status="error"),
        EdgeCase("03_jelszavas.pdf", "Megnyitási jelszóval titkosított PDF",
                 _invoice("EC-2026/03", user_password="titok", **ok), status="error"),
        EdgeCase("04_idegen_szamla.pdf", "A saját cég egyik oldalon sem szerepel (K7)",
                 _invoice("EC-2026/04", buyer="Harmadik Fel Zrt.", buyer_tax="11111111-2-41", **ok), status="rejected"),
        EdgeCase("05_jovairo.pdf", "Jóváíró számla (K7)",
                 _invoice("EC-2026/05", title="JÓVÁÍRÓ SZÁMLA", **ok), status="rejected"),
        EdgeCase("06_proforma.pdf", "Proforma / díjbekérő (K7)",
                 _invoice("EC-2026/06", title="PROFORMA INVOICE", **ok), status="rejected"),
        EdgeCase("07_negativ_vegosszeg.pdf", "Negatív végösszeg (K7)",
                 _invoice("EC-2026/07", total="-127 000 Ft", **ok), status="rejected"),
        EdgeCase("08_hianyzo_datumok.pdf", "Nincs teljesítés és határidő, csak fizetési feltétel (K6)",
                 _invoice("EC-2026/08", issue=issue, terms="15 nap"), status="ok",
                 warnings=("INFERRED_SUPPLY", "INFERRED_DUE")),
        EdgeCase("09_hianyzo_hatarido.pdf", "Nincs határidő és fizetési feltétel sem (K5: ellenőrzendő)",
                 _invoice("EC-2026/09", issue=issue, supply=issue), status="review"),
        EdgeCase("10_jovobeli_teljesites.pdf", "A teljesítés a jövőben van: ideiglenes árfolyam (K8)",
                 _invoice("EC-2026/10", issue=today, supply=today + timedelta(days=10), due=today + timedelta(days=30),
                          currency="EUR", total="1 000,00 EUR"),
                 status="ok", provisional=True),
        EdgeCase("11_nem_pdf.pdf", "Szövegfájl .pdf kiterjesztéssel", b"Ez nem PDF, csak egy szovegfajl.\n", http_status=400),
        EdgeCase("12_ures.pdf", "Üres (0 bájtos) fájl", b"", http_status=400),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", type=Path, help="Ide kerülnek a fájlok (létrejön, ha nincs).")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for case in build_cases():
        (args.out_dir / case.filename).write_bytes(case.data)
        expected = f"HTTP {case.http_status}" if case.http_status else case.status + (" (ideiglenes)" if case.provisional else "")
        print(f"{case.filename:28} → {expected:18} {case.description}")


if __name__ == "__main__":
    main()
