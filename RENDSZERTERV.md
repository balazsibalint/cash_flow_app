# Implementációs terv – Számlafeldolgozó és cash-flow kimutatás

> Forrás: [FELADAT.md](FELADAT.md) + a [TERV-KERDESEK.md](TERV-KERDESEK.md)-ben meghozott döntések (K1–K16).
> Ez a dokumentum a megvalósítás **kötelező referenciája**: ha a fejlesztés közben valamitől el kell térni,
> előbb ezt a fájlt kell frissíteni, és az eltérést jelezni.

---

## 1. Döntések összefoglalója

| # | Téma | Döntés |
|---|---|---|
| K1 | Kinyerési stratégia | **Szabályalapú elsődleges**, LLM csak tartalék, ha a validáció elbukik |
| K2 | LLM-modell | `google/gemini-3.5-flash-lite` (OpenRouter), env-ből felülírható – az eredeti `google/gemini-2.5-flash` helyett, a 4. lépés után |
| K3 | LLM-kliens | **Egyetlen OpenAI-kompatibilis kliens**, átállítható base URL (OpenRouter élesben, Gemini OpenAI-kompatibilis végpontja fejlesztéshez) |
| K4 | Duplikáció | Fájl-hash gyorsszűrő + **kiállító adószám-kulcs + normalizált számlaszám**; ütközéskor **kihagyás** „már feldolgozva” jelzéssel |
| K5 | Bizonytalan számla | „**Ellenőrzendő**” státusz, látszik a listában, **nem számít bele** a kimutatásba |
| K6 | Hiányzó dátumok | Nincs teljesítés → a kiállítás dátuma, figyelmeztetéssel. Nincs határidő → kiállítás + fizetési feltétel (N nap), figyelmeztetéssel; ha feltétel sincs → ellenőrzendő |
| K7 | Különleges bizonylatok | Jóváíró, sztornó, helyesbítő, díjbekérő, proforma, előleg → **elutasítva**, sehova nem számít bele. A mi cégünk egyik félként sem szerepel → **elutasítva**. Egyéb deviza → általánosan lekérjük az MNB-től (`unit` figyelembevételével) |
| K8 | Jövőbeli vagy még nem jegyzett nap | A legutolsó ismert árfolyam, **„ideiglenes”** jelöléssel; később automatikusan újraszámoljuk |
| K9 | Nem elérhető MNB | „**Árfolyamra vár**” státusz; a **következő feltöltés** újrapróbálja |
| K10 | Feltöltés | A frontend **fájlonként** küld kérést, 4 párhuzamos kéréssel, élő haladásjelzővel |
| K11 | Eredeti PDF | **Tároljuk** a volume-ban (megnyitható, újrafeldolgozható) |
| K12 | Törlés | **Egyenkénti** és **összes törlése**, mindkettő megerősítéssel |
| K13 | Partner neve, oszlopsorrend | A leggyakoribb írásmód (a változatok tooltipben); az oszlopok **teljes forgalom szerint csökkenő** sorrendben |
| K14 | Teszt-PDF-ek | **10–15 reprezentatív PDF** a `backend/tests/pdfs/` alatt; az `expected.json`-t **a felhasználó készíti kézzel** |
| K15 | Felület | Magyar nyelv, világos téma, magyar számformátum |
| K16 | Git, szabályok | A fő ág `master`; `CLAUDE.md` szabályfájl; `ai-logs/` egyelőre nem kell |

Technikai alapdöntések: SQLite + SQLAlchemy (`create_all`, Alembic nélkül), `Decimal` minden pénzösszegre,
`ROUND_HALF_UP` kerekítés, Recharts. Az irányt az adószám dönti el; a partnerkulcs a normalizált adószám.
A számlán feltüntetett saját árfolyamot vagy forintos ÁFA-összeget nem használjuk.

---

## 2. Rendszerarchitektúra

```
┌──────────────────────────── Böngésző ─────────────────────────────┐
│ React 19 + TypeScript + Tailwind 4 + Recharts                      │
│ UploadPanel → CashflowChart → PartnerTable → InvoiceTable          │
└───────────────┬────────────────────────────────────────────────────┘
                │ HTTP JSON (azonos origin, :8080)
┌───────────────▼──────────── app konténer (python:3.12-slim) ──────┐
│ FastAPI                                                            │
│  /api/invoices  /api/report  /api/health    + statikus frontend /  │
│        │                                                           │
│  services/ingest.py  ── feltöltés-orkesztráció (hash, dedup, mentés)│
│        ├── pdf_text.py          (pdfplumber: szöveg + szavak)       │
│        ├── extraction/pipeline  (doctype → rules → validate → llm)  │
│        ├── mnb.py + fx.py       (árfolyam, átváltás)                │
│        └── partners.py          (partner-összevonás)                │
│  services/report.py ── aggregáció                                  │
│        │                                                           │
│  SQLite  /app/data/app.db      PDF-ek  /app/data/pdfs/<sha256>.pdf │
└───────────────┬──────────────────────────────┬─────────────────────┘
                │ SOAP (http)                  │ HTTPS (csak tartalékként)
        www.mnb.hu/arfolyamok.asmx      openrouter.ai/api/v1
```

- **Éles:** a gyökérkönyvtári `Dockerfile` (többlépcsős build) és a `docker-compose.yml` → `http://localhost:8080`.
- **Fejlesztés:** `docker-compose.dev.yml` (külön projektnév) → backend `:8000` `--reload`-dal, Vite `:5173` proxyval.
- **Perzisztencia:** a `sqlite_data` named volume tartalmazza az adatbázist és a PDF-eket is.

### 2.1 Könyvtárstruktúra

```
backend/
  app/
    main.py                  FastAPI app, routerek, statikus mount (a routerek UTÁN)
    config.py                Settings (pydantic-settings)
    db.py                    engine, SessionLocal, init_db()
    models.py                SQLAlchemy ORM modellek
    schemas.py               Pydantic I/O sémák + ExtractedInvoice
    api/
      deps.py                függőségek (DB-session, IngestService-példány, PDF-mappa) – a tesztek felülírják
      invoices.py            feltöltés, lista, PDF letöltés, törlés
      report.py              diagram + partnertábla
    services/
      ingest.py              egy fájl teljes feldolgozása (orkesztráció), újrapróbálás (6.5), törlés (K12)
      pdf_text.py            PdfDocument: oldalak, szavak, sorok
      partners.py            partnerkulcs, megjelenített név
      mnb.py                 SOAP-kliens, cache, árfolyam-kiválasztás
      fx.py                  átváltás és kerekítés
      report.py              aggregáció
      extraction/
        normalize.py         dátum, szám, adószám, számlaszám, pénznem
        labels.py            többnyelvű címke- és kulcsszószótár
        layout.py            sorok építése, címke→érték keresés koordinátákkal
        doctype.py           különleges bizonylatok felismerése (K7)
        rules.py             szabályalapú kinyerő
        validate.py          validátorok → hibák és figyelmeztetések
        llm.py               OpenAI-kompatibilis kliens, prompt, séma
        pipeline.py          a lépések összekötése
  tests/
    conftest.py
    pdfs/                    10–15 reprezentatív PDF (K14)
    expected.json            a felhasználó által kézzel készített referencia
    mnb/                     rögzített SOAP-válaszok
    test_normalize.py  test_layout.py  test_doctype.py  test_extraction.py
    test_validate.py   test_llm.py     test_mnb.py      test_fx.py
    test_report.py     test_api.py     test_partners.py   test_edge_cases.py
  scripts/
    dump_extraction.py       egy mappa PDF-jeinek kinyert mezői (kézi ellenőrzés, LLM nélkül)
    make_edge_cases.py       szintetikus próbacsomag hibás és szokatlan fájlokból, a várt eredménnyel (8. lépés)
frontend/src/
  api.ts  types.ts  format.ts  labels.ts (státusz-, irány- és bizonylatfeliratok)
  components/ UploadPanel.tsx CashflowChart.tsx PartnerTable.tsx InvoiceTable.tsx ConfirmDialog.tsx
  App.tsx
```

> ⚠ A `.gitignore` minden `invoices/` nevű mappát kizár, ezért a teszt-PDF-ek mappáját **nem** szabad `invoices`-nak nevezni.

---

## 3. Konfiguráció (`.env`)

| Változó | Alapérték | Leírás |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | `openrouter` (éles/kiértékelés) · `gemini` (fejlesztés, saját kulccsal) · `none` (LLM kikapcsolva) |
| `OPENROUTER_API_KEY` | *(üres)* | Ha a kiválasztott szolgáltató kulcsa üres, az LLM-tartalék ki van kapcsolva, és az app csak szabályalapon működik |
| `OPENROUTER_MODEL` | `google/gemini-3.5-flash-lite` | K2 |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | |
| `GEMINI_API_KEY` | *(üres)* | Csak fejlesztéshez (CLAUDE.md 2. szabály) |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | A `gemini-2.5-flash` a fejlesztői kulccsal 404-et adott (4. lépés), ezért cseréltük |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` | A Gemini OpenAI-kompatibilis végpontja |
| `LLM_TIMEOUT_SECONDS` | `60` | |
| `LLM_MAX_CONCURRENCY` | `2` | Egyszerre futó LLM-hívások száma |
| `LLM_MAX_CALLS_PER_DAY` | `200` | Költségvédelem (az `llm_calls` tábla alapján) |
| `MAX_UPLOAD_MB` | `20` | |
| `DATABASE_URL` | `sqlite:///./data/app.db` | |
| `DATA_DIR` | `./data` | Ide kerülnek a PDF-ek (`pdfs/`) |
| `MNB_URL` | `http://www.mnb.hu/arfolyamok.asmx` | |
| `MNB_TIMEOUT_SECONDS` | `20` | |
| `OWN_COMPANY_NAME` / `OWN_TAX_NUMBER` / `OWN_EU_VAT` | Nordwind adatai | Az irány eldöntéséhez |

K3 szerint **egyetlen OpenAI-kompatibilis kliens** van: a `LLM_PROVIDER` csak azt választja ki, melyik
(base URL, kulcs, modell) hármast kapja – külön szolgáltató-implementáció nincs. Az üres env-értékek az alapértéket
kapják (`env_ignore_empty`). A `LLM_MAX_CALLS_PER_BATCH` megszűnik (fájlonkénti feltöltésnél nincs „köteg”),
helyette `LLM_MAX_CALLS_PER_DAY` van.

---

## 4. Adatmodell

### 4.1 `invoices`

| Mező | Típus | Megjegyzés |
|---|---|---|
| `id` | int PK | |
| `file_sha256` | str(64) **UNIQUE** | gyorsszűrő (K4) |
| `filename` | str | csak megjelenítésre |
| `status` | enum | `ok` · `review` (ellenőrzendő) · `pending_fx` (árfolyamra vár) · `rejected` (elutasítva) · `error` (feldolgozhatatlan) |
| `status_reason` | str? | ember által olvasható ok (magyarul) |
| `messages` | JSON | figyelmeztetések és hibák listája: `{code, level, text}` |
| `extraction_method` | enum? | `rule` · `llm` |
| `doc_type` | str? | pl. `invoice`, `credit_note`, `proforma` (a K7-hez) |
| `invoice_number` | str? | ahogy a számlán áll |
| `invoice_number_norm` | str? | nagybetűs, `[^A-Z0-9]` nélkül |
| `seller_name`, `seller_tax` | str? | |
| `buyer_name`, `buyer_tax` | str? | |
| `seller_tax_key` | str? | normalizált (lásd 5.4) |
| `issue_date`, `supply_date`, `due_date` | date? | |
| `supply_date_inferred`, `due_date_inferred` | bool | K6-figyelmeztetés |
| `currency` | str(3)? | ISO 4217 |
| `net_amount`, `vat_amount`, `gross_amount` | Decimal? | **TEXT-ként tárolt Decimal** (saját `DecimalText` típus): az SQLite `NUMERIC` affinitása float-tá alakítana, ami pontosságvesztés |
| `direction` | enum? | `incoming` · `outgoing` |
| `partner_id` | FK → partners? | |
| `fx_rate` | Decimal? (TEXT) | HUF esetén 1 |
| `fx_unit` | int? | |
| `fx_rate_date` | date? | a ténylegesen felhasznált jegyzés napja |
| `fx_provisional` | bool | K8 |
| `gross_huf` | int? | számlánként kerekítve |
| `raw_text` | text | újrafeldolgozáshoz és hibakereséshez |
| `created_at`, `updated_at` | datetime | |

Egyedi index: **`UNIQUE(seller_tax_key, invoice_number_norm)`**, ahol mindkettő nem NULL (SQLite partial index).
Az `error` és a `rejected` sorokat is elmentjük, hogy ugyanaz a fájl ne fusson újra (LLM-költség). Az `error` sorokat a
lista mutatja; a `rejected` bizonylatok a felületen csak a feltöltési naplóban jelennek meg (a számlalistában és a
„Figyelmet igényel” csempében nem), az „Összes törlése” azonban őket is törli.

### 4.2 `partners`

| Mező | Típus | Megjegyzés |
|---|---|---|
| `id` | int PK | |
| `tax_key` | str **UNIQUE** | pl. `HU23918466`, `GB284719356`, `US843920175`; adószám hiányában `NAME:<normalizált név>` |
| `display_name` | str | a leggyakoribb írásmód (K13), minden mentéskor újraszámolva |
| `aliases` | JSON | `{név: előfordulás}` |

### 4.3 `exchange_rates` és `mnb_fetches`

| Tábla | Mezők |
|---|---|
| `exchange_rates` | `(date, currency)` PK, `rate` Decimal (TEXT), `unit` int, `fetched_at` |
| `mnb_fetches` | `id`, `currency`, `start_date`, `end_date`, `fetched_at` – a már lekérdezett intervallumok, beleértve a jegyzés nélküli napokat is |

### 4.4 `llm_calls`

`id`, `file_sha256`, `model`, `started_at`, `duration_ms`, `success`, `prompt_tokens`, `completion_tokens`, `error`.
A napi limit és a README-ben leírt költségbecslés alapja.

---

## 5. Feldolgozási folyamat (egy fájl)

```
POST /api/invoices (1 fájl)
 1. Méret- és típusellenőrzés: ≤ MAX_UPLOAD_MB, „%PDF-” fejléc         ─ hiba → 400 (nem mentjük)
 2. sha256 → létezik?  ─ igen → {result: "duplicate", invoice}         (K4 gyorsszűrő)
 3. PDF mentése: data/pdfs/<sha>.pdf
 4. Szövegkinyerés (pdf_text)        ─ kivétel / üres szöveg → status=error
 5. Bizonylattípus (doctype)         ─ különleges → status=rejected   (K7)
 6. Szabályalapú kinyerés (rules)
 7. Validáció (validate)
      ├─ nincs hiba → tovább a 9. lépésre
      └─ van hiba → 8.
 8. LLM-tartalék (ha engedélyezett és van keret)
      → validáció; ha jó → method=llm; ha nem → status=review (a hibákkal)
 9. Saját cég ellenőrzése: egyik fél sem mi → status=rejected          (K7)
10. Dedup-kulcs (seller_tax_key + invoice_number_norm) ütközik?
      ─ igen → a PDF-et töröljük, a sort nem mentjük, {result: "duplicate"}  (K4/A)
11. Partner hozzárendelése / létrehozása
12. Árfolyam (MNB) + átváltás         ─ MNB nem elérhető → status=pending_fx (K9)
13. Mentés, válasz: {result: "created", invoice}
Minden kérés elején: pending_fx és fx_provisional számlák újrapróbálása (K8, K9)
```

A teljes folyamat egy `try/except` alatt fut: bármilyen váratlan kivétel `status=error`-t és naplóbejegyzést eredményez.
Az alkalmazás nem áll le, és a következő fájl feldolgozása is folytatódik.

### 5.1 PDF-szöveg (`pdf_text.py`)

- `PdfDocument.pages[i].words`: a `pdfplumber` `extract_words(keep_blank_chars=False, x_tolerance=1.5, y_tolerance=3)` eredménye (`text, x0, x1, top, bottom`).
- `lines`: a szavak `top` szerint, ±3 pt toleranciával csoportosítva, majd `x0` szerint rendezve. Minden sor megkapja az oldalszámot és a globális sorindexet (a többoldalas számlák összefűzéséhez).
- `full_text`: az oldalak `extract_text()` eredménye összefűzve (a doctype, a kulcsszavak és az LLM használja).
- Olvasási hibák (mind `status=error`, magyar üzenettel): sérült vagy csonka fájl; **megnyitási jelszóval titkosított**
  PDF (`PDFPasswordIncorrect`, külön üzenettel – 8. lépés); szöveg nélküli PDF. A csak tulajdonosi jelszavas
  (jogosultság-korlátozott) PDF olvasható.
- **Egymásra nyomtatott szöveg** (a 2. lépésben derült ki, `NWS/2026/0044`): a nagy betűs „Fizetendő összesen / Total due”
  címke és a „8 743,00 GBP” érték ugyanarra a sávra esik, ezért az x szerint rendezett szöveg összekeveri őket
  („Tota8l d7u4e3,00”). Kezelés: a szavakat a PDF-tartalomfolyam sorrendjében is előállítjuk (`use_text_flow=True`),
  és ha egy sorban betűk és számjegyek keverednek egy szón belül, ezt a változatot használjuk; a végösszeget emellett
  a fejlécben lévő ismételt „Total due” érték és a nettó + ÁFA ellenőrzés is megerősíti.

### 5.2 Bizonylattípus-felismerés (`doctype.py`, K7)

Szótáras keresés a dokumentum **címében és fejlécében** (az első oldal felső ~35%-a), hogy egy tételsorban szereplő szó
(pl. „előleg-beszámítás”) ne okozzon téves elutasítást:

| Típus | Kulcsszavak (példák) |
|---|---|
| jóváíró / sztornó / helyesbítő | jóváíró, sztornó, helyesbítő számla, credit note, Gutschrift, Stornorechnung, avoir, facture d'avoir, nota de crédito, factura rectificativa, nota di credito, faktura korygująca, korekta |
| díjbekérő / proforma | díjbekérő, proforma, pro forma, Proforma-Rechnung, facture pro forma, factura proforma, fattura proforma, faktura proforma |
| előlegszámla | előlegszámla, advance invoice, Anzahlungsrechnung, Vorauszahlungsrechnung, facture d'acompte, factura de anticipo, fattura d'acconto, faktura zaliczkowa |

Emellett a **negatív bruttó végösszeg** a kinyerés után szintén `rejected` státuszt eredményez (jóváíró jelleg).

### 5.3 Szabályalapú kinyerés (`labels.py`, `layout.py`, `rules.py`)

**Címkeszótár** (`labels.py`): mezőnként nyelvenkénti címkelista, kis- és nagybetűtől, ékezettől és ritkított írástól
(`S Z Á M L A`) függetlenül illesztve:

| Mező | Példák |
|---|---|
| `invoice_number` | Számlaszám, Invoice No., Invoice number, Rechnungsnummer, N° de facture, Nº de factura, Fattura n., Numer faktury |
| `issue_date` | Kiállítás dátuma, Invoice date, Rechnungsdatum, Date de facture, Fecha de emisión, Data fattura, Data wystawienia |
| `supply_date` | Teljesítés dátuma, Date of supply, Leistungsdatum, Date de prestation, Fecha de operación, Data prestazione, Data sprzedaży |
| `due_date` | Fizetési határidő, Due date, Zahlbar bis, Date d'échéance, Fecha de vencimiento, Data scadenza, Termin płatności |
| `currency` | Pénznem, Currency, Währung, Devise, Moneda, Valuta, Waluta |
| `gross` (prioritási sorrendben) | Fizetendő összesen, Total due, Amount due, Rechnungsbetrag, Net à payer TTC, TOTAL A PAGAR, Totale documento, Do zapłaty, Bruttó összesen, Total |
| `net` | Nettó összesen, Subtotal, Summe netto, Total HT, Base imponible total, Totale imponibile, Razem netto |
| `vat` | ÁFA összesen, VAT total, Umsatzsteuer, Total TVA, Total IVA, Totale IVA, Razem VAT |
| `buyer_block` | Vevő, Bill to, Rechnungsempfänger, Facturé à, Cliente, Cessionario / Committente, Nabywca |
| `payment_terms` | Fizetési feltétel, Payment terms, Zahlungsziel, Conditions de paiement, Condiciones de pago, Pagamento, Termin płatności: N dni |
| `exclude_amount` | forintban, in HUF, ÁFA összege, VAT amount – ilyen sorból nem választunk végösszeget |

**Címke→érték keresés** (`layout.py`, megvalósítva a 3. lépésben):
1. A sorokat **szegmensekre** bontjuk (a betűméretnél nagyobb vízszintes rés = új szegmens, pl. bal és jobb oszlop).
   Címke csak a szegmens elején vagy `/` után állhat (kétnyelvű „Kiállítás dátuma / Invoice date”), így a mondatba ágyazott szó nem címke.
2. **Ugyanabban a sorban:** a címke utáni szöveg a szegmensen belül, majd a következő szegmens – az első, amelyet a típusos `parser` elfogad.
3. Ha a címke után nincs számjegy: a **legközelebbi (≤ 30 pt) sor, amelynek szavai a címke oszlopába esnek** (kétoszlopos fejléc).
   Csak ez az egy sor számít, mert a távolabbiak már más mezőhöz (pl. tételsorhoz) tartoznak. Az egymás alatti címkéket
   (*Kiállítás dátuma* / *Fizetési határidő*) a sorrendi párosítás helyett az oszlop szerinti illesztés kezeli: a mintákban ezek eltérő x-pozíción állnak.
4. Több találatnál: dátumnál és számlaszámnál az első; összegeknél a nettó + ÁFA = bruttó egyezést adó jelölt, ennek híján a leggyakoribb
   (holtversenynél a későbbi, mert a többoldalas számla összesítője a végén van).
5. A címkeszótárban szándékosan **nincsenek oszlopfejlécek** (Nettó érték, Net amount, Wartość brutto, IVA, TVA, Imposta …),
   mert alattuk tételsor áll.
- **Vevő-címkék két szinten:** erős (Vevő, Bill to, Rechnungsempfänger, Facturé à, Cliente, Cessionario, Nabywca …) és gyenge
  (Customer, Client, Kunde) – a gyengét csak erős hiányában használjuk, és ha utána „No./ID/#” áll, nem vevőblokk.

**Felek és adószámok:**
- Minden adószám-jelöltet kigyűjtünk pozícióval együtt: magyar `\d{8}-\d-\d{2}`, EU VAT `[A-Z]{2}[0-9A-Z]{8,12}` (ismert országkódokkal),
  `EIN \d{2}-\d{7}`, lengyel NIP `\d{10}`.
- A **vevőblokk** a buyer-címke alatti terület, a címke x-pozíciójától a következő oszlopkezdetig, a következő üres sávig vagy a táblázatfejlécig.
- A **kiállítóblokk** a dokumentum teteje a vevőblokk előtt (a jobb oldali „SZÁMLA / INVOICE” címet kizárva), illetve tartalékként a lábléc cégsora.
- A saját cég ott van, ahol a `26481937` törzs vagy a saját név előfordul. **Kimenő**, ha a kiállítóblokkban, **bejövő**, ha a vevőblokkban.
- A partner neve a másik blokk első, nem címke sora; az adószáma a másik blokk adószám-jelöltjei közül a legerősebb (EU VAT > belföldi > egyéb).

**Pénznem:** címke → ISO-kód; ennek híján a végösszeg melletti szimbólum (`Ft`→HUF, `€`→EUR, `$`→USD, `£`→GBP, `zł`→PLN), illetve a szövegben talált 3 betűs ISO-kód.

### 5.4 Normalizálók (`normalize.py`)

| Függvény | Szabály |
|---|---|
| `parse_date(s)` | Formátumok: `YYYY.MM.DD.`, `YYYY. <hónapnév> D.`, `DD.MM.YYYY`, `DD/MM/YYYY`, `D. <Monat> YYYY`, `D <mois> YYYY`, `<Month> D, YYYY`, `D <Month> YYYY`, ISO. A hónapnév-szótár 7 nyelven, ékezettel és anélkül. A `DD/MM` és `MM/DD` kétértelműséget a nyelv dönti el: `MM/DD` csak angol, amerikai kontextusban. |
| `parse_amount(s)` | Pénznem-szimbólumok és szóközök (NBSP is) eltávolítása. Ha `,` és `.` is szerepel, **az utolsó a tizedesjel**. Ha csak egyféle van, és utána pontosan 3 jegy áll, akkor ezres elválasztó, különben tizedesjel. Kimenet: `Decimal`. A negatív előjelet (`-`, `( )`) megőrzi. |
| `normalize_tax_id(s)` | Magyar `12345678-1-42` → `HU12345678`; `HU12345678` → `HU12345678`; egyéb EU VAT → nagybetűs, elválasztók nélkül; EIN → `US` + 9 jegy. |
| `normalize_invoice_number(s)` | Nagybetű, `[^A-Z0-9]` törlése (`KT-2026/006` → `KT2026006`). |
| `normalize_company_name(s)` | Kisbetű, ékezet nélkül, cégforma-utótagok (Kft., Zrt., Bt., Ltd., Inc., GmbH, KG, SARL, S.L., S.r.l., Sp. z o.o. …) és írásjelek nélkül (tartalék partnerkulcshoz). |

### 5.5 Validáció (`validate.py`)

| Kód | Szint | Feltétel |
|---|---|---|
| `MISSING_FIELD` | hiba | Hiányzik a számlaszám, a kiállítás dátuma, a pénznem vagy a bruttó összeg, illetve a partner adószáma és neve is |
| `MISSING_DUE` | hiba | Nincs határidő, és fizetési feltételből sem számítható (K6) |
| `INFERRED_SUPPLY` / `INFERRED_DUE` | figyelmeztetés | K6-következtetés történt |
| `UNKNOWN_CURRENCY` | hiba | Nem ISO 4217 kód |
| `SUM_MISMATCH` | hiba | nettó + ÁFA ≠ bruttó (tűrés: 0,01 × pénznem-pontosság), ha mindhárom megvan |
| `LINES_MISMATCH` | figyelmeztetés | A tételsorok összege ≠ nettó (ha a tételsorok kinyerhetők) |
| `DATE_ORDER` | hiba | határidő < kiállítás, vagy a teljesítés több mint 1 évvel eltér a kiállítástól |
| `OWN_COMPANY_SIDE` | hiba | A mi cégünk mindkét oldalon, vagy egyik oldalon sem szerepel |
| `NEGATIVE_TOTAL` | elutasítás | A bruttó < 0 (K7) |

A hibák az LLM-tartalékot indítják; ha az LLM után is maradnak, a számla `review` státuszt kap.

**Megvalósítás (4. lépés) – kiegészítések:**
- A `SUM_MISMATCH` tűrése HUF-nál 1 Ft (egész forintra kerekített ÁFA), más devizánál 0,01.
- Az LLM-hívás **előtt** elutasítjuk (K7) a különleges bizonylatot és azt a dokumentumot, amelyen a cégünk
  (adószám vagy név) **egyáltalán nem szerepel** – ezekre LLM-et hívni felesleges költség lenne.
  Ha a cégünk szerepel, de az oldala nem állapítható meg, az `OWN_COMPANY_SIDE` hiba → LLM / `review`.
- Ha az LLM-eredmény is elbukik, a kevesebb hibát tartalmazó változat marad (döntetlennél a szabályalapú),
  és az `LLM_FAILED` üzenet az LLM-eredmény hibáit is felsorolja.
- További üzenetkódok: `LLM_DISABLED` (info), `LLM_FAILED` (figyelmeztetés), `LLM_UNGROUNDED` (hiba),
  `LLM_USED` (info – miért kellett az LLM), `LLM_DISAGREES` (figyelmeztetés), `REJECTED`.
- Az irány-meghatározás egyetlen függvényben van (`validate.direction_of`); a `rules.determine_direction` ezt hívja.

### 5.6 LLM-tartalék (`llm.py`)

- **Kliens:** `httpx` POST a `{OPENROUTER_BASE_URL}/chat/completions` végpontra (OpenAI-formátum), `temperature: 0`,
  `response_format: {type: "json_schema", …}`; ha a modell ezt nem támogatja, `json_object`-re váltunk.
- **Bemenet:** a `full_text` (oldaljelzésekkel), a saját cég adatai, és a szabályalapú részeredmény a hibakódokkal
  („ezek a mezők hiányoznak vagy ellentmondásosak”). **A PDF-et nem küldjük el**, csak a szöveget.
- **Kimeneti séma:** `invoice_number, seller{name,tax_id}, buyer{name,tax_id}, issue_date, supply_date, due_date (ISO),
  currency (ISO 4217), net_total, vat_total, gross_total (string számként), document_type, payment_terms_days`.
- **A válasz ellenőrzése:**
  1. Pydantic-sémavalidáció;
  2. **Horgonyzás:** a számlaszámnak és a bruttó összegnek (normalizált formában) szerepelnie kell a forrásszövegben,
     különben a válasz hallucinációnak minősül;
  3. ugyanazok a validátorok, mint a szabályalapú eredményre (összegegyezés, dátumsorrend, saját cég);
  4. ahol a szabályalapú és az LLM-érték is megvan és eltér, figyelmeztetést rögzítünk.
- **Takarékosság:** csak validációs hibánál hívjuk; fájl-hash szerint egyszer (a már feldolgozott fájl duplikátumként áll meg);
  napi limit (`LLM_MAX_CALLS_PER_DAY`), párhuzamossági korlát (`LLM_MAX_CONCURRENCY`), timeout, legfeljebb 1 újrapróba hálózati hibánál.
  Kulcs nélkül az LLM ki van kapcsolva, és a számla `review` státuszt kap.
- **A kulcs soha nem kerül naplóba.**

**Megvalósítás (4. lépés) – eltérések és részletek:**
- A modellnek a `layout_text`-et küldjük (a rekonstruált sorok, oldaljelzéssel) a `full_text` helyett, mert az egymásra
  nyomtatott szövegnél (`NWS/2026/0044`) a `full_text` olvashatatlan; legfeljebb 20 000 karakter.
- A horgonyzás a `full_text` és a `layout_text` együttesén történik.
- Az LLM-eredmény hiányzó mezőit a szabályalapú eredményből pótoljuk, és az LLM `document_type`-ja is elutasíthat (K7).
- Költségkeret és napló: `services/llm_budget.py` (`DbLlmBudget`, `llm_calls` tábla); a kliens csak egy
  `try_acquire()/record()` interfészt ismer, így a kinyerés DB nélkül tesztelhető.

### 5.7 Partnerek (`partners.py`)

- A partnerkulcs a partner normalizált adószáma (5.4). A magyar belföldi és közösségi adószám **ugyanarra a kulcsra** képződik (`HU` + 8 jegy).
- Adószám hiányában a kulcs `NAME:<normalized name>`. Mentéskor, ha később adószámos változat érkezik ugyanazzal a normalizált névvel, összevonjuk őket.
- A `display_name` az `aliases` leggyakoribb eleme; holtversenynél a legkorábbi.

---

## 6. MNB-árfolyam (`mnb.py`, `fx.py`)

### 6.1 Kliens
- `POST {MNB_URL}`, `Content-Type: text/xml; charset=utf-8`, `SOAPAction: "http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"`.
- A válaszból kivesszük a `GetExchangeRatesResult` szöveget (`xml.etree`), amelyet **másodszor is XML-ként** elemzünk:
  `Day@date` → `Rate@curr`, `Rate@unit`, és a vesszős érték → `Decimal`.

### 6.2 Lekérés és gyorsítótár
- `ensure_rates(currency, need_from, need_to)`: kiszámolja, hogy a `[need_from, need_to]` intervallum mely részeit nem fedik le
  az `mnb_fetches` sorok, és **csak ezeket** kéri le, majd a jegyzéseket upsertáli az `exchange_rates` táblába, az intervallumot pedig rögzíti.
- Egy számlánál a szükséges intervallum `[supply_date − 10 nap, min(supply_date, ma)]`. Ha ebben nincs jegyzés
  (pl. hosszú ünnepi időszak), 30 napra bővítjük.
- A mai napot (és a jövőt) tartalmazó intervallum **nem számít véglegesen lefedettnek**, mert később még jöhet jegyzés.
  Ezért a mai napra szóló `mnb_fetches` bejegyzést naponta legfeljebb egyszer frissítjük.
- Egy napot vagy devizát tehát soha nem kérdezünk le kétszer, kivéve a „ma” egyszeri napi frissítését.

### 6.3 Kiválasztás
`select_rate(currency, supply_date)` → a `date ≤ supply_date` feltételű legkésőbbi jegyzés.
- `HUF` → `rate=1, unit=1, rate_date=supply_date`.
- Ha `supply_date > a legutolsó jegyzés napja`, és a `supply_date ≥ ma` → `fx_provisional=True` (K8).
- Hálózati vagy SOAP-hiba → `MnbUnavailable` → a számla `status=pending_fx` (K9).

### 6.3.1 Megvalósítás (5. lépés) – részletek és eltérések
- A lekérést **hónapra kerekítjük**: `[hónap eleje(teljesítés − 10 nap), hónap vége(teljesítés)]`, a mai napnál levágva.
  Így egy év számláihoz devizánként kb. 12 SOAP-hívás kell, nem számlánként egy; a lefedett időszakokat az
  `mnb_fetches` alapján kivonjuk, ezért egy nap/deviza sosem kerül kétszer lekérésre (teszt: `test_no_day_currency_is_requested_twice`).
- „Ma” kezelése: ha egy lekérés a lekérés napját is tartalmazta, az a nap csak aznap számít lefedettnek, másnap újra lekérjük
  (a jegyzés napközben jelenik meg). A napot UTC szerint számoljuk (az éjfél körüli 1–2 órás eltérés elhanyagolható).
- Ha a 10 napos visszatekintésben nincs jegyzés, 40 napra bővítünk; ha így sincs, `MnbNoRate` (az MNB nem jegyzi a devizát).
- Ideiglenes (K8): ha `teljesítés ≥ ma`, és a talált jegyzés korábbi a teljesítésnél.
- **Valódi ellenőrzés:** EUR 2026-03-09 → 396,92 (egyezik a nyers MNB-válasszal), vasárnap 2026-03-08 → péntek 03-06 jegyzése.
  Az `NW-2026-0014` számlára nyomtatott 396,92-es árfolyam tehát **helyes MNB-árfolyam** – a 0. fejezetben „csapdának” jelölt
  adatból valójában csak a forintos ÁFA-összeg (97 309 Ft) veszélyes, mert az nem a végösszeg. Ettől függetlenül
  mindig a lekért MNB-árfolyamot használjuk.
- Valódi MNB-válasz teszt-fixture-ként: `backend/tests/mnb/rates_2026_03.xml`.

### 6.4 Átváltás
`gross_huf = (gross_amount × rate / unit).quantize(Decimal("1"), ROUND_HALF_UP)` → int. Az összesítés ezután történik.

### 6.5 Újrapróbálás (K8, K9)
Minden `POST /api/invoices` elején (folyamaton belüli zárral, legfeljebb percenként egyszer):
- a `pending_fx` számlákra újra lefut a 6.2–6.4 lépés, siker esetén `status=ok`;
- az `fx_provisional` számláknál, ha a teljesítés napja már elmúlt, és van rá jegyzés, újraszámolunk, és levesszük a jelölést.

---

## 7. Aggregáció (`report.py`)

- **Bemenet:** csak az `ok` státuszú számlák. Az ideiglenes árfolyamú számlák beleszámítanak, de a listában jelölve vannak.
  A `review`, `pending_fx`, `rejected` és `error` számlák **nem** számítanak bele.
- **Diagram:** `due_date` → `YYYY-MM`. A hónaplista a legkorábbi és a legkésőbbi hónap között **folytonos**; a hiányzó hónap értéke 0.
  Elemek: `{month, incoming_huf, outgoing_huf}`.
- **Partnertábla:** `{partner_id, name, aliases[], incoming_huf, outgoing_huf}`, rendezve `incoming + outgoing` szerint csökkenően (K13).
- **Összesítők** a felülethez: darabszám státuszonként, összes bejövő és kimenő.

---

## 8. REST API

| Metódus | Útvonal | Leírás | Válasz |
|---|---|---|---|
| `GET` | `/api/health` | | `{status: "ok", llm_enabled: bool}` |
| `POST` | `/api/invoices` | multipart, **1 fájl** (`file`) | `200 {result: "created"\|"duplicate"\|"rejected"\|"review"\|"error", message, invoice}` · `400` nem PDF vagy túl nagy · `413` |
| `GET` | `/api/invoices` | minden számla, a legújabb elöl | `InvoiceOut[]` |
| `GET` | `/api/invoices/{id}/pdf` | az eredeti PDF | `application/pdf` (inline) |
| `DELETE` | `/api/invoices/{id}` | egy számla és a PDF-je; a partner is törlődik, ha árva lett | `204` |
| `DELETE` | `/api/invoices` | **összes törlése**; az árfolyam-cache megmarad | `204` |
| `GET` | `/api/report` | | `{months: [...], partners: [...], totals: {...}, counts: {...}}` |

Az `InvoiceOut` a 4.1 összes megjelenítendő mezőjét tartalmazza; a pénzösszegeket **stringként** adja vissza
(a Decimal pontossága miatt), a `gross_huf`-ot egész számként.
A statikus mount (`/`) a routerek **után** kerül regisztrálásra.

### 8.1 Megvalósítás (6. lépés) – részletek és eltérések

- **Feltöltés-ellenőrzés:** üres vagy `%PDF-` fejléc nélküli fájl (az első 1024 bájtban) → `400`; `MAX_UPLOAD_MB` felett → `413`. Ezeket nem mentjük.
- **Eredmény-típusok:** a `pending_fx` számla `result: "created"` (a státusz és az üzenet jelzi, hogy árfolyamra vár).
  Ha az MNB nem jegyzi a devizát (`MnbNoRate`), a számla `review` státuszt kap (`FX_NO_RATE`), mert nem váltható át.
- **Dedup** minden státuszra érvényes, amelynél a kiállító adószáma és a számlaszám ismert (az `error`/`rejected` sor is
  foglalja a kulcsot, hogy ugyanaz ne fusson újra). Kihagyáskor a már elmentett PDF-et töröljük.
- **Árfolyam csak `ok` számlához:** a `review` számla adatai bizonytalanok, ezért nem kérdezzük le hozzá az MNB-t.
- **Párhuzamosság (K10, 4 kérés):** az első valódi 100 fájlos próbán két, ugyanattól az új partnertől érkező számla
  egyszerre próbálta létrehozni a partnert (`UNIQUE constraint failed: partners.tax_key`, 1 hibás feltöltés).
  Javítás: a dedup-ellenőrzés + partner + beszúrás egy folyamaton belüli zár alatt fut, az MNB-lekérés viszont előtte
  (a lassú hívás ne sorosítson); több folyamat esetére a UNIQUE-index + egy újrapróba véd.
- **Újrapróbálás (6.5):** az első MNB-hiba után a kör megáll (nem kérdezzük számlánként a kieső szolgáltatást).
  Az ideiglenes árfolyamú számlánál a jelölés akkor kerül le, amikor a teljesítés napjára már van jegyzés.
- **Partnerek:** az adószám nélküli számla a név alapján kerül a partnerhez (`NAME:<név>`), vagy ahhoz az adószámos
  partnerhez, amelynek egyik névváltozata ugyanerre normalizálódik. Ha se adószám, se név: „Ismeretlen partner”.
  A névváltozatokat és a megjelenített nevet mentéskor és törléskor a partner számláiból számoljuk újra.
  Holtversenynél a legkorábban rögzített változat nyer – párhuzamos feltöltésnél ez a beérkezés sorrendjétől függ.
- **Riport:** a partnertáblában csak az a partner szerepel, akinek van `ok` számlája; a `counts` a státuszokon kívül
  `total` és `provisional` (ideiglenes árfolyamú `ok` számlák) értéket is ad.
- **Valódi ellenőrzés (LLM kikapcsolva):** a 100 fájl curl-lel, 4 párhuzamos kéréssel 18 mp alatt → 100 `ok`;
  újrafeltöltés 7 mp → 100 `duplicate`. 12 partner, 23 MNB SOAP-hívás 4 devizára, átfedő nap nélkül; 0 LLM-hívás.

---

## 9. Frontend

| Komponens | Tartalom |
|---|---|
| `UploadPanel` | Drag & drop és tallózás (`multiple`, `accept=application/pdf`). Feltöltési sor: **4 párhuzamos** kérés (K10). Fájlonkénti sor ikonnal: ⏳ / ✓ új / ↺ már feldolgozva / ⚠ ellenőrzendő / ⛔ elutasítva / ✗ hiba, az üzenettel. Összesítő sáv és haladásjelző. A köteg végén a riport és a lista újratöltődik. |
| `CashflowChart` | Recharts `LineChart`: X = `YYYY-MM`, Y = HUF; két vonal (bejövő, kimenő), eltérő színnel; `Legend`, tengelyfeliratok („Fizetési határidő (hónap)”, „Bruttó összeg (Ft)”), tooltip `1 234 567 Ft` formátumban, Y-tengelyen rövidített értékek (`1,2 M`). |
| `PartnerTable` | Transzponált tábla: oszlopok = partnerek (forgalom szerint), sorok = Össz bejövő / Össz kimenő; rögzített első oszlop, vízszintes görgetés, a (levágott) teljes név a `title` tooltipben – a névváltozatokat nem jelenítjük meg –, a `0` értékek halványítva. |
| `InvoiceTable` | Oszlopok: státusz, irány, számlaszám, partner, kiállító (név, adószám), vevő (név, adószám), kiállítás, teljesítés, határidő, eredeti összeg és pénznem, árfolyam (unit), árfolyam dátuma (+ „ideiglenes” jelvény), HUF-összeg, kinyerési mód (szabály/LLM), üzenetek. Szűrés státuszra, irányra, partnerre; rendezés oszlopfejlécre. Soronként PDF-megnyitás és törlés; a sorra bárhol kattintva nyílnak le a részletek. Az elutasított bizonylatok nem szerepelnek benne. Lapozás (10 / 25 / 50 / 100 sor oldalanként, alapértelmezés 10); a lista magassága az aktuális oldal sorait követi (a nem teli utolsó oldal alacsonyabb), belső görgetés nélkül. |
| `ConfirmDialog` | Törlés-megerősítés (egyenkénti és összes, K12). |

Formázás (`format.ts`): `Intl.NumberFormat('hu-HU')` (szóközös ezres tagolás), a dátum `YYYY.MM.DD.`, a devizaösszeg a pénznem tizedesjegyeivel.
Az oldal sorrendje: fejléc → feltöltés → diagram → partnertábla → számlalista (FELADAT 5.).

### 9.1 Megvalósítás (7. lépés) – részletek és eltérések

- **Új függőség:** `recharts@3.10.1` és a peer-függősége, `react-is@19.3.1` (pontos verzióval). A legfrissebb kiadás (3.11.1)
  3 napos volt, ezért a júliusi stabil verziót választottuk. A bundle így ~627 kB (gzip ~185 kB); a Vite 500 kB-os
  figyelmeztetése egy helyi alkalmazásnál elfogadható.
- **Feltöltés:** legfeljebb 4 worker veszi ki a fájlokat a sorból (K10). A kimutatás 20 fájlonként és a köteg végén frissül.
  A nem PDF kiterjesztésű/típusú fájlt a böngésző fel sem küldi; a méret- és tartalomellenőrzés a szerveren történik.
  A napló szűrhető a problémás fájlokra (ellenőrzendő, elutasított, hibás).
- **Összesítő csempék** a diagram fölött: össz bejövő, össz kimenő, a kimutatásba számító számlák (és az ideiglenes
  árfolyamúak), valamint a figyelmet igénylők száma (ellenőrzendő + árfolyamra vár + hibás; az elutasítottak nem),
  státuszonkénti bontás nélkül.
- **Diagram:** a két sorozat színe a validált referencia-paletta első két helye (kék `#2a78d6` bejövő, narancs `#eb6834`
  kimenő; színtévesztés-szimulációval ellenőrizve). 2 px-es vonalak, pontjelölők, vízszintes rácsvonalak, crosshair és
  tooltip. A vonalvégi névfelirat elmarad, ha a két végpont a skála 8%-ánál közelebb van egymáshoz (különben egymásra
  csúsznának); a jelmagyarázat mindig látszik. (A korábbi „Táblázat” nézetet felhasználói kérésre elhagytuk; a havi
  értékek a tooltipben olvashatók.)
- **Számlalista:** szabad szöveges keresés (számlaszám, név, adószám, fájlnév) a státusz-, irány- és partnerszűrő mellett;
  a sor kibontva a fájlnevet, a nettó/ÁFA összeget, a státusz okát és az összes üzenetet mutatja.
  A kikövetkeztetett dátumokat `*` jelzi (K6).
- **Felhasználói kérésre módosítva (a 7. lépés után):** az elutasított bizonylatok kikerültek a számlalistából, a
  státuszszűrőből és a „Figyelmet igényel” csempéből; a kibontott sorból a bizonylattípus, a partnertábla fejlécéből az
  „n névváltozat” felirat, és a fejléc tooltipje is csak a teljes nevet mutatja (a változatokat nem). A „Kimutatásban”
  csempe alsó sora csak az ideiglenes árfolyamú számlák számát mutatja (ha van ilyen). A számlalista lapozó alatta
  (10/25/50/100, alapértelmezés 10); a doboz magassága az aktuális oldal sorait követi, belső görgetés nélkül (a nem
  teli utolsó oldalon csak a maradék sorok férnek el). A sorra bárhol kattintva lenyílnak a részletek (a PDF-link, a
  Törlés gomb és a szövegkijelölés kivétel). Szűrés, rendezés és oldalméret-váltás az első oldalra ugrik; ha törlés után
  az aktuális oldal megszűnik, az utolsó létező oldal látszik. A diagramról lekerült a „Táblázat” nézet, a fejlécből az
  „LLM-tartalék: …” jelzés (az `llm_enabled` mező a `/api/health` válaszában megmaradt).
- **Hibajavítás a böngészős ellenőrzésből:** a táblák görgethető keretei `relative` osztályt kaptak. Nélküle a
  fejléc `sr-only` (abszolút pozíciójú) felirata kiszökött a keretből, és vízszintes görgetést okozott az egész oldalon.
- A sérült PDF hibaüzenete csak magyar szöveget tartalmaz; a pdfminer angol technikai üzenete a naplóba kerül.
- **Ellenőrzés (LLM kikapcsolva):** a böngészőből feltöltött 100 fájl 16 mp alatt 100 új számla; oldal-újratöltés után
  minden megmaradt; a 99 meglévő újrafeltöltése 99 „már feldolgozva”; egy nem PDF, egy sérült és egy 21 MB-os fájl a
  saját hibaüzenetével jelent meg; egyenkénti törlés a megerősítő ablakkal.

---

## 10. Tesztelés

### 10.1 Fixture-PDF-ek (K14/B) – javasolt válogatás

| Fájl (a csomagból) | Mit fed le |
|---|---|
| `szamla_KT-2026-006.pdf` | magyar, címke: érték elrendezés, **2025-ös teljesítés** |
| `szamla_PI-26-0023.pdf` | **kétoldalas**, a végösszeg a 2. oldalon; kétoszlopos fejléc; csak közösségi adószám |
| `szamla_DL-2026-00014.pdf` | „ERP-nyomtatvány” stílus, `DL/2026/00014` |
| `invoice_GA-10404.pdf` | angol, GBP, kétoszlopos, `30 January 2026` |
| `invoice_INV-US-7782285.pdf` | USD, `February 1, 2026`, EIN |
| `facture_F2026-0147.pdf` | francia, `13 mars 2026`, `2 668,00` |
| `Rechnung_2026-0584.pdf` | német (osztrák), `10. März 2026` |
| `factura_FAC-2026-0219.pdf` | spanyol, kétoszlopos, `1.493,78` |
| `fattura_127-2026.pdf` | olasz, bejövő |
| `faktura_FV-48-03-2026.pdf` | lengyel, PLN, `FV/48/03/2026` |
| `056_NW-2026-0014.pdf` | **kimenő**, kétnyelvű, **csapda: saját árfolyam és forintos ÁFA** |
| `szamla_NWS-2026-0035.pdf` | kimenő, kétoszlopos NWS-sablon |
| `scan_20260304_1148.pdf` | kimenő, olasz nyelvű, megtévesztő fájlnév |
| `invoice_NW-2026-0004.pdf` | kimenő, angol |
| `szamla_NWS-2026-0044.pdf` | kimenő, kétnyelvű kétoszlopos, **egymásra nyomtatott végösszeg** (3. lépésben hozzáadva) |

A debug szkript (`backend/scripts/dump_extraction.py`) mind a 100 számla kinyert mezőit kilistázza, és az
`expected.json` formátumában is ki tudja írni – kiindulásnak, de az értékeket kézzel kell ellenőrizni.

### 10.2 Az `expected.json` formátuma (a felhasználó tölti ki kézzel)

```json
{
  "szamla_KT-2026-006.pdf": {
    "invoice_number": "KT-2026/006",
    "seller_name": "Kovács és Társa Könyvelőiroda Bt.",
    "seller_tax": "21847502-1-42",
    "buyer_name": "Nordwind Solutions Kft.",
    "buyer_tax": "26481937-2-43",
    "issue_date": "2026-01-05",
    "supply_date": "2025-12-31",
    "due_date": "2026-01-13",
    "currency": "HUF",
    "gross_amount": "427736.00",
    "direction": "incoming"
  }
}
```
Az összehasonlítás normalizált formában történik (adószám → `tax_key`, számlaszám → `invoice_number_norm`, nevek → `normalize_company_name`).
**Az `expected.json` értékei mérvadók: a kódot kell a referenciához igazítani, a referenciát soha nem a kódhoz.**

### 10.3 Tesztfájlok

| Fájl | Tartalom |
|---|---|
| `test_normalize.py` | dátumok 7 nyelven, számformátumok (`1 234,56`, `1.234,56`, `1,234.56`, `3,465.00`, `1 648 156`), adószám- és számlaszám-normalizálás |
| `test_layout.py` | címke→érték azonos sorban és oszlopban alatta; több címke egymás alatt, sorrendi párosítással |
| `test_doctype.py` | jóváíró, proforma és előleg felismerése több nyelven; a tételsorban szereplő kulcsszó **nem** okoz elutasítást |
| `test_extraction.py` | paraméterezett teszt az `expected.json` minden bejegyzésére (ha a fájl még nincs meg, `skip`) |
| `test_validate.py` | minden validációs kód |
| `test_llm.py` | `httpx.MockTransport`: sémahiba, horgonyzási hiba, sikeres válasz, kulcs nélküli mód, napi limit – **valódi LLM-hívás nélkül** |
| `test_pipeline.py` | a teljes folyamat hamis LLM-mel: a fixture-ökön nincs LLM-hívás; tartalék-ág, hallucináció, elutasítások, K6-következtetés |

> A szintetikus PDF-ek a reportlab beépített Helvetica betűtípusával készülnek, amely nem tud `ő`/`ű` betűt –
> ezekben a tesztekben ezért angol címkék szerepelnek; a magyar címkéket a valódi fixture-PDF-ek fedik le.
| `test_mnb.py` | rögzített SOAP-válasz feldolgozása; hétvége és ünnepnap → előző jegyzés; `unit=100`; a cache miatt nincs második HTTP-hívás; részleges lefedettség esetén csak a hiányzó intervallum kérődik le; hiba → `MnbUnavailable` |
| `test_fx.py` | kerekítés: `x,5` → felfelé, `x,4999` → lefelé; HUF-számla |
| `test_report.py` | folytonos hónapok 0-val; partner-összevonás belföldi és EU adószámmal; rendezés; csak `ok` státusz számít |
| `test_api.py` | feltöltés → created; ugyanaz újra → duplicate (hash), más fájl ugyanazzal a kulccsal → duplicate; nem PDF → 400; sérült PDF → error, az app tovább fut; törlés egyenként és összesen; MNB-kiesés → pending_fx és újrapróbálás; ideiglenes árfolyam véglegesítése; párhuzamos feltöltés; a 15 fixture végig a riportig |
| `test_partners.py` | belföldi és EU-adószám → egy kulcs; saját kulcs kizárása; név szerinti partner összevonása az adószámossal; megjelenített név (K13); árva partner törlése |
| `test_edge_cases.py` | a `scripts/make_edge_cases.py` próbacsomagja végig a HTTP-folyamaton: sérült, szöveg nélküli, jelszavas PDF → `error`; idegen, jóváíró, proforma, negatív végösszeg → `rejected`; K6-következtetés → `ok` figyelmeztetéssel; határidő nélkül → `review`; jövőbeli teljesítés → ideiglenes; nem PDF és üres fájl → 400; a csomag után a riportban csak az `ok` számlák |

A szintetikus teszt-PDF-ek (jóváíró, ismeretlen elrendezés, hiányzó határidő) a tesztben generálódnak a `reportlab` dev-függőséggel
(`requirements-dev.txt`), így nem kell őket a repóban tárolni.

Futtatás: `docker compose -f docker-compose.dev.yml run --rm app pytest -q`.

---

## 11. Megvalósítási lépések

Minden lépés végén: a tesztek zöldek, `docker compose up --build` indul, és egy kis, beszédes commit készül (a felhasználó kérésére).

| # | Lépés | Elfogadási feltétel |
|---|---|---|
| 1 | **Alapok:** `config.py`, `db.py`, `models.py`, `schemas.py`; `.env.example` frissítése (K3); `requirements-dev.txt` | Az app indul, és létrejönnek a táblák a volume-ban |
| 2 | **Normalizálók** + `test_normalize.py` | A normalizáló tesztek zöldek |
| 3 | **PDF-szöveg + layout + címkeszótár + szabályalapú kinyerő + doctype** + tesztek | A fixture-ökön a mezők helyesek (`expected.json`, amint a felhasználó elkészíti); egy debug szkripttel a 100 számla összes mezője kilistázható kézi ellenőrzéshez |
| 4 | **Validáció + LLM-tartalék** + tesztek (mockolt) | A szabályalapú kinyerés a 100 számlán LLM nélkül is validál, vagy dokumentált, hogy hol nem |
| 5 | **MNB-kliens + cache + kiválasztás + fx** + tesztek | Egy valódi lekérés kézi ellenőrzése (pl. EUR 2026-03-09 → MNB-weboldal), a tesztek zöldek |
| 6 | **Ingest + API** (feltöltés, dedup, státuszok, törlés, PDF) + **report** + tesztek | A 100 fájl feltöltése curl-lel → 100 sor, újrafeltöltéskor 100 duplikátum |
| 7 | **Frontend:** feltöltő panel → diagram → partnertábla → számlalista | A teljes csomag feltöltése a böngészőből, majd frissítés után minden megmarad |
| 8 | **Robusztusság:** szintetikus és hibás fájlok, K6/K7/K8/K9 élesben; **README.md** | Egy sérült, egy idegen és egy jóváíró fájl helyes státusszal jelenik meg |

### 11.1 Megvalósítás (8. lépés) – részletek

- **Próbacsomag:** `backend/scripts/make_edge_cases.py` 12 szintetikus fájlt állít elő a várt eredménnyel (a saját cég
  adatai a konfigurációból, a dátumok a futtatás napjához igazodnak). A kimenet (`backend/edge_cases/`) a `.gitignore`-ban
  és a `.dockerignore`-ban van. Ugyanezt a csomagot futtatja a `tests/test_edge_cases.py`.
- **Új kezelés:** a jelszóval védett PDF eddig „sérült vagy hiányos fájl” üzenetet kapott; most saját üzenetet kap.
- **Élő ellenőrzés (éles konténer, valódi MNB, LLM kikapcsolva):** a 12 fájl mindegyike a várt eredményt adta
  (3 `error`, 4 `rejected`, K6 → `ok` két figyelmeztetéssel, `review`, K8 → `ok` ideiglenes árfolyammal, 2 × HTTP 400).
  K9: elérhetetlen `MNB_URL`-lel egy GBP-számla `pending_fx` lett, a szerver közben is válaszolt; a valódi MNB
  visszaállítása után a következő feltöltés pótolta az árfolyamot (2026-11-23-i jegyzés). A felületen a feltöltési
  napló minden fájlnál a magyar indoklást mutatta; az elutasítottak a számlalistában nem jelennek meg (felhasználói
  döntés, 9.1).
- **README.md:** indítás, architektúra, kinyerés és ismeretlen formátumok, LLM-ellenőrzés és modellválasztás,
  MNB-árfolyam, státuszok, konfiguráció, tesztek, korlátok, továbbfejlesztés.

---

## 12. Nem funkcionális követelmények

- **Robusztusság:** fájlonkénti hibaizoláció; a szerver soha nem áll le egy fájl miatt; az időtúllépések (MNB, LLM) be vannak állítva.
- **Teljesítmény:** a 100 fájl szabályalapon ~1 perc alatt feldolgozható; az MNB-hívások száma pénznemenként minimális (összevont intervallumok).
- **Biztonság:** a kulcs csak env-ből jön, nem kerül naplóba; a feltöltés mérete korlátozott; a fájlnév nem kerül fájlrendszer-útvonalba (a PDF-et sha256 néven tároljuk).
- **Átláthatóság:** a számlalistában látszik minden számításhoz felhasznált adat (árfolyam, annak dátuma, unit, kinyerési mód, figyelmeztetések).

## 13. Ismert korlátok és kockázatok (a README-be is)

- A szabályalapú kinyerés a címkeszótárra épül: egy teljesen ismeretlen nyelvű vagy címke nélküli sablon az LLM-tartalékra szorul, kulcs nélkül `review` státuszt kap.
- A `DD/MM` és `MM/DD` kétértelműséget heurisztika dönti el (a nyelv és az érvényesség alapján).
- Szkennelt (képes) PDF-et nem kezelünk (a feladat szerint nincs ilyen); üres szöveg esetén `error` státuszt adunk.
  A megnyitási jelszóval védett PDF szintén `error`.
- A különleges bizonylatokat (jóváíró, proforma, előleg) szándékosan elutasítjuk (K7), így a nettósított cash-flow ezekkel nem számol.
- Az ideiglenes árfolyam (K8) a következő feltöltésig marad érvényben, mert nincs ütemezett háttérfrissítés.
