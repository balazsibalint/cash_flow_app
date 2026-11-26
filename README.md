# Számlafeldolgozó és cash flow kimutatás

Webalkalmazás a Nordwind Solutions Kft. bejövő és kimenő számláinak feldolgozására. A feltöltött PDF számlákból
kinyeri a kimutatáshoz szükséges adatokat, a devizás összegeket az MNB hivatalos árfolyamával forintra váltja, és
fizetési határidő szerinti havi cash flow kimutatást készít (vonaldiagramot, partnerenkénti összesítőt és
ellenőrizhető számlalistát).

- **Kinyerés:** elsődlegesen szabályalapú (többnyelvű címkeszótár és a PDF elrendezése). LLM csak tartalék, ha a
  szabályalapú eredmény nem megy át a validáción. A mellékelt 100 mintaszámla mindegyike LLM nélkül feldolgozható.
- **Árfolyam:** a teljesítés napján vagy azelőtt közzétett utolsó MNB jegyzés, helyi gyorsítótárral.
- **Átláthatóság:** a számlalistában minden számlánál látszik a felhasznált árfolyam, annak dátuma, a kinyerés módja
  és minden figyelmeztetés. A kimutatásba csak a hibátlan („Rendben” státuszú) számlák számítanak bele.

## Indítás

Előfeltétel: Docker (Docker Desktop). Más helyi függőség nem kell.

```bash
cp .env.example .env
docker compose up --build
```

Az alkalmazás címe: **http://localhost:8080**.

- Kulcs nélkül is elindul és működik, csak szabályalapon. Ha egy számla így nem dolgozható fel, „Ellenőrzendő”
  státuszt kap.
- Az adatbázis és a feltöltött PDF-ek a `sqlite_data` Docker-volume-ban vannak, így a konténer újraindítása után is megmaradnak.
- Teljes törlés: `docker compose down -v` vagy a felületen az „Összes törlése” gomb.
- Állapotellenőrzés: `curl http://localhost:8080/api/health` → `{"status":"ok","llm_enabled":...}`.

## Használat

1. **Feltöltés:** a PDF-ek behúzhatók vagy tallózhatók, akár a teljes csomag egyszerre.
   - A böngésző fájlonként küldi őket, egyszerre 4 kéréssel.
   - Minden fájl mellett megjelenik az eredménye: új, már feldolgozott, ellenőrzendő, elutasított vagy hibás, magyar
     indoklással.
   - Ugyanaz a számla nem kerül be kétszer.
2. **Kimutatás:** havi bejövő és kimenő bruttó forintösszeg a fizetési határidő hónapja szerint, valamint
   partnerenkénti összesítő. A partnereket az adószám azonosítja, így egy cég eltérő névírásai is egy oszlopba
   kerülnek.
3. **Számlalista:** keresés, szűrés, rendezés és lapozás. Egy sorra kattintva megjelennek a részletek és az
   üzenetek. Soronként megnyitható az eredeti PDF, és a számla törölhető.

## Tesztelés
- Az alkalmazás **automatizált tesztkészlete** (összesen 337 teszt) a fejlesztői konténerben, ideiglenes adatbázissal, valamint mockolt MNB- és LLM-válaszokkal fut, így nem érinti a futó alkalmazás adatait és nem generál külső API forgalmat.
```bash
# Az összes teszt futtatása (~45 mp)
docker compose -f docker-compose.dev.yml run --rm app pytest -q
```
- A részletes tesztelési útmutatót, a szűrési parancsokat és az élő bemutatóhoz használható próbacsomag lépéseit a [TESZTELES.md](/TESZTELES.md) fájl tartalmazza, amely az alábbi négy fő szempont szerint csoportosítja a teszteket:
  - Adatkinyerés
  - Árfolyam-kiválasztás és átváltás
  - Aggregálás
  - Egyéb tesztek

## Architektúra

```
Böngésző (React 19 + TypeScript + Tailwind 4 + Recharts)
   │  HTTP/JSON, azonos origin (:8080)
FastAPI (Python 3.12) ── a statikus frontendet is kiszolgálja
   ├─ api/            vékony HTTP-réteg: validáció, státuszkódok
   ├─ services/
   │   ├─ ingest.py           egy fájl teljes útja: ellenőrzés → dedup → kinyerés → árfolyam → partner → mentés
   │   ├─ pdf_text.py         pdfplumber: szavak koordinátákkal, sorok, oldalak
   │   ├─ extraction/         doctype → szabályalapú kinyerés → validáció → (LLM-tartalék)
   │   ├─ mnb.py, fx.py       MNB SOAP-kliens, gyorsítótár, árfolyam-kiválasztás, átváltás
   │   ├─ partners.py         partnerkulcs (normalizált adószám), névváltozatok
   │   └─ report.py           havi és partnerenkénti aggregáció
   └─ SQLite (/app/data/app.db) + eredeti PDF-ek (/app/data/pdfs/<sha256>.pdf)
          │                                   │
   www.mnb.hu/arfolyamok.asmx (SOAP)     openrouter.ai (csak tartalékként)
```

- **Egy konténer:** a gyökérkönyvtári `Dockerfile` többlépcsős; előbb lefordítja a frontendet, majd a FastAPI-alkalmazás
  szolgálja ki.
- **Pénzösszegek:** mindig `Decimal` (soha `float`). Az átváltás számlánként egész forintra kerekít
  (`ROUND_HALF_UP`), és az összesítés csak ezután történik.
- **Hibaizoláció:** a fájlok feldolgozása egymástól független. Bármilyen hiba, váratlan kivétel is, csak az adott
  fájlt jelöli „Hiba” státusszal, magyar indoklással; a szerver tovább fut.
- **API:**
  - `POST /api/invoices` (egy fájl), `GET /api/invoices`, `GET /api/invoices/{id}/pdf`;
  - `DELETE /api/invoices/{id}`, `DELETE /api/invoices`;
  - `GET /api/report`, `GET /api/health`.

A részletes terv és a döntések indoklása: [RENDSZERTERV.md](RENDSZERTERV.md), [TERV-KERDESEK.md](TERV-KERDESEK.md).

## Hogyan működik az adatkinyerés

Minden fájl ezen a láncon megy végig (`services/extraction/pipeline.py`):

1. **Feltöltés-ellenőrzés:**
   - üres fájl, illetve `%PDF-` fejléc nélküli fájl → `400`;
   - a `MAX_UPLOAD_MB`-nál nagyobb fájl → `413`;
   - ezeket a fájlokat nem mentjük.
2. **Duplikáció (1):** ha a fájl SHA-256 hash-e már ismert, a fájlt nem dolgozzuk fel újra.
3. **PDF-szöveg:** a pdfplumber koordinátás szavaiból sorokat és sorszegmenseket építünk (bal és jobb oszlop, kétnyelvű
   címkék). A sérült, a jelszóval védett és a szöveg nélküli (szkennelt) PDF „Hiba” státuszt kap, a saját magyar
   indoklásával.
4. **Bizonylattípus:** ha a dokumentum fejlécében (az első oldal felső 35%-ában) jóváíró, sztornó, helyesbítő,
   díjbekérő, proforma vagy előleg kulcsszó áll, hét nyelven és ritkított írással is felismerve, a bizonylat
   „Elutasítva” státuszt kap. Elutasítjuk a negatív végösszegű bizonylatot és azt a dokumentumot is, amelyen a saját
   cégünk egyik félként sem szerepel. Ezekhez LLM-et sem hívunk.
5. **Szabályalapú kinyerés:**
   - **Címkék:** mezőnként többnyelvű címkeszótár (magyar, angol, német, francia, spanyol, olasz, lengyel), kis- és
     nagybetűtől, ékezettől és ritkított írástól függetlenül.
   - **Érték keresése:** a címke utáni érték ugyanabban a sorban vagy a címke oszlopában közvetlenül alatta.
   - **Típusos értelmezés:**
     - dátumok számmal és hónapnévvel írva (7 nyelvű hónapnév-szótárral), pl. `2026.03.09.`, `09.03.2026`,
       `9. März 2026`, `March 9, 2026`;
     - összegek ezres és tizedes elválasztóval;
     - adószámok: magyar, EU-s közösségi, amerikai EIN, lengyel NIP;
     - pénznem: címke, szimbólum vagy ISO-kód alapján.
   - **Több jelölt esetén:** a végösszegnél a nettó + ÁFA = bruttó egyezést adó jelölt nyer.
   - **A felek:** a vevőblokkot a „Vevő / Bill to / Rechnungsempfänger …” címke jelöli ki, a kiállító a fölötte lévő
     rész.
   - **Irány:** a saját adószám helye dönti el (kiállítónál → kimenő, vevőnél → bejövő).
   - **Kizárt adatok:** a számlára nyomtatott forintos tájékoztató adatot (például „ÁFA forintban”, saját árfolyam)
     sosem használjuk végösszegként vagy árfolyamként.
6. **Következtetés:**
   - hiányzó teljesítési dátum → a kiállítás dátuma;
   - hiányzó határidő → kiállítás + fizetési feltétel (pl. „15 nap”, „Net 30”);
   - mindkét esetben figyelmeztetéssel.
7. **Validáció:**
   - kötelező mezők;
   - nettó + ÁFA = bruttó (HUF-nál 1 Ft, devizánál 0,01 tűréssel);
   - dátumsorrend, ISO-pénznem;
   - a saját cég pontosan az egyik oldalon szerepel.
8. **LLM-tartalék:** csak akkor fut, ha a 7. lépés hibát talált (lásd lent). Ha az eredménye sem érvényes, a számla
   „Ellenőrzendő” lesz, és nem számít bele a kimutatásba.
9. **Duplikáció (2):** ha ugyanannál a kiállítónál ugyanaz a normalizált számlaszám már szerepel
   (`KT-2026/006` = `KT2026006`), a számlát kihagyjuk. Így a más fájlnévvel vagy újragenerált PDF-ként érkező
   számla sem kerül be kétszer.

### Ismeretlen formátumú számlák

- **Kódban nincs semmi a mintákra szabva:** se fájlnév, se partnernév, se sablon. A kinyerés a címkékre és az
  elrendezés geometriájára épül, ezért egy új, de hasonló felépítésű számla (más nyelv, más oszlopelrendezés, több
  oldal) ugyanígy feldolgozható.
- **Ha a szabályok nem boldogulnak** (ismeretlen címke, szokatlan elrendezés), az eredmény elbukik a validáción, és az
  LLM-tartalék kapja meg a szöveget.
- **Ha az LLM sem ad ellenőrizhető eredményt, vagy nincs kulcs,** a számla „Ellenőrzendő” lesz, a hibák felsorolásával.
  Bizonytalan adat tehát nem kerül be a kimutatásba.

### Az LLM-tartalék és a válasz ellenőrzése

- **Mit kap a modell:** a PDF rekonstruált szövegét (soronként, oldaljelzéssel), a saját cég adatait és a szabályalapú
  részeredményt a hibakódokkal. Magát a PDF-et nem küldjük el.
- **A válasz formátuma:** OpenAI-kompatibilis `chat/completions` hívás, `temperature: 0`, JSON-sémás válasz.
- **A válasz ellenőrzése:**
  1. **Séma:** Pydantic-validáció (típusok, ISO-dátumok, pénznem).
  2. **Horgonyzás:** a számlaszámnak és a bruttó összegnek normalizált formában szerepelnie kell a PDF szövegében.
     Ha nem szerepel, a választ hallucinációnak tekintjük és elvetjük.
  3. **Ugyanazok a validátorok,** mint a szabályalapú eredményre: összegegyezés, dátumsorrend, a saját cég helye.
  4. **Eltérés:** ahol a szabályalapú és az LLM-érték is megvan és eltér, figyelmeztetés kerül a számlához.
- **Takarékosság:**
  - LLM-et csak validációs hibánál hívunk;
  - egy fájlt egyszer (a hash-alapú dedup miatt);
  - napi limit (`LLM_MAX_CALLS_PER_DAY`), párhuzamossági korlát és időtúllépés;
  - különleges és idegen bizonylatra nem hívunk LLM-et.
- **Látható jelölés:** az LLM-mel feldolgozott számla a listában „LLM” módot kap, és az üzenetek között szerepel,
  miért kellett az LLM.

## MNB-árfolyamok lekérése és tárolása

- **Forrás:** az MNB hivatalos SOAP-webszolgáltatása (`GetExchangeRates`, `http://www.mnb.hu/arfolyamok.asmx`).
- **Melyik árfolyam:** a teljesítés napján vagy azelőtt közzétett **utolsó** jegyzés. Hétvégén, ünnepnapon vagy a napi
  közzététel előtt ez a korábbi munkanap jegyzése. A jegyzés egységét (`unit`, pl. 100 JPY) is figyelembe vesszük:
  `forint = összeg × árfolyam / unit`, számlánként egész forintra kerekítve (`ROUND_HALF_UP`).
- **Gyorsítótár:**
  - a lekért jegyzések az `exchange_rates`, a lekért időszakok az `mnb_fetches` táblába kerülnek;
  - a lekérés deviza és naptári hónap szerint összevont, így egy év számláihoz devizánként kb. 12 hívás kell;
  - ugyanazt a napot és devizát soha nem kérdezzük le kétszer;
  - kivétel a mai nap: ma még jöhet jegyzés, ezért naponta egyszer frissítjük.
  - Az „Összes törlése” a gyorsítótárat nem törli.
- **Ha még nincs jegyzés** (jövőbeli vagy mai teljesítés, a közzététel előtt): a legutolsó ismert árfolyammal számolunk,
  „ideiglenes” jelöléssel. Amint a teljesítés napjára megjelenik a jegyzés, a következő feltöltés automatikusan
  újraszámolja a számlát.
- **Ha az MNB nem érhető el:** a számla „Árfolyamra vár” státuszt kap, és nem számít bele a kimutatásba. A következő
  feltöltés elején újrapróbáljuk, legfeljebb percenként egyszer. Ha az újrapróbálás első hívása sikertelen, abban a
  körben a többi számlára már nem kérdezünk rá, így egy kiesés alatt nem terheljük feleslegesen az MNB-t.
- **Ha az MNB nem jegyzi a devizát:** a számla „Ellenőrzendő” lesz.

## Számlastátuszok

| Státusz | Jelentés | A kimutatásban |
|---|---|---|
| Rendben (`ok`) | Minden adat megvan és érvényes; „ideiglenes” jelöléssel is lehet | igen |
| Ellenőrzendő (`review`) | A kinyert adat hiányos vagy ellentmondásos, és az LLM sem javította | nem |
| Árfolyamra vár (`pending_fx`) | Az MNB nem volt elérhető, a következő feltöltés újrapróbálja | nem |
| Elutasítva (`rejected`) | Különleges bizonylat, negatív végösszeg, vagy a saját cég nem szerepel rajta. A felületen csak a feltöltési naplóban látszik | nem |
| Hiba (`error`) | A fájl nem olvasható (sérült, jelszavas, szöveg nélküli) | nem |


## Ismert korlátok

- **Szkennelt PDF:** nem kezeljük (OCR nincs). Szöveg nélküli PDF-re „Hiba” státuszt adunk. A jelszóval védett PDF-et sem tudjuk megnyitni.
- **Különleges bizonylatok:** a jóváírót, a proformát és az előleget szándékosan elutasítjuk.
- **Késleltetett újraszámolás:** az ideiglenes árfolyamot és az MNB-kiesést csak a következő feltöltés javítja.

## Továbbfejlesztési ötletek

- **Kézi javítás:** az „Ellenőrzendő” számlák mezőinek javítása a felületen, és ezután bekerülésük a kimutatásba.
- **Jóváírók nettósítása:** a jóváíró és sztornó bizonylatok összekapcsolása az eredeti számlával.
- **OCR** a szkennelt számlákhoz.
- **Export:** a kimutatás és a számlalista exportja CSV-be.

## AI-asszisztált fejlesztés

- A fejlesztés menete és a döntések: [AI_NAPLO.md](AI_NAPLO.md)
- Az AI-nak adott szabályfájl: [CLAUDE.md](CLAUDE.md)
- A megvalósítás terve: [RENDSZERTERV.md](RENDSZERTERV.md)
- A tervezéskor meghozott döntések: [TERV-KERDESEK.md](TERV-KERDESEK.md)
