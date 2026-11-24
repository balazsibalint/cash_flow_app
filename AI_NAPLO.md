# Projekt főbb lépései

## 1. lépés - Környezet inicializálása
- Felraktam a React-et, Tailwind-et, FastAPI-t és a pdfplumber-t. Valamint felállítottam a docker konténereket a frontend-nek és a backend-nek.

## 2. lépés - Teljes rendszer megtervezése
- Claude-nak beadtam az általatok biztosított [FELADAT.md](./FELADAT.md) fájlt, amiből kérdéseket, nem egyértelmű részeket gyűjtettem össze: [TERV-KERDESEK.md](./TERV-KERDESEK.md).
```
Olvasd át a teljes @FELADAT.md feladatleíró markdown fájlt! Ez alapján tervezd meg a leírt alkalmazást! A projekt megtervezése során felmerülő kérdéseket és azokat a döntéseket, amiket nekem kellene meghoznom, gyűjtsd össze egy TERV-KERDESEK.md fájlba a gyökérkönyvtárba!
```
- Majd ezekre válaszoltam, és a megválaszolt kérdések alapján megterveztettem architektúrálisan a projektet.
```
Megválaszoltam az összes kérdést a @TERV-KERDESEK.md fájlban. Nézd át, és az alapján készítsd el a teljes rendszertervet a gyökérbe, RENDSZERTERV.md néven! Emellett a CLAUDE.md szabályfájlt is készítsd el a @TERV-KERDESEK.md fájlban megbeszéltek alapján!
```
- Így keletkezett az [RENDSZERTERV.md](./RENDSZERTERV.md) fájl, amit átolvastam, esetlegesen javítottam.
- Azért ezzel a lépéssel kezdtem, mert így az LLM megismerte, és  már teljesen átgondolta az egész projektet. Így ha a későbbiekben egyesével is fejlesztem le a főbb részeket, akkor is a big picture tudatában lesz, és az alapján dolgozik a kisebb részeken is.

## 3. lépés - Adatmodellek, adatbázis és konfiguráció létrehozása
- **Megvalósított fájlok:** `config.py`, `db.py`, `models.py`, `schemas.py`, `main.py`.

## 4. lépés - 
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