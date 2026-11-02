# Registrace webu ve vyhledávačích (pokyny pro majitele)

Nic z toho se neděje automaticky; je to jednorázová práce majitele domény `meteoverdict.cz`.
Sitemapa je `https://meteoverdict.cz/sitemap.xml` (index: `sitemap-pages.xml`, `sitemap-okresy.xml`,
`sitemap-obce.xml`; obce s méně než 500 obyvateli jsou `noindex` a v sitemapě nejsou).

## Google Search Console
1. https://search.google.com/search-console → Přidat vlastnost → **Doména** `meteoverdict.cz`.
2. Ověření DNS záznamem TXT u správce domény (jednou, pokryje http/https/www i podadresy).
3. Sitemapy → přidat `sitemap.xml`. Google si z indexu načte všechny tři soubory.
4. Kontrola URL: `/`, `/predpoved/`, jedna stránka okresu a jedna obce → „Požádat o indexaci“.
5. Po 3–7 dnech: Stránky (pokrytí), Core Web Vitals, hreflang v „Mezinárodní cílení“ už Google nemá; stačí, aby nehlásil chyby u sitemap.

## Bing Webmaster Tools
1. https://www.bing.com/webmasters → **Importovat z Google Search Console** (jedno kliknutí po ověření v GSC).
2. Zkontrolovat, že se načetl `sitemap.xml`. Volitelně IndexNow (urychlí indexaci po denní aktualizaci).

## Seznam Webmaster
1. https://search.seznam.cz/webmaster → přidat web `https://meteoverdict.cz`, ověřit meta značkou nebo souborem.
2. Odeslat `sitemap.xml`. Seznam hůř vykresluje JavaScript, proto jsou stránky okresů a obcí čisté HTML.

## Po spuštění sledovat
- GSC → Stránky: „Odeslané a indexované“ má růst na ~3 000 (okresy + obce od 500 obyvatel); „Vyloučeno značkou noindex“ jsou malé obce, záměrně.
- Až bude většina velkých obcí indexovaná a bude mít zobrazení, snížit `INDEX_MIN_POPULATION` v `web/scripts/places.mjs`.
