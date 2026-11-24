# Projekt főbb lépései

## 1. lépés - Környezet inicializálása
- Felraktam a React-et, Tailwind-et, FastAPI-t és a pdfplumber-t. Valamint felállítottam a docker konténereket.

## 2. lépés - Teljes rendszer megtervezése
- Claude-nak beadtam az általatok biztosított [FELADAT.md](./FELADAT.md) fájlt, amiből kérdéseket, nem egyértelmű részeket gyűjtettem össze: [TERV-KERDESEK.md](./TERV-KERDESEK.md).
```
Olvasd át a teljes @FELADAT.md feladatleíró markdown fájlt! Ez alapján tervezd meg a leírt alkalmazást! A projekt megtervezése során felmerülő kérdéseket és azokat a döntéseket, amiket nekem kellene meghoznom, gyűjtsd össze egy TERV-KERDESEK.md fájlba a gyökérkönyvtárba!
```
- Majd ezekre válaszoltam, és a megválaszolt kérdések alapján megterveztettem architektúrálisan a projektet.
```
Megválaszoltam az összes kérdést a @TERV-KERDESEK.md fájlban. Nézd át, és az alapján készítsd el a teljes rendszertervet a gyökérbe, RENDSZERTERV.md néven! Emellett a CLAUDE.md szabályfájlt is készítsd el a @TERV-KERDESEK.md fájlban megbeszéltek alapján!
```
- Így keletkezett az [RENDSZERTERV.md](./RENDSZERTERV.md) fájl, amit átolvastam, némileg javítottam.
- Azért ezzel a lépéssel kezdtem, mert így az LLM megismerte, és  már teljesen átgondolta az egész projektet. Így ha a későbbiekben egyesével is fejlesztem le a főbb részeket, akkor is a big picture tudatában lesz, és az alapján dolgozik a kisebb részeken is.

## 3. lépés - Adatmodellek, adatbázis és konfiguráció létrehozása
#### Megvalósított fájlok: `config.py`, `db.py`, `models.py`, `schemas.py`, `main.py`.
- Konfiguráció: Pydantic `BaseSettings` alapú környezeti változó kezelés üres értékek figyelmen kívül hagyásával
- Egységes OpenAI-kompatibilis `LlmConfig`
- Adatbázis: SQLite táblák inicializálása
- Sémák és belépési pont implementálása

## 4. lépés - Normalizálók implementálása
#### Megvalósított fájlok: `normalize.py`.
- Szöveg- és címketisztítás
- Többnyelvű dátumkezelés
- Összeg és adószám normalizálás
- Azonosítók és devizák
- A 100 számlára lefuttatott teszt során a NWS/2026/0044 számla hibás lett, mivel a fejlécében összecsúsztak a blokkok. Ezt a PDF feldolgozóban majd kezelni kell.

## 5. lépés - Számlák kinyeréséhez használt ellenörző fájl
#### Elkészítettem az [expected.json](/backend/tests/expected.json) fájlt, amiben 15 darab különböző nyelvű és felépítésű számlának helyes adatait írtam ki kézzel, hogy ezzel hasonlíthassam össze az app által feldolgozott számlák kimenetét.

## 6. lépés - PDF szövegkinyerés és szabályalapú mezőkinyerés
#### Megvalósított fájlok: `pdf_text.py`, `layout.py`, `labels.py`, `doctype.py`, `rules.py`, `dump_extraction.py`.
- Koordinátaalapú szövegkinyerés: szavak, sorok és szegmensek kinyerése pozícióval
- Elrendezés és címkeillesztés: Címke–érték párosítás ugyanabban a szegmensben, a jobbra lévő szegmensben vagy a kétoszlopos fejléc oszlopa alatti legközelebbi sorban.
- Dokumentumtípus felismerés: Jóváíró, díjbekérő és előlegszámla azonosítása kizárólag a fejlécben keresve
- Szabályalapú kinyerő és debug eszköz: Felek azonosítása szövegblokkok alapján, irány meghatározása, a bruttó végösszeg kiválasztása a nettó + ÁFA matematikai egyezés alapján

## 7. lépés - 
- 



## Szabályfájl
#### Készítettem egy [CLAUDE.md](/CLAUDE.md) szabályfájlt, amiben rögzítettem a következő szabályokat:
- Kötelező kontextus
- Nyelv
- Tiltások
- Üzleti szabályok
- Kódolási szabályok
- Tesztelés és ellenőrzés
- Parancsok
- Munkamenet