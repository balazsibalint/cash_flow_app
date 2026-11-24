# Coding feladat: Számlafeldolgozó és cash-flow kimutatás

## Háttér

A **Nordwind Solutions Kft.** (a továbbiakban: *a mi cégünk*) egy budapesti szoftvercég, amely magyar és
külföldi partnerekkel dolgozik. A számlák PDF-ben érkeznek és mennek ki, különböző nyelveken,
különböző pénznemekben és a kiállítótól függően teljesen eltérő elrendezésben.

A mi cégünk adatai (ez alapján kell eldönteni, hogy egy számla bejövő vagy kimenő):

| Mező | Érték |
|---|---|
| Név | Nordwind Solutions Kft. |
| Cím | Infopark sétány 7., 1117 Budapest |
| Adószám | 26481937-2-43 |
| Közösségi adószám (EU VAT) | HU26481937 |

- **Kimenő számla**: a mi cégünk a kiállító (eladó / seller / Verkäufer / émetteur …).
- **Bejövő számla**: a mi cégünk a vevő (buyer / bill to / Rechnungsempfänger / client …).

## A mellékelt adatcsomag

Az `invoices/` mappában **100 db PDF számla** található:

- **Nyelvek:** magyar, angol, német, francia, spanyol, olasz, lengyel, valamint kétnyelvű (magyar/angol) számlák.
- **Pénznemek:** HUF, EUR, USD, GBP, PLN.
- **Formátumok:** több különböző kiállító, több különböző sablon (táblázatos, „ERP-nyomtatvány” jellegű, színes fejléces stb.).
  Dátum- és számformátumok nyelvenként eltérnek (pl. `2026.03.15.`, `15.03.2026`, `15 mars 2026`, `March 15, 2026`;
  `1 234,56`, `1.234,56`, `1,234.56`).
- Van köztük **többoldalas** számla is (a végösszeg nem feltétlenül az első oldalon van).
- A PDF-ek szöveges PDF-ek (nem szkennelt képek), tehát OCR nem szükséges.
- A fájlnevekre **ne** építs: azok nem egységesek, és nem hordoznak megbízható információt.

> A kiértékelés során a megoldást **a csomagban nem szereplő, hasonló számlákkal is teszteljük**,
> ezért a 100 db fájlra „bedrótozott” megoldás nem elfogadható.

## A feladat

Készíts egy **Docker konténerben futtatható webalkalmazást**, amelyben fel lehet tölteni a számlákat,
és amely azokból az alábbi, **forintos** kimutatást készíti.

**Technológiai megkötés nincs** – a nyelv, framework, adatbázis, PDF-feldolgozó könyvtár szabadon választható.

### 1. Futtatás

- Az alkalmazás egyetlen paranccsal induljon, pl.:
  ```bash
  docker compose up --build
  ```
  vagy `docker build` + `docker run`. Az elérési URL (pl. `http://localhost:8080`) legyen a README-ben.
- Lokális függőség a Dockeren kívül ne kelljen.
- Ha LLM-et használsz: a `.env.example` fájlt `.env` néven lemásolva és a kulcsot beírva induljon el az alkalmazás.

### 2. Feltöltés

- Webes felületen lehessen **egyszerre több PDF-et** feltölteni (a teljes 100 db-os csomagot is egyben).
- Ugyanannak a számlának az ismételt feltöltése **ne duplikálja** az adatokat
  (azonosítás pl. kiállító + számlaszám alapján).
- A feldolgozás eredménye a böngésző frissítése után is maradjon meg.
- Ha egy fájlt nem sikerül feldolgozni, az alkalmazás ne álljon le: jelezze a hibát az adott fájlnál.

### 3. Adatkinyerés

Minden számlából legalább a következőket kell kinyerni:

| Mező | Megjegyzés |
|---|---|
| Számlaszám | |
| Kiállító (eladó) neve és adószáma | |
| Vevő neve és adószáma | |
| Kiállítás dátuma | |
| **Teljesítés dátuma** | Ehhez a naphoz kell az MNB-árfolyam (lásd 4. pont). |
| **Fizetési határidő (due date)** | Ez alapján készül a diagram. Nem összekeverendő a kiállítás és a teljesítés dátumával! |
| Pénznem | |
| **Bruttó végösszeg** (fizetendő összeg) | Nem a nettó összeg és nem az ÁFA. |
| Irány | `bejövő` / `kimenő` – a mi cégünk adatai alapján |
| Partner | a másik fél (nem a mi cégünk) |

### 4. Átváltás forintra – MNB-árfolyam

A kimutatás **pénzneme HUF**. A nem forintos számlákat a **Magyar Nemzeti Bank hivatalos devizaárfolyamával**
kell átváltani, amelyet az alkalmazás az MNB webszolgáltatásából kérdez le.

**Melyik napi árfolyam:** a számla **teljesítési dátumán** érvényes MNB-árfolyam. Ha azon a napon nem volt
jegyzés (hétvége, munkaszüneti nap), akkor az **utolsó, azt megelőzően közzétett** árfolyam.
Kerekítés: számlánként egész forintra (0,5-től felfelé), az összesítés ezután történik.

**MNB árfolyam-webszolgáltatás (SOAP):**

| | |
|---|---|
| WSDL | `https://www.mnb.hu/arfolyamok.asmx?wsdl` |
| Szolgáltatás végpontja | `http://www.mnb.hu/arfolyamok.asmx` (figyelem: a POST kérés csak **http**-n működik, https-en 404-et ad) |
| Névtér | `http://www.mnb.hu/webservices/` |
| SOAPAction | `http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/<Művelet>` |

Műveletek:

| Művelet | Paraméterek | Mire jó |
|---|---|---|
| `GetExchangeRates` | `startDate`, `endDate` (`ÉÉÉÉ-HH-NN`), `currencyNames` (pl. `EUR,USD,GBP,PLN`) | Napi árfolyamok egy időszakra – **erre lesz szükség** |
| `GetCurrentExchangeRates` | – | A legutóbbi jegyzés |
| `GetCurrencies` | – | Az elérhető devizák listája |
| `GetCurrencyUnits` | `currencyNames` | Egységek (pl. JPY 100 egységre jegyzett) |
| `GetDateInterval` | – | A lekérdezhető időszak |
| `GetInfo` | – | Összefoglaló infó |

Példa kérés:

```bash
curl -X POST "http://www.mnb.hu/arfolyamok.asmx" \
  -H "Content-Type: text/xml; charset=utf-8" \
  -H 'SOAPAction: "http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"' \
  --data '<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:web="http://www.mnb.hu/webservices/">
  <soap:Body>
    <web:GetExchangeRates>
      <web:startDate>2026-01-01</web:startDate>
      <web:endDate>2026-01-31</web:endDate>
      <web:currencyNames>EUR,USD,GBP,PLN</web:currencyNames>
    </web:GetExchangeRates>
  </soap:Body>
</soap:Envelope>'
```

Tudnivalók a válaszról:

- A `GetExchangeRatesResult` elem egy **XML-t tartalmazó szöveg** (escape-elt XML), amit külön kell feldolgozni:
  `<MNBExchangeRates><Day date="2026-11-13"><Rate unit="1" curr="EUR">365,67000</Rate>…</Day>…</MNBExchangeRates>`
- A tizedesjel **vessző**.
- Az árfolyam `unit` egységre vonatkozik (a feladat devizáinál ez 1, de ne feltételezd).
- Csak a jegyzési napok szerepelnek a válaszban.
- A lekért árfolyamokat tárold el, és egy napot/devizát ne kérdezz le többször.

### 5. Kimutatás

Egy oldalon, az alábbi sorrendben. Minden összeg **bruttó, forintban**.

#### a) Vonaldiagram fizetési határidő szerint

- **X tengely:** fizetési határidő (due date), **havi** bontásban (`ÉÉÉÉ-HH`), a legkorábbi és a legkésőbbi
  hónap között folyamatosan – az a hónap is jelenjen meg, amelyben nincs számla (0 értékkel).
- **Y tengely:** bruttó összeg HUF-ban.
- **Két vonal:** *bejövő* számlák összege és *kimenő* számlák összege havonta.
- Jelmagyarázat, tengelyfeliratok, olvasható számformátum (pl. ezres tagolás).

#### b) Cégenkénti összesítő táblázat (a diagram alatt)

- **Oszlopok:** a partnercégek (minden cég, amellyel van legalább egy számla – a mi cégünk nem oszlop).
- **1. sor:** *Össz bejövő* – az adott cégtől kapott számlák bruttó összege (HUF).
- **2. sor:** *Össz kimenő* – az adott cégnek kiállított számlák bruttó összege (HUF).
- Ahol egy irányban nincs számla, ott `0` szerepeljen.
- Ugyanaz a cég akkor is egy oszlop legyen, ha a nevét a különböző számlákon eltérően írják
  (pl. nagybetűvel vagy más nyelvű számlán) – az azonosításhoz érdemes az adószámot használni.

Példa a formára:

| | Cég A | Cég B | Cég C | … |
|---|---:|---:|---:|---|
| **Össz bejövő** | 1 250 000 | 0 | 830 400 | … |
| **Össz kimenő** | 4 100 000 | 2 300 500 | 0 | … |

#### c) Számlalista

- A feldolgozott számlák listája a kinyert mezőkkel, valamint az eredeti összeggel és pénznemmel,
  a felhasznált MNB-árfolyammal és annak dátumával, továbbá a forintösszeggel.
  Így ellenőrizhető, mi alapján készült a kimutatás.

### 6. LLM használata az alkalmazásban (OpenRouter)

Ha a megoldásodhoz LLM-re van szükség (pl. a számlamezők kinyeréséhez), ehhez biztosítunk egy
[OpenRouter](https://openrouter.ai) API kulcsot:

```
---
```

- Az OpenRouteren elérhető **bármelyik modell** használható. A választott modellt és az indoklást írd le a README-ben.
- Ez a kulcs **kizárólag az alkalmazásba beépített LLM-kommunikációra** használható, **a fejlesztéshez nem**
  (a fejlesztéshez a saját AI eszközödet használd, lásd 7. pont).
- A kulcs keretösszege korlátozott. Kíméletesen bánj vele: a már feldolgozott számlát ne küldd el újra,
  és felesleges hívásokat se indíts.
- A kulcs **nem kerülhet be a repositoryba**. Környezeti változóból olvasd (pl. `.env`, amit a `docker compose` betölt),
  és mellékelj egy `.env.example` fájlt a kulcs nélkül.
- A modell neve is legyen konfigurálható környezeti változóval (pl. `OPENROUTER_MODEL`).
- A kiértékelés során a saját kulcsunkkal futtatjuk az alkalmazást.
- Az LLM használata nem kötelező. Ha nélküle (vagy csak hibakezelési tartalékként használva) is megbízhatóan működik
  a megoldás, az előnyt jelent. Ha LLM-et használsz, írd le, hogyan ellenőrzöd a válaszát
  (pl. séma-validáció, a tételsorok összegének és a végösszegnek az összevetése).

### 7. AI-asszisztált fejlesztés – kötelező

A feladatot **AI-asszisztált fejlesztéssel** kell elkészíteni. Bármelyik eszköz használható
(pl. Claude Code, Cursor, GitHub Copilot, ChatGPT/Codex, Windsurf), a saját előfizetéseddel.
Nem az a cél, hogy minden sort te gépelj be. Azt szeretnénk látni, hogyan irányítod, ellenőrzöd és javítod
az AI munkáját.

Dokumentáld a folyamatot:

- **`AI_NAPLO.md`** a repóban, időrendben:
  - milyen lépésekre bontottad a feladatot, és miért;
  - a fontosabb promptok, utasítások (nem kell mindet, csak a meghatározókat);
  - mit javasolt az AI, mit fogadtál el, mit vetettél el, és miért;
  - hol tévedett az AI, hogyan vetted észre (teszt, kézi ellenőrzés, a referenciaértékekkel való összevetés), és hogyan javítottad;
  - milyen kontextust, szabályfájlt adtál neki (pl. `CLAUDE.md`, `.cursorrules`) – ezek is maradjanak a repóban.
- Ha az eszköz engedi, mellékeld a beszélgetések exportját is (pl. egy `ai-logs/` mappában).
- **Git history:** kisebb, beszédes commitok, amelyekből látszik a fejlesztés menete. Egyetlen „final” commit nem elfogadható.

### 8. Leadandó

- Git repository (link vagy zip) a teljes forráskóddal és a teljes git historyval.
- `README.md`:
  - indítás lépései,
  - architektúra röviden,
  - hogyan működik az adatkinyerés, és hogyan kezeli az ismeretlen formátumú számlákat,
  - az MNB-árfolyamok lekérése és tárolása,
  - ismert korlátok, továbbfejlesztési ötletek.
- `AI_NAPLO.md` (lásd 7. pont).
- Automatikus tesztek (legalább az adatkinyerésre, az árfolyam-kiválasztásra és az aggregálásra).

### 9. Bemutató

A leadás után egy kb. **45 perces** bemutatón (személyesen vagy online) mutasd be:

1. **A fejlesztés menetét** (~10 perc): hogyan indultál el, milyen lépésekben haladtál, hogyan dolgoztál az AI-val.
2. **A gondolkodásmódodat** (~10 perc): a fontosabb döntéseket és a mérlegelt alternatívákat
   (pl. szabályalapú vagy LLM-alapú kinyerés, árfolyam-kezelés, adatmodell). Térj ki arra is, hol nem bíztál meg
   az AI eredményében, és miért.
3. **Az elkészült programot** (~10 perc): élő demó Dockerből indítva – a 100 számla feltöltése, a kimutatás
   és a számlalista, egy hibás vagy szokatlan számla kezelése.
4. **Kérdések** (~15 perc): a kódról és a döntéseidről. Készülj fel arra, hogy egy kisebb módosítást élőben,
   AI-val együtt kell elvégezned.

## Értékelési szempontok

1. **Helyesség** – a kimutatás számai egyeznek-e a referenciaértékekkel (a 100 db-os csomagon és rejtett tesztszámlákon),
   helyes-e az MNB-árfolyam kiválasztása.
2. **Robusztusság** – mennyire általános az adatkinyerés (nyelvek, formátumok, többoldalas számla, hibás fájl).
3. **AI-asszisztált fejlesztés** – mennyire tudatosan irányítod és ellenőrzöd az AI-t, és ez mennyire látszik az
   `AI_NAPLO.md`-ből és a git historyból.
4. **Bemutató** – mennyire érthetően mutatod be a folyamatot, a döntéseket és a programot.
5. **Kódminőség** – struktúra, olvashatóság, tesztek.
6. **Működés Dockerben** – egy paranccsal elindul-e tisztán.
7. **Felhasználói élmény** – feltöltés, visszajelzés, a diagram és a táblázat olvashatósága.
8. **Dokumentáció** – a döntések és a korlátok őszinte leírása.

Ajánlott időráfordítás: kb. 6–8 óra. Ha valamit nem sikerül befejezni, írd le a README-ben, mit csinálnál tovább.
