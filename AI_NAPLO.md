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
- Így keletkezett a [RENDSZERTERV.md](./RENDSZERTERV.md) fájl, amit átolvastam, némileg javítottam.
- Azért ezzel a lépéssel kezdtem, mert így az LLM megismerte, és  már teljesen átgondolta az egész projektet. Így ha a későbbiekben egyesével is fejlesztem le a főbb részeket, akkor is a big picture tudatában lesz, és az alapján dolgozik a kisebb részeken is.

## 3. lépés - Szabályfájl elkészítése
#### Készítettem egy [CLAUDE.md](/CLAUDE.md) szabályfájlt, amiben rögzítettem a következő szabályokat:
- Kötelező kontextus
- Nyelv
- Tiltások
- Üzleti szabályok
- Kódolási szabályok
- Tesztelés és ellenőrzés
- Parancsok
- Munkamenet

## Megjegyzés:
- A későbbiekben a [RENDSZERTERV.md](./RENDSZERTERV.md) alapján haladtam tovább a fejlesztéssel. A főbb lépéseket egyesével implementáltam a Claude segítségével, minden egyes lépés végén pedig átnéztem az elkészült részt, majd javítottam/elfogadtam.

## 3. lépés - Adatmodellek, adatbázis és konfiguráció létrehozása
#### Megvalósított fájlok: `config.py`, `db.py`, `models.py`, `schemas.py`, `main.py`.
- A Claude által javasolt Pydantic BaseSettings konfigurációt és az egységes OpenAI-kompatibilis LlmConfig interfészt elfogadtam, így a tartalék LLM szolgáltató bármikor cserélhető vagy kikapcsolható.

## 5. lépés - Normalizálók implementálása
#### Megvalósított fájlok: `normalize.py`.
- A 100 számlára lefuttatott teszt során a NWS/2026/0044 számla hibás lett, mivel a fejlécében összecsúsztak a blokkok. Ezt a PDF feldolgozóban a későbbiekben kezeltem.

## 6. lépés - Számlák kinyeréséhez használt ellenörző fájl
#### Elkészítettem az [expected.json](/backend/tests/expected.json) fájlt, amiben 15 darab különböző nyelvű és felépítésű számlának helyes adatait írtam ki kézzel, hogy ezzel hasonlíthassam össze az app által feldolgozott számlák kimenetét.

## 7. lépés - PDF szövegkinyerés és szabályalapú mezőkinyerés
#### Megvalósított fájlok: `pdf_text.py`, `layout.py`, `labels.py`, `doctype.py`, `rules.py`, `dump_extraction.py`.
- Koordinátaalapú szövegkinyerés: szavak, sorok és szegmensek kinyerése pozícióval
- Elrendezés és címkeillesztés: Címke–érték párosítás ugyanabban a szegmensben, a jobbra lévő szegmensben vagy a kétoszlopos fejléc oszlopa alatti legközelebbi sorban.
- Dokumentumtípus felismerés: Jóváíró, díjbekérő és előlegszámla azonosítása kizárólag a fejlécben keresve
- Szabályalapú kinyerő és debug eszköz: Felek azonosítása szövegblokkok alapján, irány meghatározása, a bruttó végösszeg kiválasztása a nettó + ÁFA matematikai egyezés alapján
- Az [expected.json](/backend/tests/expected.json) fájllal való összehasonlító teszt is sikeresen lefut

## 8. lépés - Validáció, tartalék LLM feldolgozás és teljes kinyerési folyamat
#### Megvalósított fájlok: `validate.py`, `llm.py`, `llm_budget.py`, `pipeline.py`.
- Üzleti validáció és dátumpótlás: Ellenőrzések magyar hibaüzenetekkel és iránymeghatározással. Hiányzó teljesítési dátum esetén a kiállítás dátuma kerül behelyettesítésre, a hiányzó fizetési határidő pedig a fizetési feltételből számolódik
- OpenAI kompatibilis LLM-kliens: Egységes kliens, amely strukturált `json_schema` móddal indul, hálózati hibánál egyszer újrapróbál. A kimeneten sémavalidáció fut (a számlaszámnak és a végösszegnek szó szerint szerepelnie kell a PDF szövegében).
- Költségkontroll: Napi LLM-hívási keret ellenőrzése és hívásnaplózás az `llm_calls` táblába.
- Teljes kinyerési folyamat: `doctype` --> saját cég ellenőrzése --> szabályalapú kinyerés --> validáció --> LLM-tartalék (kizárólag hiba esetén) --> záróvalidáció lépése, `ok`, `review` vagy `rejected` végső státuszok.

## 9. lépés - MNB árfolyamlekérdezés, gyorsítótárazás és átváltás
#### Megvalósított fájlok: `mnb.py`, `fx.py`.
- MNB SOAP kliens és XML feldolgozás
- Adatbázis gyorsítótár
- Árfolyam-kiválasztás és visszatekintési ablak
- Forintosítás és pénzügyi kerekítés

## 10. lépés - Számlabefogadási folyamat, partnerkezelés, cash-flow riport és REST API végpontok
#### Megvalósított fájlok: `ingest.py`, `partners.py`, `report.py`, `deps.py`, `invoices.py`, `report.py`.
- Teljes befogadási és életciklus folyamat: `SHA-256 hash → kinyerési pipeline → duplikátum-ellenőrzés → partnerkezelés → MNB-árfolyam lekérés és forintosítás → mentés`
- Partnerazonosítás és összevonás
- Cash flow riport és összesítések: Kizárólag az `ok` státuszú számlákból épít lyukmentes havi idősort (a számla nélküli köztes hónapok `0` értékkel szerepelnek), forgalom szerint rendezi a partnereket, és visszaadja az egyes státuszok darabszámait.
- REST API végpontok


## 11. lépés - Frontend implementáció és adatvizualizáció
#### Megvalósított fájlok: `App.tsx`, `ConfirmDialog.tsx`, `UploadPanel.tsx`, `CashflowChart.tsx`, `PartnerTable.tsx`, `InvoiceTable.tsx`, `api.ts`, `types.ts`, `format.ts`, `labels.ts`, `frontend/package.json`.
- Kötegelt feltöltés és párhuzamosság: Drag-and-drop és tallózás alapú fájlfeltöltés egyszerre legfeljebb 4 párhuzamos kéréssel, fájlonkénti státuszikonnal és üzenettel, folyamatjelzővel, problémás fájlokra szűrhető naplóval, valamint a kimutatások 20 fájlonkénti és kötegvégi frissítésével
- Cash flow grafikon és partner kimutatás
- Számlalista: Keresés, szűrés státuszra/irányra/partnerre, fejlécre kattintós rendezés, valamint soronkénti PDF-megnyitás és törlés

## 12. lépés - Átnézés, végső tesztelés
- Átvizsgáltattam a teljes projektet Claude-dal, majd generáltattam egy tesztsegédletet ([TESZTELES.md](/TESZTELES.md)), aminek segítségével látványosan le lehet ellenőrizni az alkalmazás működését.
- Elkészítettem a [README.md](/README.md) fájlt is, amiben le van írva az indítás lépései,  röviden az architektúra, az alkalmazás működésének rövid ismertetése és a továbbfejlesztési ötletek.