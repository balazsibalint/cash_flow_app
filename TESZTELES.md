# Tesztelési útmutató

## Előfeltételek

- A Docker Desktop fut, és a projekt gyökerében van `.env` fájl (`cp .env.example .env`).
- Minden parancsot a projekt gyökeréből kell futtatni. A tesztek a fejlesztői konténerben futnak.
- A tesztek **nem érintik** a futó alkalmazást (http://localhost:8080): ideiglenes adatbázist használnak.
- Valódi MNB- vagy LLM-hívást sem indítanak: az MNB-t rögzített válaszok és hamisított szolgáltatás, az LLM-et mock
  helyettesíti.

## Gyors parancsok

```bash
# Az összes teszt (337 db, ~45 mp)
docker compose -f docker-compose.dev.yml run --rm app pytest -q

# Tesztenként, névvel és PASSED/FAILED jelzéssel (bemutatóhoz)
docker compose -f docker-compose.dev.yml run --rm app pytest -v

# Szűrés névrészletre, pl.
docker compose -f docker-compose.dev.yml run --rm app pytest -v -k "weekend or holiday"

# Csak a tesztek listája, futtatás nélkül
docker compose -f docker-compose.dev.yml run --rm app pytest --collect-only -q
```

A tesztfájlok helye: [backend/tests/](backend/tests/).

## 1. Adatkinyerés (241 teszt)

```bash
docker compose -f docker-compose.dev.yml run --rm app pytest -v tests/test_normalize.py tests/test_layout.py tests/test_doctype.py tests/test_extraction.py tests/test_validate.py tests/test_pipeline.py tests/test_llm.py
```

| Fájl | Mit ellenőriz | Jellemző esetek |
|---|---|---|
| `test_normalize.py` (115) | Dátumok, összegek, adószámok, számlaszámok, cégnevek és pénznemek értelmezése | `2026. szept. 8.`, `10. März 2026`, `16 de abril de 2026`, `Sept 3rd, 2026` → dátum; `1.234,56`, `£3,465.00`, `(1 234,00)` → `Decimal`; `26481937-2-43` és `HU26481937` → ugyanaz a kulcs; érvénytelen dátum (`31.02.2026`) → nincs találat |
| `test_layout.py` (11) | Címke → érték keresés az elrendezésben | Érték a címke mellett vagy az oszlopában alatta; kétnyelvű címke; a távoli vagy más oszlopban lévő érték nem kerül be |
| `test_doctype.py` (18) | Különleges bizonylatok felismerése a fejlécből | Jóváíró, sztornó, proforma, előleg 7 nyelven, ritkított írással is (`J Ó V Á Í R Ó`); a tételsorban szereplő „sztornó” szó **nem** okoz elutasítást |
| `test_extraction.py` (39) | Kinyerés valódi PDF-eken | A 15 minta-PDF minden kötelező mezője megvan, és nettó + ÁFA = bruttó; mezőnkénti összevetés a kézzel készített `expected.json`-nal; a nyomtatott forintos ÁFA nem lesz végösszeg; ismeretlen elrendezésű (német, CHF) szintetikus számla; sérült, szöveg nélküli és jelszavas PDF |
| `test_validate.py` (22) | Validációs szabályok és K6-következtetés | Hiányzó mező, összeg-eltérés (HUF-nál 1 Ft tűrés), dátumsorrend, a saját cég mindkét oldalon vagy egyiken sem, negatív végösszeg; teljesítés ← kiállítás, határidő ← kiállítás + fizetési feltétel |
| `test_pipeline.py` (25) | A teljes kinyerési lánc hamis LLM-mel | Jó szabályalapú eredménynél **nincs** LLM-hívás (15 minta); hiányzó határidőt az LLM pótol; hallucinált vagy hibás LLM-válasz → ellenőrzendő; jóváíró és idegen számla LLM nélkül elutasítva |
| `test_llm.py` (11) | Az LLM-kliens mockolt HTTP-vel | Sémás válasz; tartalék formátum; egy újrapróba hálózati hibánál; a kulcs nem kerül hibaüzenetbe; napi limit; horgonyzás (a forrásszövegben nem szereplő érték elvetése) |

## 2. Árfolyam-kiválasztás és átváltás (30 teszt)

```bash
docker compose -f docker-compose.dev.yml run --rm app pytest -v tests/test_mnb.py tests/test_fx.py
```

| Fájl | Mit ellenőriz | Jellemző esetek |
|---|---|---|
| `test_mnb.py` (22) | MNB-válasz feldolgozása, árfolyam-kiválasztás, gyorsítótár | **Valódi, rögzített MNB-válasz** (2026. március) feldolgozása, a hétvégén nincs jegyzés. Kiválasztás: jegyzési nap → aznapi; vasárnap → pénteki; húsvéti ünnepsor → az előtte lévő utolsó; hónap eleje → előző hónap vége. `unit=100` (JPY); HUF → nincs lekérés. Jövőbeli vagy mai, még nem jegyzett nap → ideiglenes; nem jegyzett deviza → hiba; elérhetetlen MNB → `MnbUnavailable`. Gyorsítótár: ismételt kérésnél nincs új hívás, csak a hiányzó hónap kérődik le, egy nap/deviza sosem kétszer, a „ma” csak másnap kérődik újra |
| `test_fx.py` (8) | Forintra váltás és kerekítés | `1153,16 EUR × 396,92` = 457 712 Ft; `x,5` → felfelé, `x,4999` → lefelé (`ROUND_HALF_UP`); `unit=100`; `float` bemenet → hiba |

## 3. Aggregálás (14 teszt)

```bash
docker compose -f docker-compose.dev.yml run --rm app pytest -v tests/test_report.py tests/test_partners.py "tests/test_api.py::test_all_fixture_invoices_are_processed_and_reported"
```

| Fájl | Mit ellenőriz | Jellemző esetek |
|---|---|---|
| `test_report.py` (6) | Havi és partnerenkénti összesítés | A hónapok folytonosak, a kimaradt hónap 0, évváltáson át is; **csak az `ok` számlák** számítanak bele (az ideiglenes igen; a review, pending_fx, rejected és error nem, és a hónapjuk sem jelenik meg); partnerek forgalom szerint csökkenő sorrendben; az `ok` számla nélküli partner nem jelenik meg; üres adatbázis |
| `test_partners.py` (7) | Partnerazonosítás (a partnertábla alapja) | A belföldi és az EU-s adószám egy partnert ad; a név szerinti partner összevonása az adószámossal; megjelenített név = a leggyakoribb írásmód |
| `test_api.py::test_all_fixture_…` (1) | Végponttól végpontig | A 15 minta-PDF feltöltése HTTP-n át; a havi, a partnerenkénti és az összesített forintösszeg pontosan egyezik a számlák összegével; az MNB-lekérésekben egy nap sem ismétlődik; az újrafeltöltés 15 duplikátumot ad |

## Egyéb tesztek (röviden)

```bash
docker compose -f docker-compose.dev.yml run --rm app pytest -v tests/test_api.py tests/test_edge_cases.py
```

- **`test_api.py` (24):** a teljes HTTP-folyamat.
  - Feltöltés és duplikáció (hash, valamint kiállító + számlaszám).
  - Hibás fájlok: nem PDF → 400, túl nagy fájl → 413; a sérült fájl és egy váratlan kivétel sem állítja le az appot.
  - MNB-kiesés → „Árfolyamra vár”, majd újrapróbálás (K9); az ideiglenes árfolyam véglegesítése (K8).
  - Törlés; párhuzamos feltöltés.
- **`test_edge_cases.py` (13):** a 12 fájlos próbacsomag (sérült, jelszavas, jóváíró, idegen, hiányos dátumú, jövőbeli
  teljesítésű számla stb.), mindegyik a várt státusszal.

### Élő bemutató a próbacsomaggal

```bash
docker compose -f docker-compose.dev.yml run --rm app python -m scripts.make_edge_cases edge_cases
```

1. A parancs a `backend/edge_cases/` mappába írja a fájlokat, és mindegyik mellé kiírja a várt eredményt.
2. A mappát húzd be a http://localhost:8080 feltöltő paneljére, és vesd össze az eredményeket a várttal.
3. Utána futtasd le a `pytest -v tests/test_edge_cases.py` parancsot: ugyanezeket az eseteket automatikusan is
   ellenőrzi.

A dátumok a generálás napjához igazodnak, ezért a demó napján generáld újra a fájlokat. Bekapcsolt LLM mellett a
`09_hianyzo_hatarido.pdf` egy LLM-hívást indít.