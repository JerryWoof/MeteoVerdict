// The text of the Data page (data.html) below the okres picker, as two lists of blocks (the API
// part and the rest) for info-page.js's renderBlocks (one function for both languages: L(cs, en)). The times come
// from schedule.js (checked against the workflows); licences from docs/licensing.md.

const REPO = "https://github.com/JerryWoof/MeteoVerdict";
const SITE = "https://jerrywoof.github.io/MeteoVerdict";
const BY = "https://creativecommons.org/licenses/by/4.0/";
const BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/";

const release = (tag) => `[${tag}](${REPO}/releases/tag/${tag})`;
const releases = (label, query) => `[${label}](${REPO}/releases?q=${query})`;

/** @param {"cs"|"en"} language @param {{outlook: string, daily: string, runs: string, chmi: string, sun: string, zone: string}} c Prague clock times */
export function dataBlocks(language, c) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  const all = [
    ["h", L("Kdy se co aktualizuje", "When what is updated"), "schedule"],
    ["table", {
      head: [L("Co", "What"), L("Kdy (pražský čas, teď " + c.zone + ")", "When (Prague time, now " + c.zone + ")")],
      rows: [
        [L("Předpověď okresů: `api/v1`, `outlook.json`, předpovědi jednotlivých modelů", "Forecast of the okresy: `api/v1`, `outlook.json`, every model's forecast"),
          L(`4× denně v ${c.outlook}`, `4 times a day at ${c.outlook}`)],
        [L("Skóre a pořadí modelů (`models` v `api/v1`, `meta.json`, `leads.json`, `blend-test.json`, `blend-interval.json`), release `data-latest`", "Scores and ranking of the models (`models` in `api/v1`, `meta.json`, `leads.json`, `blend-test.json`, `blend-interval.json`), release `data-latest`"),
          L(`denně v ${c.daily}`, `daily at ${c.daily}`)],
        [L("Opravy slunečního svitu, oblačnosti a nárazů", "Sunshine, cloud and gust corrections"), L(`denně v ${c.sun}`, `daily at ${c.sun}`)],
        [L("Samostatné běhy modelů na stanicích (`runs-*`)", "Single model runs at the stations (`runs-*`)"), L(`4× denně v ${c.runs}`, `4 times a day at ${c.runs}`)],
        [L("Archiv stanic ČHMÚ (`chmi-*`)", "ČHMÚ station archive (`chmi-*`)"), L(`2× denně v ${c.chmi}`, `twice a day at ${c.chmi}`)],
        [L("Archiv ALADIN (`aladin-*`)", "ALADIN archive (`aladin-*`)"), L("každé 3 hodiny, přibývají hotové běhy", "every 3 hours, finished runs are added")],
        [L("Radar a družice (větev `radar-live`)", "Radar and satellite (branch `radar-live`)"), L("nové snímky každých 5 minut; archiv `radar-*` a `satellite-*` každých 6 hodin", "new frames every 5 minutes; the `radar-*` and `satellite-*` archives every 6 hours")],
        [L("Experimentální AI předpověď a heatmapa (`data/scores/ai/`, release `ai-latest`)", "Experimental AI forecast and heatmap (`data/scores/ai/`, release `ai-latest`)"),
          L("denně od 08:30 (hotovo kolem 09:15); na webu po dalším sestavení stránek", "daily from 08:30 (done by about 09:15); on the site after the next page build")],
      ],
    }],
    ["note", L(
      "Jde o plánovaný začátek: GitHub Actions spouští úlohy s proměnlivým zpožděním (v říjnu 2026 občas i několik hodin) a výpočet pak trvá desítky minut. Čas poslední aktualizace je v záhlaví stránky a v poli `generated` každého souboru. Čas ani dostupnost nezaručujeme (bez SLA).",
      "These are the scheduled start times: GitHub Actions starts jobs with a variable delay (sometimes several hours in October 2026) and the computation then takes tens of minutes. The time of the last update is in the page header and in the `generated` field of every file. We do not guarantee timing or availability (no SLA).")],

    ["h", L("API v1: předpověď a pořadí modelů po okresech", "API v1: forecast and model ranking by okres"), "api"],
    ["p", L(
      "Statické soubory na GitHub Pages: zdarma, bez klíče a registrace, CORS povolený. Struktura `v1` se nemění zpětně nekompatibilně; zastaralá pole se oznamují v poli `deprecated`.",
      "Static files on GitHub Pages: free, no key or registration, CORS allowed. The `v1` layout does not change in a backwards-incompatible way; deprecated fields are announced in the `deprecated` field.")],
    ["table", {
      head: [L("Soubor", "File"), L("Obsah", "Contains")],
      rows: [
        [`[api/v1/index.json](${SITE}/api/v1/index.json)`, L("Seznam všech 77 okresů s kódem, názvem, bodem předpovědi a adresami jejich souborů, čas vytvoření, licence a `notice`.", "All 77 okresy with code, name, forecast point and the addresses of their files, time of creation, licence and `notice`.")],
        ["`api/v1/okresy/{code}.json`", L("Vše pro jeden okres (pole níže), např. [CZ0201](" + SITE + "/api/v1/okresy/CZ0201.json).", "Everything for one okres (fields below), e.g. [CZ0201](" + SITE + "/api/v1/okresy/CZ0201.json).")],
        ["`api/v1/okresy/{code}.csv`", L("Hodinová předpověď jako tabulka: `time_utc`, `temperature_2m`, `precipitation`, `wind_speed_10m`, `cloud_cover`, `sunshine_duration`, `temperature_2m_lo`, `temperature_2m_hi`. Bez příznaků prahů, pro Excel a Google Sheets.", "The hourly forecast as a table: `time_utc`, `temperature_2m`, `precipitation`, `wind_speed_10m`, `cloud_cover`, `sunshine_duration`, `temperature_2m_lo`, `temperature_2m_hi`. No threshold flags; for Excel and Google Sheets.")],
      ],
    }],
    ["table", {
      head: [L("Pole v souboru okresu", "Field in an okres file"), L("Význam", "Meaning")],
      rows: [
        ["`okres`", L("Kód okresu (LAU 1, např. CZ0201), název a bod, pro který je předpověď.", "Okres code (LAU 1, e.g. CZ0201), name and the point the forecast is for.")],
        ["`forecast.hourly`", L("`time` (UTC) a hodinové řady `temperature_2m` (°C), `precipitation` (mm za hodinu končící v daném čase), `wind_speed_10m` (m/s), `cloud_cover` (%), `sunshine_duration` (s za hodinu). Oblačnost a svit jsou průměr modelů opravený podle pozorování ČHMÚ. **temperature_2m_lo, temperature_2m_hi** (°C): 80% rozpětí kolem teploty („±“ v grafu) z chyb naší předpovědi za posledních 30 dní; chybí, dokud se nespočítá.", "`time` (UTC) and the hourly series `temperature_2m` (°C), `precipitation` (mm in the hour ending at the time), `wind_speed_10m` (m/s), `cloud_cover` (%), `sunshine_duration` (s per hour). Cloud cover and sunshine are the mean of the models corrected against ČHMÚ observations. **temperature_2m_lo, temperature_2m_hi** (°C): the 80 % range around the temperature (the “±” in the chart) from the errors of our forecast over the last 30 days; absent until computed.")],
        ["`forecast.parts`", L("Souhrn po dnech a částech dne v pražském čase (`night`, `morning`, `afternoon`, `evening`, `day`): `tmin`, `tmax`, srážky, `rain_probability`, vítr, oblačnost, svit, `symbol`, východ a západ slunce, `heavy_rain_probability`. **Prahy MeteoVerdictu** (ano/ne, `null`, kde nejsou data): `heavy_rain` (aspoň 5 mm za období), `frost` a `ground_frost` (noční minimum, přízemní mrazík), `gust_over_threshold` (náraz aspoň 13,5 m/s; `gust_warning` je zastaralý alias, zmizí v příští verzi API). **Nejde o výstrahy ČHMÚ**, ty vydává jen [ČHMÚ](https://www.chmi.cz/).", "Summary by day and part of day in Prague time (`night`, `morning`, `afternoon`, `evening`, `day`): `tmin`, `tmax`, precipitation, `rain_probability`, wind, cloud, sunshine, `symbol`, sunrise and sunset, `heavy_rain_probability`. **MeteoVerdict thresholds** (yes/no, `null` where there are no data): `heavy_rain` (at least 5 mm in the period), `frost` and `ground_frost` (night minimum, ground frost), `gust_over_threshold` (gust of at least 13.5 m/s; `gust_warning` is a deprecated alias, removed in the next API version). **They are not ČHMÚ warnings**; only [ČHMÚ](https://www.chmi.cz/) issues those.")],
        ["`models.variables`", L("Pro teplotu, vítr a srážky (denní i 06–06) a předstih `lead_days` 1 až 5: modely podle chyby za posledních 90 dní, s `rank`, `mae`, `bias`, `rmse`, `days`, `weight` a `correction` v naší předpovědi a `mos_weight` (váha v regresi teploty a větru). **p_best** je pravděpodobnost, že je model nejlepší (podíl blokových bootstrapových přepočtů, kde má nejnižší MAE); pod 0,6 u vedoucího nejde o jasného vítěze. `tied_with_best`: statisticky stejně dobrý jako nejlepší; `small_sample`: méně než 30 dní; `short_record`: nový model, neřadí se.", "For temperature, wind and precipitation (daily and 06–06) and the lead `lead_days` 1 to 5: the models by error over the last 90 days, with `rank`, `mae`, `bias`, `rmse`, `days`, `weight` and `correction` in our forecast and `mos_weight` (weight in the temperature and wind regression). **p_best** is the probability of being the best model (the share of block-bootstrap resamples in which it has the lowest MAE); below 0.6 for the leader there is no clear winner. `tied_with_best`: statistically as good as the best; `small_sample`: fewer than 30 days; `short_record`: a new model, not ranked.")],
        ["`licence`, `attribution`, `notice`", L("Licence, text ke zdroji a upozornění, že prahy nejsou výstrahy ČHMÚ.", "Licence, the text to credit and the notice that thresholds are not ČHMÚ warnings.")],
      ],
    }],

    ["h", L("Další soubory na webu", "More files on the site"), "files"],
    ["p", L(
      "Čtou je stránky webu, jsou veřejné, ale na rozdíl od `api/v1` se jejich struktura může změnit. Základ adresy: `" + SITE + "/data/scores/`.",
      "The pages of the site read them; they are public but, unlike `api/v1`, their layout may change. Base address: `" + SITE + "/data/scores/`.")],
    ["table", {
      head: [L("Soubor", "File"), L("Obsah", "Contains")],
      rows: [
        ["`outlook.json`, `outlook-hourly.json`", L("Předpověď všech okresů v jedné tabulce (`columns`, `rows`): po částech dne a po hodinách.", "The forecast of all okresy in one table (`columns`, `rows`): by part of day and hourly.")],
        ["`forecast/models/{code}.json`", L("Hodinová předpověď každého modelu pro okres tak, jak ji dala Open-Meteo (bez naší korekce), a naše kombinace; `licence` a `attribution` v souboru.", "Every model's hourly forecast for an okres as Open-Meteo gave it (without our correction), and our combination; `licence` and `attribution` in the file.")],
        ["`forecast/models-parts/{model}.json`, `index.json`", L("Části dne a dny jednoho modelu pro všech 77 okresů (přepínač modelů na mapě předpovědi).", "Parts of day and days of one model for all 77 okresy (the model switch of the forecast map).")],
        ["`station-fc/{station}.json`, `index.json`", L("Předpověď každého modelu a blendu v bodě stanice po dnech (D+1, D+2, posledních 35 dní) vedle naměřeného, pro asi 300 stanic: `obs` a `series[veličina][předstih][model]` (`tmax`, `tmin`, `r`, `wind`, `gust`). Výběr modelu na stránce Naměřeno. AI zde zatím není.", "Every model's and the blend's forecast at the station point by day (D+1, D+2, the last 35 days) next to the measured values, for about 300 stations: `obs` and `series[value][lead][model]` (`tmax`, `tmin`, `r`, `wind`, `gust`). The model selector of the Measured page. No AI here yet.")],
        ["`meta.json`, `leads.json`, `blend-test.json`, `rain-calibration.json`", L("Seznam modelů a oken, chyby podle předstihu, denní test, zda kombinace poráží nejlepší model, a kalibrace srážek.", "The models and windows, errors by lead time, the daily test of whether the combination beats the best model, and the rain calibration.")],
        ["`ai/ai.json`, `ai/ai-forecast.json`", L("**Experimentální MeteoVerdict AI.** `ai.json`: stav, pravidlo ověřování, skóre a validace; započítává se jen od spuštění 2026-10-19. `ai-forecast.json`: hodinová předpověď AI po okresech.", "**Experimental MeteoVerdict AI.** `ai.json`: status, the rule of the verification, scores and validation; counted only from the launch on 2026-10-19. `ai-forecast.json`: the AI's hourly forecast by okres.")],
        ["`ai/fc/outlook.json`, `ai/fc/verify/{code}.json`, `ai/fc/compare/`", L("Úplná předpověď AI po částech dne: hodnoty, které AI předpovídá sama (teplota, vítr, nárazy, oblačnost, slunění, symbol), doplněné blendem MeteoVerdict (srážky, mráz a další); `sources` v souboru říká u každé veličiny `ai` nebo `blend`. Dále její porovnání s pozorováním po okresech a pořadí vedle ostatních modelů.", "The complete AI forecast by part of day: the values the AI forecasts itself (temperature, wind, gusts, cloud, sunshine, symbol), filled in with the MeteoVerdict blend (rain, frost and more); `sources` in the file says `ai` or `blend` for each value. Also its comparison with observations by okres, and the ranking next to the other models.")],
        ["`ai/fc/heat/`, `ai/fc/temp100m/`", L("Podklady **heatmapy** teploty s rozlišením 100 m (`index.json` a PNG mřížky; teplotu pro hodinu skládá prohlížeč) a mapy po částech dne.", "The inputs of the **heatmap** of temperature at 100 m resolution (`index.json` and PNG grids; the browser composes the temperature for an hour) and the maps by part of day.")],
      ],
    }],
    ["note", L(
      "AI výstupy jsou experiment: nejsou oficiální předpověď a nemají záruku. Soubory AI zatím nenesou pole `licence` a `attribution`; platí CC BY-SA 4.0 jako u ostatních našich výstupů; uvádějte zdroje níže.",
      "The AI outputs are an experiment: not an official forecast and without a guarantee. The AI files do not yet carry `licence` and `attribution` fields; CC BY-SA 4.0 applies, as for our other outputs; credit the sources below.")],

    ["h", L("Soubory ke stažení: releasy na GitHubu", "Downloads: releases on GitHub"), "releases"],
    ["p", L(
      `Velké soubory jsou v [releasech repozitáře](${REPO}/releases) (Parquet, JSON, ZIP, TAR), každý do 2 GiB. Formát je popsán v [dokumentaci](${REPO}/blob/main/docs/data-sources.md).`,
      `Large files are in the [releases of the repository](${REPO}/releases) (Parquet, JSON, ZIP, TAR), each up to 2 GiB. The formats are described in the [documentation](${REPO}/blob/main/docs/data-sources.md).`)],
    ["table", {
      head: [L("Release", "Release"), L("Obsah", "Contains"), L("Licence", "Licence")],
      rows: [
        [release("data-latest"), L("Měřené hodnoty, archivované předpovědi na stanicích a denní skóre (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), váhy modelů, `blend-interval.json` (rozpětí „±“), `frost.json`, `compare.zip`, `outlook*.zip`, `site-data.zip`. Starší měsíce: " + releases("data-YYYY-MM", "data-20") + ".", "Observed values, archived forecasts at the stations and daily scores (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), model weights, `blend-interval.json` (the “±” range), `frost.json`, `compare.zip`, `outlook*.zip`, `site-data.zip`. Older months: " + releases("data-YYYY-MM", "data-20") + "."), L("CC BY-SA 4.0", "CC BY-SA 4.0")],
        [release("data-latest") + L(": `station-data.zip`", ": `station-data.zip`"), L("Stránky stanic (jen data ČHMÚ).", "The station pages (ČHMÚ data only)."), L("CC BY 4.0, ČHMÚ", "CC BY 4.0, ČHMÚ")],
        [release("data-latest") + L(": `station-fc.zip`", ": `station-fc.zip`"), L("Předpověď každého modelu v bodě stanice po dnech (D+1, D+2, 35 dní) vedle naměřeného, pro asi 300 stanic.", "Every model's forecast at the station point by day (D+1, D+2, 35 days) next to the measured values, for about 300 stations."), "CC BY-SA 4.0"],
        [release("ai-latest"), L("`ai.zip`: soubory `ai/` výše, denně nové.", "`ai.zip`: the `ai/` files above, new every day."), "CC BY-SA 4.0"],
        [releases("runs-YYYY-MM", "runs-20"), L("Samostatné běhy modelů na asi 300 stanicích, jeden Parquet za měsíc.", "Single model runs at about 300 stations, one Parquet per month."), "CC BY-SA 4.0"],
        [releases("outlook-models-YYYY-MM", "outlook-models") + ", " + release("outlook-archive"), L("Celá odpověď modelů při každém běhu předpovědi, jeden Parquet za den; průměry oblačnosti a svitu.", "Every model's whole answer at each forecast run, one Parquet per day; the means of cloud and sunshine."), "CC BY-SA 4.0"],
        [releases("aladin-YYYY-MM", "aladin-20"), L("ALADIN ČHMÚ ve stanicích, jeden Parquet na běh modelu.", "ČHMÚ's ALADIN at the stations, one Parquet per model run."), L("CC BY 4.0, ČHMÚ", "CC BY 4.0, ČHMÚ")],
        [releases("chmi-YYYY", "chmi-") + L(" a ", " and ") + release("chmi-now-2026"), L("Všechny prvky všech klimatologických stanic ČHMÚ (10 minut až rok, jevy) jako Parquet.", "Every element of every ČHMÚ climatological station (10 minutes to a year, phenomena) as Parquet."), L("CC BY 4.0, ČHMÚ; hodnoty beze změny", "CC BY 4.0, ČHMÚ; values unchanged")],
        [releases("radar-YYYY-MM", "radar-20"), L("Radarové složeniny ČHMÚ (TAR na produkt a den), hodinové srážky MERGE, snímky radarové stránky.", "ČHMÚ radar composites (a TAR per product and day), hourly MERGE precipitation, the radar page's frames."), L("CC BY 4.0, ČHMÚ", "CC BY 4.0, ČHMÚ")],
        [releases("satellite-YYYY-MM", "satellite-20"), L("Snímky Meteosatu z ČHMÚ (TAR na produkt, oblast a den, po 15 minutách).", "Meteosat images from ČHMÚ (a TAR per product, region and day, every 15 minutes)."), L("CC BY 4.0, EUMETSAT a ČHMÚ", "CC BY 4.0, EUMETSAT and ČHMÚ")],
        [`[radar-live](${REPO}/tree/radar-live)`, L("Větev s aktuálními snímky radaru a družice (posledních několik hodin), přepisuje se každých 5 minut.", "A branch with the current radar and satellite frames (the last few hours), replaced every 5 minutes."), L("CC BY 4.0, ČHMÚ a EUMETSAT", "CC BY 4.0, ČHMÚ and EUMETSAT")],
      ],
    }],
    ["p", L(
      "**Neveřejný archiv.** Sami si ukládáme i vstupy, které poskytovatelé po pár dnech mažou: ALADIN (celé GRIB včetně tlakových hladin), ECMWF IFS a AIFS (výřez střední Evropy), běhy modelů z otevřeného bucketu Open-Meteo, radarové objemy, radiosondáže a profily větru ČHMÚ. Ke stažení zatím nejsou; licence zdrojů (CC BY 4.0) jejich sdílení dovoluje. Zájem nám napište: [Spolupráce](collaboration.html).",
      "**Private archive.** We also keep inputs that the providers delete after a few days: ALADIN (the full GRIB files with pressure levels), ECMWF IFS and AIFS (cropped to central Europe), model runs from Open-Meteo's open-data bucket, radar volumes, radiosondes and wind profiles from ČHMÚ. They are not available for download yet; the licences of the sources (CC BY 4.0) allow sharing them. If you are interested, write to us: [Collaboration](collaboration.html).")],

    ["h", L("Licence a zdroje", "Licences and sources"), "licences"],
    ["p", L(
      `Podrobnosti a důkazy jsou v [docs/licensing.md](${REPO}/blob/main/docs/licensing.md). Každý soubor v \`api/v1\` nese licenci a text ke zdroji.`,
      `Details and evidence are in [docs/licensing.md](${REPO}/blob/main/docs/licensing.md). Every file in \`api/v1\` carries the licence and the text to credit.`)],
    ["table", {
      head: [L("Zdroj", "Source"), L("Licence", "Licence"), L("Co uvést", "What to credit")],
      rows: [
        [L("ČHMÚ: měření stanic, ALADIN, radar, snímky družice (opendata.chmi.cz)", "ČHMÚ: station observations, ALADIN, radar, satellite images (opendata.chmi.cz)"), `[CC BY 4.0](${BY})`, L("ČHMÚ; u snímků družice také „contains modified EUMETSAT Meteosat data 2026“", "ČHMÚ; for satellite images also “contains modified EUMETSAT Meteosat data 2026”")],
        [L("Open-Meteo.com: modely přes API a otevřený bucket", "Open-Meteo.com: models via the API and the open-data bucket"), `[CC BY 4.0](${BY})`, L("Open-Meteo.com s odkazem. **Bezplatně jen pro nekomerční užití**: web i soubory jsou nekomerční; pro komerční použití nás nejdřív kontaktujte, aby se ověřily podmínky zdrojů", "Open-Meteo.com with a link. **Free only for non-commercial use**: the site and files are non-commercial; for commercial use contact us first so the terms of the sources can be checked")],
        ["ECMWF (IFS, AIFS), DWD (ICON), KNMI, DMI, GeoSphere Austria", `[CC BY 4.0](${BY})`, L("poskytovatel modelu", "the model's provider")],
        ["UK Met Office", `[CC BY-SA 4.0](${BY_SA})`, L("poskytovatel a **ShareAlike**: odvozená data musí mít stejnou licenci, proto jsou naše kombinované soubory CC BY-SA", "the provider and **ShareAlike**: derived data must carry the same licence, which is why our combined files are CC BY-SA")],
        ["NOAA (GFS, AIGFS)", L("volné dílo USA", "US government work"), L("poskytovatel (ze slušnosti)", "the provider (as a courtesy)")],
        ["Météo-France (ARPEGE)", "Licence Ouverte 2.0", "Météo-France"],
        ["ECCC (GEM), JMA (GSM), CMA (GRAPES)", L("licence ECCC; podmínky JMA (slučitelné s CC BY 4.0); CC BY 4.0 podle Open-Meteo", "ECCC licence; JMA terms (compatible with CC BY 4.0); CC BY 4.0 per Open-Meteo"), L("Environment and Climate Change Canada; Japan Meteorological Agency; China Meteorological Administration", "Environment and Climate Change Canada; Japan Meteorological Agency; China Meteorological Administration")],
        [L("Hranice okresů a krajů, obce (ČÚZK)", "Okres and kraj boundaries, municipalities (ČÚZK)"), `[CC BY 4.0](${BY})`, "ČÚZK"],
      ],
    }],
    ["table", {
      head: [L("Naše výstupy", "Our outputs"), L("Licence", "Licence")],
      rows: [
        [L("`api/v1`, předpovědi, skóre a pořadí, výstupy AI, `runs-*`, `outlook-*`", "`api/v1`, forecasts, scores and rankings, AI outputs, `runs-*`, `outlook-*`"), `[CC BY-SA 4.0](${BY_SA})`],
        [L("Archivy jen s daty ČHMÚ (`aladin-*`, `chmi-*`, radar, stránky stanic) a družicí", "Archives with ČHMÚ data only (`aladin-*`, `chmi-*`, radar, the station pages) and satellite"), `[CC BY 4.0](${BY})`],
        [L("Kód", "Code"), `[MIT](${REPO}/blob/main/LICENSE)`],
      ],
    }],

    ["h", L("Jak citovat", "How to cite"), "cite"],
    ["p", L(
      "Stačí zkopírovat pole `attribution` ze souboru, nebo použít tuto větu:",
      "Copy the `attribution` field of the file, or use this sentence:")],
    ["code", L(
      `MeteoVerdict: předpověď a pořadí modelů pro okresy ČR, ${SITE}/ (CC BY-SA 4.0). Měření: ČHMÚ (CC BY 4.0). Modely: Open-Meteo.com (CC BY 4.0) od DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, KNMI, DMI, ČHMÚ, ECCC, JMA, CMA a UK Met Office (CC BY-SA 4.0). Údaje byly kombinovány a opraveny.`,
      `MeteoVerdict: forecast and ranking of the models for the okresy of Czechia, ${SITE}/ (CC BY-SA 4.0). Observations: ČHMÚ (CC BY 4.0). Models: Open-Meteo.com (CC BY 4.0) from DWD, ECMWF, NOAA, Météo-France, GeoSphere Austria, KNMI, DMI, ČHMÚ, ECCC, JMA, CMA and the UK Met Office (CC BY-SA 4.0). The values were combined and corrected.`)],
    ["p", L(
      "Jednotlivé archivy (radar, družice, ČHMÚ, ALADIN) mají zdroj v popisu releasu; opište ho. Neříkejte, že data schvaluje ČHMÚ, Open-Meteo nebo poskytovatel modelu.",
      "The individual archives (radar, satellite, ČHMÚ, ALADIN) have their credit in the release notes; copy it. Do not imply that ČHMÚ, Open-Meteo or a model provider endorses the data.")],

    ["h", L("Podmínky", "Terms"), "terms"],
    ["p", L(
      "Prosíme, stahujte nejvýš jednou za hodinu: předpověď se mění jen čtyřikrát denně.",
      "Please fetch at most once an hour: the forecast changes only four times a day anyway.")],
    ["p", L(
      "Předpověď je statistická kombinace modelů, ne oficiální předpověď ČHMÚ; zda je lepší než nejlepší jednotlivý model, zpětně ověřujeme každý den na stránce [Porovnání](compare.html). Prahy (mráz, přízemní mrazík, vydatný déšť, nárazy) nejsou výstrahy: oficiální výstrahy vydává jen [ČHMÚ](https://www.chmi.cz/). Za použití dat neručíme.",
      "The forecast is a statistical combination of models, not an official ČHMÚ forecast; whether it beats the best single model is tested every day on the [Compare](compare.html) page. The thresholds (frost, ground frost, heavy rain, gusts) are not warnings: only [ČHMÚ](https://www.chmi.cz/) issues official warnings. Use the data at your own risk.")],
  ];
  const split = all.findIndex((block) => block[2] === "files");
  return { api: all.slice(0, split), more: all.slice(split) };
}
