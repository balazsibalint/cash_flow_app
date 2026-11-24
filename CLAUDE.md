# CLAUDE.md - Projektszabályok

Számlafeldolgozó és cash-flow kimutatás (Nordwind Solutions Kft.).
A feladat: [FELADAT.md](FELADAT.md) · Döntések: [TERV-KERDESEK.md](TERV-KERDESEK.md) · Terv: [RENDSZERTERV.md](RENDSZERTERV.md)

## Kötelező kontextus

- Minden munka előtt az **[RENDSZERTERV.md](RENDSZERTERV.md)** az irányadó. Ha el kell térni tőle, **előbb a tervet frissítsd**, és az eltérést jelezd a felhasználónak.
- A [TERV-KERDESEK.md](TERV-KERDESEK.md) K1–K16 döntései **kötelezőek**, nem kell őket újratárgyalni. Ha egy döntés megváltoztatása indokolt, kérdezz, ne dönts helyette.
- Ha a terv nem fed le egy kérdést, és a válasz a felhasználó döntése (üzleti szabály, UX, hatókör), **kérdezz**. A technikai részletekben dönts a terv szellemében.

## Nyelv

- **Felület, dokumentáció (README, tervek), hibaüzenetek a felhasználónak:** magyar.
- **Kód (azonosítók, fájlnevek, API-mezők):** angol.
- **Kódkommentek:** magyar, röviden; csak ott, ahol a „miért” nem nyilvánvaló.
- **Commit-üzenetek:** angol, felszólító mód, rövid tárgysor (pl. `Add multilingual date parser`).

## Tiltások (soha)

1. **Ne „drótozd be” a 100 minta-számlát.** Fájlnévre, konkrét partnernévre, számlaszám-formátumra vagy sablonra szabott elágazás tilos. Az egyetlen beégethető cégadat a saját cégünké, és az is csak a konfigurációból (`OWN_*`). Az általánosítás a cél, mert a kiértékelés ismeretlen számlákkal is történik.
2. **Fejlesztéshez a Gemini API kulcsot** használd.
3. **Titkok:** a `.env` soha nem kerülhet a repóba, kulcs nem kerülhet kódba, naplóba vagy válaszüzenetbe. A `.env` tartalmát ne írd ki; legfeljebb a kulcsok neveit.
4. **Az `expected.json` értékeit a felhasználó készíti, és mérvadók.** Soha ne módosítsd őket azért, hogy egy teszt átmenjen. Ha szerinted hibás egy érték, jelezd, és a felhasználó dönt.
5. **Az `AI_NAPLO.md`-t a felhasználó vezeti** – csak kifejezett kérésre szerkeszd. Ha valami naplóba illő történik (az AI tévedése, egy elvetett javaslat), szólj, hogy érdemes beírni.
6. **Az MNB-t ne terheld feleslegesen:** egy napot vagy devizát ne kérdezz le kétszer (a cache-t használd).
7. A számlán feltüntetett saját árfolyamot vagy forintos ÁFA-összeget soha ne használd végösszegként vagy árfolyamként.
8. Ne commitolj és ne pusholj kérés nélkül. Ne válts ágat; a fő ág a **`master`**.

## Üzleti szabályok (röviden, a részletek a tervben)

- **Irány:** a saját adószám (`26481937` törzs, belföldi vagy EU-s formában) helye dönti el: ha a kiállítónál van, kimenő, ha a vevőnél, bejövő.
- **Partnerkulcs:** a normalizált adószám (a magyar belföldi és közösségi adószám ugyanarra a kulcsra képződik: `HU` + 8 jegy).
- **Duplikáció:** fájl-hash, majd `seller_tax_key + invoice_number_norm`; ütközéskor **kihagyás** (K4).
- **Különleges bizonylatok** (jóváíró, sztornó, helyesbítő, díjbekérő, proforma, előleg), negatív végösszeg, és ha a mi cégünk egyik félként sem szerepel → `rejected`, sehova nem számít bele (K7).
- **Bizonytalan számla** → `review`, nem számít bele a kimutatásba (K5). Hiányzó teljesítés → a kiállítás dátuma; hiányzó határidő → kiállítás + fizetési feltétel, figyelmeztetéssel (K6).
- **Árfolyam:** a teljesítés napján vagy azelőtt közzétett legutolsó MNB-jegyzés, a `unit`-tal osztva; számlánként egész forintra kerekítve, `ROUND_HALF_UP`; az összesítés ezután jön. Ha nincs még jegyzés → ideiglenes (K8); ha az MNB nem érhető el → `pending_fx`, és a következő feltöltés újrapróbálja (K9).
- A kimutatásba **csak az `ok` státuszú** számlák számítanak bele.

## Kódolási szabályok

- **Pénz:** mindig `Decimal`, soha `float`. Az API-ban a pénzösszeg string, a `gross_huf` egész szám.
- **Rétegek:** az `api/` vékony (validáció, HTTP), a logika a `services/`-ben van; a kinyerés tiszta, DB-független függvényekből álljon, hogy tesztelhető legyen.
- **Hibaizoláció:** egy fájl feldolgozási hibája soha nem állíthatja le a szervert, és nem befolyásolhat más fájlokat; minden hiba ember által olvasható magyar üzenettel kerül a számlához.
- **A statikus frontend mountja** a `main.py`-ban a routerek **után** legyen.
- **Típusok:** Python type hintek; Pydantic-sémák az I/O-hoz. TypeScript strict; a `noUnusedLocals` miatt nem maradhat nem használt import (különben a build elbukik).
- **Függőségek:** új függőséget csak indokolt esetben vegyél fel, verzióval rögzítve; jelezd a felhasználónak.
- A teszt-PDF-ek mappája ne `invoices` nevű legyen (a `.gitignore` kizárja): `backend/tests/pdfs/`.

## Tesztelés és ellenőrzés

- **Minden változtatáshoz teszt** tartozik a kinyerés, az árfolyam-kiválasztás, az átváltás és az aggregáció területén.
- Mielőtt egy lépést késznek mondasz:
  1. `docker compose -f docker-compose.dev.yml run --rm app pytest -q` → zöld;
  2. `docker compose up --build -d`, majd `curl http://localhost:8080/api/health` → `ok`;
  3. a kinyerést érintő változásnál futtasd le a 100 minta-számlán is (debug szkripttel), és jelezd, ha bármelyik eredménye megváltozott.
- Az eredményekről őszintén számolj be: ha valami nem működik, vagy nem ellenőrizted, mondd ki.

## Parancsok

```powershell
# Éles futtatás (http://localhost:8080)
docker compose up --build

# Fejlesztés hot-reloaddal (backend :8000, frontend :5173)
docker compose -f docker-compose.dev.yml up --build

# Tesztek
docker compose -f docker-compose.dev.yml run --rm app pytest -q

# Frontend lint / build ellenőrzés
docker compose -f docker-compose.dev.yml run --rm frontend npm run build
```

## Munkamenet

- Kis, egy logikai lépést lefedő változtatások.
- A megvalósítás sorrendje a [RENDSZERTERV.md](RENDSZERTERV.md) 11. fejezete szerint halad.
- Egy lépés végén röviden foglald össze: mi változott, hogyan ellenőrizted, mi maradt nyitva.
