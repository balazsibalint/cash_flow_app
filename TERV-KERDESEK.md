# Terv és nyitott kérdések – Számlafeldolgozó és cash-flow kimutatás

> Ez a fájl a tervezés eredménye: az első részben a javasolt megoldás, a végén azok a kérdések és döntések,
> amelyeket **neked kell meghoznod**. Minden kérdésnél ott a javaslatom – ha egyetértesz, elég a
> „Döntés” sort kitölteni (pl. `A` vagy `OK`).

---

## 0. Mit mutat a 100 minta-számla (felmérés)

A számlákat a már futó konténerben, `pdfplumber`-rel olvastam be, és szkripttel mértem fel (a fájlok nem módosultak).

| Megállapítás | Következmény a tervre |
|---|---|
| 100/100 fájl szöveges és hiba nélkül beolvasható; 98 egyoldalas, **2 kétoldalas** (Pannon Irodaszer, a végösszeg a 2. oldalon van) | Az összes oldal szövegét együtt kell feldolgozni. |
| Pénznemek: EUR 46, HUF 37, PLN 6, USD 6, GBP 5 | Mind az öt pénznem jegyzett az MNB-nél. |
| Mind a 100 számlán szerepel a mi adószámunk (`26481937`) | Az irány az adószám alapján megbízhatóan eldönthető. |
| **Kétoszlopos fejléc** (pl. Greenfield, Pannon, Soluciones Ibéricas, NWS-sablon): a szövegkinyerés összekeveri a címkéket és az értékeket (`Vevő Kiállítás dátuma / Fizetési határidő / NORDWIND… 2026. június 24. / 2026. július 2.`) | A sima soronkénti regex nem elég, **koordináta-alapú** (szóhelyzetes) címke→érték párosítás kell. |
| A Pannon és a saját NWS-sablon fejlécében **csak a közösségi adószám** áll (`HU23918466`), máshol a belföldi is (`21847502-1-42`) | A partner kulcsa a **normalizált adószám-törzs** legyen (HU + 8 jegy ↔ 8 jegy-x-xx). |
| Ugyanaz a cég mindkét irányban szerepel (pl. a Duna Logisztika szállító és vevő is) | A partnertábla két sorában valódi értékek lesznek, nem csak nullák. |
| A számlaszámok formátuma eltér a fájlnévtől (`KT-2026/006`, `NWS/2026/0035`, `FV/48/03/2026`) | A fájlnévre nem építünk; normalizált számlaszámot tárolunk. |
| **Csapda:** a kétnyelvű kimenő számlán (`NW-2026-0014`) saját árfolyam és forintos ÁFA áll: „Az ÁFA összege forintban: 97 309 Ft (MNB árfolyam: 1 EUR = 396,92 HUF)” | Ezt figyelmen kívül kell hagyni, és sem forintos végösszegnek, sem árfolyamnak nem szabad tekinteni. Mi az MNB-ből kérdezünk le. |
| Van 2025-ös teljesítési dátum is (`KT-2026/006`: teljesítés 2025.12.31.) | Az árfolyam-lekérés nem korlátozódhat 2026-ra. |
| Dátumformátumok: `2026.03.15.`, `2026. június 24.`, `15.03.2026`, `04/03/2026`, `13 mars 2026`, `10. März 2026`, `February 1, 2026`, `30 January 2026` | Nyelvenkénti hónapnév-szótár és formátumlista kell. |
| Számformátumok: `1 648 156`, `1.493,78`, `2 668,00`, `3,465.00`, `$739.00` | Kontextusfüggő tizedesjel-felismerés kell (az utolsó elválasztó és a jegyek száma alapján). |
| Van ellenőrizhető redundancia: nettó + ÁFA = bruttó, a tételsorok összege = nettó | Erre épül a validáció és az LLM-tartalék indítása. |
| Nem találtam jóváíró, sztornó, díjbekérő vagy előlegszámlát, és duplikátum sincs (tartalom-hash alapján) | A rejtett tesztszámlák között ilyen előfordulhat, ezért lásd a **K7** kérdést. |

---

## 1. Architektúra (javaslat)

```
Böngésző (React + Tailwind + Recharts)
   │  több PDF feltöltése (fájlonként külön kérés, párhuzamosan)
   ▼
FastAPI (egy konténer, :8080, a lefordított frontendet is kiszolgálja)
   ├─ api/invoices.py   POST /api/invoices (1 fájl) · GET /api/invoices · DELETE /api/invoices[/{id}]
   ├─ api/report.py     GET /api/report  → {chart: [...], partners: [...]}
   ├─ services/pdf_text.py         szöveg + szókoordináták (pdfplumber)
   ├─ services/extraction/
   │    normalize.py   dátum, szám, adószám, számlaszám normalizálás
   │    labels.py      többnyelvű címkeszótár (hu/en/de/fr/es/it/pl)
   │    rules.py       szabályalapú kinyerő (címke→érték, koordinátákkal)
   │    llm.py         OpenRouter-tartalék (JSON-séma, temperature 0)
   │    validate.py    üzleti ellenőrzések
   │    pipeline.py    rules → validate → (hiba esetén) llm → validate
   ├─ services/mnb.py  SOAP-kliens + gyorsítótár + árfolyam-kiválasztás
   ├─ services/fx.py   átváltás, kerekítés (Decimal, ROUND_HALF_UP)
   └─ services/report.py  havi idősor és partner-aggregáció
SQLite (named volume: /app/data)
```

**Indoklás:** egyetlen konténer és egyetlen URL (`http://localhost:8080`), Dockeren kívüli függőség nélkül.
Ha a frontend fájlonként küldi a kéréseket, nincs szükség háttér-feladatsorra, és mégis fájlonkénti
visszajelzés van (✓ / ⚠ / ✗), egy hibás fájl pedig nem állítja meg a többit.

## 2. Adatkinyerés

1. **Szöveg és szókoordináták** az összes oldalról.
2. **Szabályalapú kinyerés** (elsődleges): a többnyelvű címkeszótárból megkeressük a címkét (pl. *Fizetési határidő,
   Due date, Zahlbar bis, Date d'échéance, Fecha de vencimiento, Data scadenza, Termin płatności*), majd az értéket
   ugyanabban a sorban a címkétől jobbra, vagy **ugyanabban az oszlopban alatta** keressük (ez kezeli a kétoszlopos fejlécet).
   - A **feleket** blokkokra bontva azonosítjuk: a vevő a „Vevő / Bill to / Rechnungsempfänger / Facturé à / Cliente /
     Nabywca / Cessionario” címke alatti blokk, a kiállító a fejléc. A blokkban adószám-mintákat keresünk.
   - A **bruttó összeget** prioritási lista alapján választjuk ki (*Fizetendő összesen, Total due, Rechnungsbetrag,
     Net à payer TTC, TOTAL A PAGAR, Totale documento, Do zapłaty* …), kizárva a „forintban”, ÁFA- és nettó sorokat.
3. **Validáció:** kötelező mezők, ismert pénznem, a dátumok hihetősége (kiállítás ≤ határidő), **nettó + ÁFA = bruttó**,
   ha elérhető: tételösszeg = nettó, és a mi cégünk pontosan az egyik oldalon szerepel.
4. **LLM-tartalék** (lásd K1): csak akkor fut, ha a szabályalapú eredmény elbukik a validáción. A PDF-ből kinyert
   **szöveget** küldjük, JSON-sémával. A választ ugyanazok a validátorok ellenőrzik. Az eredményt fájl-hash szerint
   tároljuk, így ugyanazt a számlát soha nem küldjük el kétszer.
5. Ha ez is elbukik: a számla „**ellenőrzendő**” vagy „**hibás**” státuszt kap az okkal együtt, és látszik a listában (lásd K5).

**Ismeretlen formátum:** a címkeszótár és a koordináta-alapú keresés nem kötődik egyetlen sablonhoz sem.
Ami így sem sikerül, azt az LLM-tartalék és a validáció kapja el. Semmi nincs a 100 fájlra „bedrótozva”.

## 3. Adatmodell (SQLite, SQLAlchemy)

| Tábla | Fő mezők |
|---|---|
| `invoices` | id, file_sha256 (egyedi), filename, status (`ok`/`review`/`error`), messages (JSON), extraction_method (`rule`/`llm`), invoice_number, invoice_number_norm, seller_name, seller_tax, buyer_name, buyer_tax, issue_date, supply_date, due_date, currency, gross_amount (Decimal), net_amount, vat_amount, direction, partner_id, fx_rate, fx_unit, fx_rate_date, gross_huf (int), created_at · **UNIQUE(seller_tax_key, invoice_number_norm)** |
| `partners` | id, tax_key (egyedi, pl. `HU23918466`), display_name, aliases (JSON) |
| `exchange_rates` | (date, currency) PK, rate (Decimal), unit |
| `mnb_fetches` | currency, start_date, end_date, fetched_at – ebből tudjuk, mely időszak van már lekérdezve (a nem jegyzési napok miatt) |

## 4. MNB-árfolyam

- `GetExchangeRates` hívás `httpx`-szel, a SOAP-választ `xml.etree`-vel dolgozzuk fel. A belső, escape-elt XML-t
  külön elemezzük, a tizedesvessző `Decimal`-ra alakul, a `unit` mezőt is figyelembe vesszük.
- **Kiválasztás:** a teljesítés napján vagy azelőtt jegyzett legutolsó árfolyam. Hogy hétvégén és ünnepnapon is legyen
  „előző” jegyzés, a lekérést **teljesítés − 10 nap**-tól indítjuk.
- **Gyorsítótár:** egy feltöltési kötegnél pénznemenként egyetlen, összevont intervallumot kérünk le, és csak azt
  a részt, amelyet az `mnb_fetches` még nem fed le. Minden jegyzést elmentünk.
- `HUF_összeg = round_half_up(bruttó × árfolyam / unit)` egész forintra; a HUF számla árfolyama 1.
- Ha az MNB nem érhető el: lásd **K9**.

## 5. Kimutatás (egy oldal, ebben a sorrendben)

1. **Feltöltő panel**: drag & drop, több fájl, fájlonkénti állapot és hibaüzenet, összesítő (új / már feldolgozott / hibás).
2. **Vonaldiagram** (Recharts): X = esedékesség hónapja (`ÉÉÉÉ-HH`), folytonos tartomány 0-s hónapokkal; két vonal
   (bejövő, kimenő); jelmagyarázat, tengelyfeliratok, `1 234 567 Ft` formátum, tooltip.
3. **Partnertábla**: oszlopok = partnerek, két sor (Össz bejövő / Össz kimenő), vízszintes görgetéssel, rögzített első oszloppal.
4. **Számlalista**: minden kinyert mező, eredeti összeg és pénznem, árfolyam és annak dátuma, HUF-összeg, státusz, kinyerési mód; rendezhető és szűrhető.

## 6. Tesztek (pytest)

- `test_normalize.py`: dátumok minden nyelven, számformátumok, adószám-normalizálás.
- `test_extraction.py`: minta-PDF-eken az elvárt mezők (egy kézzel ellenőrzött `expected.json` alapján), a kétoszlopos és a többoldalas eset.
- `test_mnb.py`: rögzített SOAP-válaszon a feldolgozás, valamint hétvégi, ünnepnapi és `unit ≠ 1` esetek; a cache miatt nincs dupla lekérés (mockolt HTTP).
- `test_fx.py`: kerekítés 0,5-nél.
- `test_report.py`: a hónapok kitöltése, a partnerek összevonása adószám alapján, a 0-s cellák.
- `test_api.py`: duplikált feltöltés, hibás (nem PDF vagy sérült) fájl.

## 7. Megvalósítási lépések (≈ commitok)

1. Konfiguráció, DB-modellek, CLAUDE.md, README-váz
2. Normalizálók és unit tesztjeik
3. PDF-szöveg + szabályalapú kinyerő; regressziós teszt mind a 100 számlán (`expected.json`)
4. Validáció + LLM-tartalék
5. MNB-kliens + cache + árfolyam-kiválasztás + tesztek
6. Feltöltés-API (dedup, hibakezelés) + aggregáció-API
7. Frontend: feltöltés → diagram → partnertábla → számlalista
8. Robusztussági kör (szintetikus, „rejtett” jellegű számlák, hibás fájlok), README, AI_NAPLO véglegesítése

---

## 8. Kérdések és döntések – ezeket neked kell eldöntened

### K1. Szabályalapú vagy LLM-alapú kinyerés?
- **A)** Szabályalapú elsődleges, az LLM csak tartalék, ha a validáció elbukik. *(javaslat: a feladat ezt előnyként említi, olcsó, determinisztikus, és jól bemutatható)*
- **B)** Elsődlegesen LLM, a szabályok csak ellenőrzésre. Gyorsabban elkészül és általánosabb, de minden számla API-hívás, és nem determinisztikus.
- **C)** Csak szabályalapú, LLM nélkül.

**Döntés:** A

### K2. Melyik LLM-modell legyen az alapértelmezett (OpenRouter)?
Jelenleg: `google/gemini-2.5-flash` (olcsó, gyors, jó JSON-kimenet és nagy kontextus). Alternatívák: `openai/gpt-4o-mini`
vagy egy erősebb modell (pl. Claude Sonnet), amely drágább, de pontosabb. A README-ben indokolni kell.

**Döntés:** google/gemini-2.5-flash

### K3. Maradjon-e a közvetlen Gemini API-szolgáltató (`LLM_PROVIDER=gemini`)?
A feladat az OpenRouter-kulcsot csak az alkalmazásba szánja, a fejlesztéshez a sajátodat használod. Két út van:
- **A)** Egyetlen OpenAI-kompatibilis kliens, amelynek `LLM_BASE_URL`-je átállítható (az OpenRouter és a Gemini is OpenAI-kompatibilis). Kevesebb kód, egy kódút. *(javaslat)*
- **B)** Két külön szolgáltató-implementáció.
- **C)** Csak OpenRouter; fejlesztéskor is azt használod a saját kulcsoddal.

**Döntés:** A

### K4. Mi számít „ugyanannak a számlának” ismételt feltöltéskor?
Javaslat: kiállító adószám-törzse + normalizált számlaszám (a `/ - szóköz` különbség nem számít). Előtte fájl-hash
alapú gyorsellenőrzés, így bájtazonos fájlnál még a feldolgozás sem fut le.
És ha ugyanaz a kulcs **más tartalommal** érkezik (pl. javított számla)?
- **A)** Kihagyjuk, és „már feldolgozva” jelzést adunk. *(javaslat)*
- **B)** Felülírjuk az új verzióval.

**Döntés:** A

### K5. Mi legyen a hiányos vagy bizonytalan számlákkal?
Ha a validáció az LLM után is elbukik (pl. nettó + ÁFA ≠ bruttó, vagy hiányzik a határidő):
- **A)** „Ellenőrzendő” státuszt kap, látszik a listában, de **nem számít bele** a kimutatásba. *(javaslat)*
- **B)** A legjobb tippel beleszámít, figyelmeztetéssel.
- **C)** Mint A), plusz a felületen **kézzel javítható** (szerkeszthető mezők). Ez több munka, de jól mutat a demón.

**Döntés:** A

### K6. Mi legyen, ha hiányzik a teljesítés dátuma vagy a fizetési határidő?
A 100 számla mindegyikén megvan, de a rejtett tesztszámlákon hiányozhat.
- Teljesítés hiányzik → a kiállítás dátumát használjuk, figyelmeztetéssel? *(javaslat)*
- Határidő hiányzik, de van „net 15 days / 8 nap” fizetési feltétel → kiszámoljuk (kiállítás + N nap), figyelmeztetéssel? *(javaslat)*
  Ha fizetési feltétel sincs → „ellenőrzendő”.

**Döntés:** Javasolt megoldások

### K7. Hogyan kezeljük a különleges bizonylatokat (a mintában nincs ilyen, a rejtett tesztben lehet)?
- **Jóváíró, sztornó számla** (negatív végösszeg): negatív előjellel számítson bele? *(javaslat: igen)*
- **Díjbekérő, proforma**: nem számla, ezért elutasítjuk („nem számla” hibaüzenettel)? *(javaslat: igen)*
- **Olyan számla, amelyen a mi cégünk egyik félként sem szerepel**: hiba, kimarad a kimutatásból? *(javaslat: igen)*
- **Az öt pénznemen kívüli deviza** (pl. CHF, JPY): az MNB-ből lekérjük, a `unit` mezőt figyelembe véve? *(javaslat: igen, általánosan)*

**Döntés:** A különleges bizonylatokat ne dolgozzuk fel, ne számítsanak bele sehova, utasítsuk el őket. A többihez jók a javasolt megoldások.

### K8. Teljesítés a jövőben, vagy olyan nap, amelyre még nincs jegyzés?
A szabály betű szerint a legutolsó, azt megelőzően közzétett árfolyamot kéri, ez a mai napig ismert legutolsó.
Ilyenkor:
- **A)** A legutolsó ismert árfolyamot használjuk, „ideiglenes” jelöléssel, és később újraszámolható. *(javaslat)*
- **B)** „Árfolyamra vár” státusz, és kimarad a kimutatásból.

**Döntés:** A

### K9. Mi legyen, ha az MNB-szolgáltatás nem érhető el feltöltéskor?
- **A)** A számla elmentődik „árfolyamra vár” státusszal, egy gomb vagy a következő feltöltés újrapróbálja. *(javaslat)*
- **B)** A feltöltés hibát ad, és újra kell próbálni.

**Döntés:** A, a következő feltöltés újrapróbálja.

### K10. Feltöltés módja
- **A)** A frontend fájlonként küld kérést (pl. egyszerre 4 párhuzamosan), mindegyikre azonnal jön eredmény, és élő a haladásjelző. *(javaslat: egyszerű, robusztus, nem kell feladatsor)*
- **B)** Egy kérés az összes fájllal, aszinkron háttérfeladat és lekérdezés (polling).

**Döntés:** A

### K11. Tároljuk-e az eredeti PDF-eket?
- **A)** Igen, a volume-ban. Így a kód javítása után az LLM újrahívása nélkül **újrafeldolgozható** minden számla, és a listából meg is nyitható a PDF. *(javaslat)*
- **B)** Csak a kinyert adatokat és a szöveget tároljuk.

**Döntés:** A

### K12. Legyen „Összes törlése” vagy egyenkénti törlés funkció?
A demóhoz hasznos (tiszta lappal indítható a 100 fájl feltöltése). *(javaslat: igen, megerősítő kérdéssel)*

**Döntés:** Legyen összes és egyenkénti törlés is.

### K13. Partner megjelenített neve és az oszlopok sorrendje
- A név: a leggyakoribb írásmód, vagy a legutóbbi számláról? *(javaslat: leggyakoribb, és a változatok tooltipben)*
- Az oszlopok sorrendje: ABC szerint, vagy a teljes forgalom szerint csökkenően? *(javaslat: forgalom szerint)*

**Döntés:** Javasolt megoldások.

### K14. A minta-PDF-ek és a referenciaértékek a repóban
Jelenleg az `invoices/` a `.gitignore`-ban van, így friss klónon a PDF-alapú tesztek nem futnak.
- **A)** A teljes `invoices/` mappa bekerül a repóba (≈ 100 kis fájl), és a tesztek mind a 100-on futnak. *(javaslat, ha a feladat engedi a csomag közzétételét)*
- **B)** Csak 10–15 reprezentatív PDF kerül a `backend/tests/fixtures/` alá.
- **C)** Semmi nem kerül be; a PDF-alapú tesztek kihagyódnak, ha nincs mappa.

Ezen felül: a referenciaértékeket (`expected.json`) **te ellenőrzöd kézzel** egy mintán, vagy elfogadod az első futás eredményét
szúrópróbás ellenőrzés után? A feladat a referenciaértékekkel való összevetést kifejezetten kéri az AI_NAPLO-ban.

**Döntés:** B, és én kézzel készítek egy expected.json fájlt az ellenőrzésre.

### K15. Felület nyelve és stílusa
Javaslat: magyar felület, magyar számformátum (`1 234 567 Ft`), egyszerű, letisztult Tailwind-dizájn, világos téma.
Kell-e sötét mód vagy angol nyelv?

**Döntés:** Elég a magyar és világos felület.

### K16. Git- és dokumentációs keretek
- Fő ág: maradjon a `master`, vagy átnevezzük `main`-re? (Jelenleg `master`.)
- Kérsz-e `CLAUDE.md`-t projekt-szabályokkal? Javasolt tartalma: nyelv, a tesztelés kötelező, LLM-kulcs a fejlesztéshez nem használható, kis commitok.
- `ai-logs/`: exportálod a Claude Code-beszélgetéseket a végén? Ezt neked kell megtenned.

**Döntés:** Maradjon master a fő ág. Igen, készíts egy CLAUDE.md fájlt, ami tartalmazza az összes szabályt. Az ai-logs mappával egyelőre nem kell foglalkozni.

---

### Döntések, amelyeket külön jelzés nélkül a javaslat szerint viszek
- SQLite + SQLAlchemy `create_all`, migrációs eszköz (Alembic) nélkül.
- `Decimal` minden pénzösszegre; kerekítés `ROUND_HALF_UP`.
- Diagramkönyvtár: Recharts.
- Az irányt elsősorban **adószám** alapján döntjük el (belföldi és EU VAT), a név csak tartalék.
- A partnerkulcs a normalizált adószám (`HU` + 8 jegy a magyar cégeknél, ország-előtag + szám a külföldieknél, EIN az amerikaiaknál), adószám hiányában a normalizált név.
- A számlán feltüntetett saját árfolyamot vagy forintos ÁFA-összeget nem használjuk.
