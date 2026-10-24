// The text of the Data page (data.html) below the okres picker, as two lists of blocks (the API
// part and the rest) for info-page.js's renderBlocks (one function for both languages: L(cs, en)). The times come
// from schedule.js (checked against the workflows); licences from docs/licensing.md.

const REPO = "https://github.com/JerryWoof/MeteoVerdict";
const SITE = "https://meteoverdict.cz";
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
        [L("Skóre a pořadí modelů (`meta.json`, `leads.json`, `blend-test.json`), release `data-latest`", "Scores and ranking of the models (`meta.json`, `leads.json`, `blend-test.json`), release `data-latest`"),
          L(`denně v ${c.daily}`, `daily at ${c.daily}`)],
        [L("Opravy slunečního svitu, oblačnosti a nárazů", "Sunshine, cloud and gust corrections"), L(`denně v ${c.sun}`, `daily at ${c.sun}`)],
        [L("Samostatné běhy modelů na stanicích (`runs-*`)", "Single model runs at the stations (`runs-*`)"), L(`4× denně v ${c.runs}`, `4 times a day at ${c.runs}`)],
        [L("Archiv stanic ČHMÚ (`chmi-*`)", "ČHMÚ station archive (`chmi-*`)"), L(`2× denně v ${c.chmi}`, `twice a day at ${c.chmi}`)],
        [L("Archiv ALADIN (`aladin-*`)", "ALADIN archive (`aladin-*`)"), L("každé 3 hodiny, přibývají hotové běhy", "every 3 hours, finished runs are added")],
        [L("Radar a družice (větev `radar-live`)", "Radar and satellite (branch `radar-live`)"), L("nové snímky každých 5 minut; archiv `radar-*` a `satellite-*` každých 6 hodin", "new frames every 5 minutes; the `radar-*` and `satellite-*` archives every 6 hours")],
        [L("Experimentální AI předpověď a heatmapa (`data/scores/ai/`, release `ai-latest`)", "Experimental AI forecast and heatmap (`data/scores/ai/`, release `ai-latest`)"),
          L("počítá se denně na vlastním stroji (ne v GitHub Actions) a balík `ai.zip` se pak publikuje; čas vydání je v polích `ai_issued`, `sky_issued` a `rain_issued` (teď kolem 08:30 a 17:30 pražského času); na webu po dalším sestavení stránek", "computed daily on our own machine (not in GitHub Actions), then the `ai.zip` package is published; the issue times are in the `ai_issued`, `sky_issued` and `rain_issued` fields (now around 08:30 and 17:30 Prague time); on the site after the next page build")],
      ],
    }],
    ["note", L(
      "Jde o plánovaný začátek: GitHub Actions spouští úlohy s proměnlivým zpožděním (v říjnu 2026 občas i několik hodin) a výpočet pak trvá desítky minut. Čas poslední aktualizace je v záhlaví stránky a v poli `generated` každého souboru. Čas ani dostupnost nezaručujeme (bez SLA).",
      "These are the scheduled start times: GitHub Actions starts jobs with a variable delay (sometimes several hours in October 2026) and the computation then takes tens of minutes. The time of the last update is in the page header and in the `generated` field of every file. We do not guarantee timing or availability (no SLA).")],

    ["h", L("API v1: předpověď a pořadí modelů po okresech", "API v1: forecast and model ranking by okres"), "api"],
    ["p", L(
      "Statické soubory na GitHub Pages: zdarma, bez klíče a registrace, CORS povolený. Struktura `v1` se nemění zpětně nekompatibilně.",
      "Static files on GitHub Pages: free, no key or registration, CORS allowed. The `v1` layout does not change in a backwards-incompatible way.")],
    ["table", {
      head: [L("Soubor", "File"), L("Obsah", "Contains")],
      rows: [
        [`[api/v1/index.json](${SITE}/api/v1/index.json)`, L("Seznam všech 77 okresů s kódem, názvem, bodem předpovědi a adresami jejich souborů, čas vytvoření, licence a `notice`.", "All 77 okresy with code, name, forecast point and the addresses of their files, time of creation, licence and `notice`.")],
        ["`api/v1/okresy/{code}.json`", L("Vše pro jeden okres (pole níže), např. [CZ0201](" + SITE + "/api/v1/okresy/CZ0201.json).", "Everything for one okres (fields below), e.g. [CZ0201](" + SITE + "/api/v1/okresy/CZ0201.json).")],
        ["`api/v1/ai/okresy/{code}.json`", L("Stejný soubor jako okresu s hodnotami **MeteoVerdict AI**: po částech dne vše z AI, hodinově všechny řady (srážky, oblačnost a svit sedí na hodnoty AI po částech dne) a další veličiny AI: vlhkost, rosný bod, tlak, směr větru, nárazy, teplota 5 cm, dohlednost, pravděpodobnost mlhy, sněžení, výška sněhu, globální záření, nízká oblačnost, CAPE (stejná jména a jednotky jako v souboru okresu, u každé `forecast.sources`: `ai`, nebo `reference` = medián modelů, kde AI model nemá). Pole a zdroje u každého pole viz [níže](#ai). Experiment.", "The same file as an okres's (without `models`) with the values of the **MeteoVerdict AI**: by part of day everything from the AI, every hourly series (precipitation, cloud and sunshine agree with the AI's part-of-day values) and the AI's further variables: humidity, dew point, pressure, wind direction, gusts, 5 cm temperature, visibility, fog probability, snowfall, snow depth, shortwave radiation, low cloud, CAPE (the same names and units as in the okres file; `forecast.sources` says for each `ai`, or `reference` = the median of the models where the AI has no model). The fields and the source of each are described [below](#ai). Experimental.")],
        ["`api/v1/obce/{okres}/{id}.json`, `api/v1/ai/obce/{okres}/{id}.json`, `api/v1/obce/index.json`", L("Předpověď jedné obce (test, struktura se může změnit) ve stejných polích jako soubor okresu. Vlastní hodnoty obce: hodinově `temperature_2m` (přepočtená na její výšku), `precipitation`, `wind_speed_10m`, `relative_humidity_2m`, `dew_point_2m`, `pressure_msl`, `wind_direction_10m`, `wind_gusts_10m` (`hourly_sources` říká, zda z blendu, nebo z AI), po částech dne `tmin`, `tmax`, `precipitation`, `wind` a mráz; ostatní pole (oblačnost, svit, symbol, pravděpodobnost srážek, nárazy po částech dne …) jsou hodnoty okresu. `sources` v souboru říká, co je čí. Varianta `ai/obce` (`model: \"ai\"`) má stejná pole z AI. `index.json` seznam všech obcí: `[okres, id, název, lat, lon]`.", "The forecast of one obec (a test, the layout may change) with the same fields as an okres file. The obec's own values: hourly `temperature_2m` (adjusted to its elevation), `precipitation`, `wind_speed_10m`, `relative_humidity_2m`, `dew_point_2m`, `pressure_msl`, `wind_direction_10m`, `wind_gusts_10m` (`hourly_sources` says whether from the blend or the AI), by part of day `tmin`, `tmax`, `precipitation`, `wind` and frost; the other fields (cloud, sunshine, symbol, probability of precipitation, gusts by part of day …) are the okres's values. `sources` in the file says which is which. The `ai/obce` variant (`model: \"ai\"`) has the same fields from the AI. `index.json` lists every obec: `[okres, id, name, lat, lon]`.")],
      ],
    }],
    ["table", {
      head: [L("Pole v souboru okresu", "Field in an okres file"), L("Význam", "Meaning")],
      rows: [
        ["`okres`", L("Kód okresu (LAU 1, např. CZ0201), název a bod, pro který je předpověď.", "Okres code (LAU 1, e.g. CZ0201), name and the point the forecast is for.")],
        ["`forecast.hourly`", L("`time` (UTC) a hodinové řady `temperature_2m` (°C), `precipitation` (mm za hodinu končící v daném čase), `wind_speed_10m` (m/s), `cloud_cover` (%), `sunshine_duration` (s za hodinu). Oblačnost a svit jsou průměr modelů opravený podle pozorování ČHMÚ. Další veličiny (jednotky v `forecast.units`, původ každé v `forecast.sources`: `blend` = naše kombinace, `reference` = medián nejlepších modelů): `relative_humidity_2m` (%), `dew_point_2m` (°C), `pressure_msl` (hPa), `wind_direction_10m` (°, odkud vane; `null` v bezvětří), `wind_gusts_10m` (m/s) jsou naše řady, `shortwave_radiation` (W/m²), `cloud_cover_low` (%), `visibility` (km), `snowfall`, `snow_depth` (cm), `snow_depth_water_equivalent` (mm) medián modelů. **temperature_2m_lo, temperature_2m_hi** (°C): 80% rozpětí kolem teploty („±“ v grafu) z chyb naší předpovědi za posledních 30 dní; chybí, dokud se nespočítá.", "`time` (UTC) and the hourly series `temperature_2m` (°C), `precipitation` (mm in the hour ending at the time), `wind_speed_10m` (m/s), `cloud_cover` (%), `sunshine_duration` (s per hour). Cloud cover and sunshine are the mean of the models corrected against ČHMÚ observations. Further variables (units in `forecast.units`, the origin of each in `forecast.sources`: `blend` = our combination, `reference` = the median of the best models): `relative_humidity_2m` (%), `dew_point_2m` (°C), `pressure_msl` (hPa), `wind_direction_10m` (°, where it blows from; `null` in calm) and `wind_gusts_10m` (m/s) are our series; `shortwave_radiation` (W/m²), `cloud_cover_low` (%), `visibility` (km), `snowfall`, `snow_depth` (cm) and `snow_depth_water_equivalent` (mm) are the median of the models. **temperature_2m_lo, temperature_2m_hi** (°C): the 80 % range around the temperature (the “±” in the chart) from the errors of our forecast over the last 30 days; absent until computed.")],
        ["`forecast.parts`", L("Souhrn po dnech a částech dne v pražském čase (`night`, `morning`, `afternoon`, `evening`, `day`): `tmin`, `tmax`, srážky, `rain_probability`, vítr, oblačnost, svit, `symbol`, východ a západ slunce, `heavy_rain_probability`. **Prahy MeteoVerdictu** (ano/ne, `null`, kde nejsou data): `heavy_rain` (aspoň 5 mm za období), `frost` a `ground_frost` (noční minimum, přízemní mrazík), `gust_over_threshold` (náraz aspoň 13,5 m/s. **Nejde o výstrahy ČHMÚ**, ty vydává jen [ČHMÚ](https://www.chmi.cz/).", "Summary by day and part of day in Prague time (`night`, `morning`, `afternoon`, `evening`, `day`): `tmin`, `tmax`, precipitation, `rain_probability`, wind, cloud, sunshine, `symbol`, sunrise and sunset, `heavy_rain_probability`. **MeteoVerdict thresholds** (yes/no, `null` where there are no data): `heavy_rain` (at least 5 mm in the period), `frost` and `ground_frost` (night minimum, ground frost), `gust_over_threshold` (gust of at least 13.5 m/s). **They are not ČHMÚ warnings**; only [ČHMÚ](https://www.chmi.cz/) issues those.")],
        ["`licence`, `attribution`, `notice`", L("Licence, text ke zdroji a upozornění, že prahy nejsou výstrahy ČHMÚ.", "Licence, the text to credit and the notice that thresholds are not ČHMÚ warnings.")],
      ],
    }],

    ["h", L("MeteoVerdict AI: soubor okresu", "MeteoVerdict AI: the okres file"), "ai"],
    ["p", L(
      "Experimentální strojová korekce 19 modelů, počítaná denně. Stav všech veličin je zatím `unverified`: štítek „funguje“ AI dostane, až porazí náš blend s celým 95% intervalem pod nulou aspoň na 28 změřených dnech (měří se od spuštění 2026-10-19; `ai/ai.json`). Není to oficiální předpověď.",
      "An experimental machine correction of 19 models, computed daily. The status of every variable is still `unverified`: the AI gets the label “works” when it beats our blend with the whole 95 % interval below zero on at least 28 measured days (counted from the launch on 2026-10-19; `ai/ai.json`). It is not an official forecast.")],
    ["table", {
      head: [L("Pole v souboru AI okresu", "Field in an AI okres file"), L("Význam", "Meaning")],
      rows: [
        ["`okres`, `licence`, `attribution`, `notice`", L("Jako u souboru okresu výše.", "As in the okres file above.")],
        ["`forecast.model`, `ai_issued`, `method`", L("`\"ai\"`; kdy AI předpověď vydala; věta o tom, co je z AI.", "`\"ai\"`; when the AI issued its forecast; a sentence on what is the AI's.")],
        ["`forecast.sources`", L("U každého pole `ai`, `blend` nebo `astronomy` (východ a západ slunce). Je to stejná tabulka polí jako v souboru okresu; záleží jen na zdroji.", "For every field `ai`, `blend` or `astronomy` (sunrise and sunset). The fields are the same as in the okres file; only the source differs.")],
        ["`forecast.hourly`", L("Stejné řady jako u okresu. Všechny sloupce jsou vyplněné. `temperature_2m` (°C) a `wind_speed_10m` (m/s) předpovídá AI hodinově, v bodech stanic okresu, zhruba 5 dní od hodiny vydání. Hodinové `precipitation`, `cloud_cover` a `sunshine_duration` jsou vlastní hodinové hodnoty AI, sladěné s hodnotou AI v každé části dne (součet srážek a svitu a průměr oblačnosti odpovídají AI). Rozpětí `temperature_2m_lo`/`_hi` (80 %) je z vlastních minulých chyb AI. Kde AI vlastní hodiny nemá, je to tvar průběhu z blendu přizpůsobený hodnotě AI v části dne. Hodiny, které AI nemá, mají hodnotu blendu.", "The same series as an okres's. Every column is filled. The AI forecasts `temperature_2m` (°C) and `wind_speed_10m` (m/s) hourly, at the okres's station points, about 5 days from the issue hour. The hourly `precipitation`, `cloud_cover` and `sunshine_duration` are the AI's own hourly values, consistent with the AI's value of each part of day (the sums of precipitation and sunshine and the mean cloud match the AI). The 80 % range `temperature_2m_lo`/`_hi` comes from the AI's own past errors. Where the AI has no hours of its own, they are the blend's hour-to-hour shape fitted to the AI's part. Hours the AI has no value for keep the blend's.")],
        ["`forecast.parts`", L("Stejná pole jako u okresu, pro dnešek a dalších 5 dní. Z AI jsou `tmin`, `tmax` (°C), `wind` (m/s), `gust` (m/s) a `gust_over_threshold` (≥ 13,5 m/s), `cloud` (%), `sunshine` (h), `symbol`, `precipitation` (mm), `rain_probability` (≥ 0,2 mm), `heavy_rain_probability` (≥ 5 mm), `heavy_rain` a mráz (`night_min`, `ground_min`, `frost_probability`, `frost`, `ground_frost`; odvozené z teploty AI). `sunrise` a `sunset` jsou astronomie, `coldest_site` a část dne, pro kterou AI nemá řádek, jsou z blendu. `frost`, `ground_frost`, `heavy_rain` a `gust_over_threshold` jsou prahy MeteoVerdictu, **ne výstrahy ČHMÚ**.", "The same fields as an okres's, for today and the next 5 days. The AI's are `tmin`, `tmax` (°C), `wind` (m/s), `gust` (m/s) and `gust_over_threshold` (≥ 13.5 m/s), `cloud` (%), `sunshine` (h), `symbol`, `precipitation` (mm), `rain_probability` (≥ 0.2 mm), `heavy_rain_probability` (≥ 5 mm), `heavy_rain` and frost (`night_min`, `ground_min`, `frost_probability`, `frost`, `ground_frost`; derived from the AI's temperature). `sunrise` and `sunset` are astronomy; `coldest_site` and a part of day the AI has no row for are the blend's. `frost`, `ground_frost`, `heavy_rain` and `gust_over_threshold` are MeteoVerdict thresholds, **not ČHMÚ warnings**.")],
      ],
    }],
    ["note", L(
      "Stav všech veličin AI je zatím `unverified`: štítek „funguje“ AI dostane, až porazí náš blend s celým 95% intervalem pod nulou aspoň na 28 změřených dnech (měří se od 2026-10-19; `ai/ai.json`). Soubory `ai-sky.json` a `ai-rain.json` jsou označeny `shadow: true` (zkušební výstup). Není to oficiální předpověď.",
      "The status of every AI variable is still `unverified`: the AI gets the label “works” when it beats our blend with the whole 95 % interval below zero on at least 28 measured days (counted from 2026-10-19; `ai/ai.json`). `ai-sky.json` and `ai-rain.json` are marked `shadow: true` (a trial output). Not an official forecast.")],

    ["h", L("Soubory ke stažení: releasy na GitHubu", "Downloads: releases on GitHub"), "releases"],
    ["p", L(
      `Velké soubory jsou v [releasech repozitáře](${REPO}/releases) (Parquet, JSON, ZIP, TAR), každý do 2 GiB. Formát je popsán v [dokumentaci](${REPO}/blob/main/docs/data-sources.md).`,
      `Large files are in the [releases of the repository](${REPO}/releases) (Parquet, JSON, ZIP, TAR), each up to 2 GiB. The formats are described in the [documentation](${REPO}/blob/main/docs/data-sources.md).`)],
    ["table", {
      head: [L("Release", "Release"), L("Obsah", "Contains"), L("Licence", "Licence")],
      rows: [
        [release("data-latest"), L("Měřené hodnoty, archivované předpovědi na stanicích a denní skóre (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Starší měsíce: " + releases("data-YYYY-MM", "data-20") + ".", "Observed values, archived forecasts at the stations and daily scores (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Older months: " + releases("data-YYYY-MM", "data-20") + "."), L("CC BY-SA 4.0", "CC BY-SA 4.0")],
        [release("data-latest") + L(": `station-data.zip`", ": `station-data.zip`"), L("Historie stanic (jen data ČHMÚ); web je nezobrazuje.", "The stations' histories (ČHMÚ data only); the website does not show them."), L("CC BY 4.0, ČHMÚ", "CC BY 4.0, ČHMÚ")],
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
      "Předpověď je statistická kombinace modelů, ne oficiální předpověď ČHMÚ; zda je lepší než nejlepší jednotlivý model, zpětně ověřujeme každý den na stránce [Porovnání](compare-models.html). Prahy (mráz, přízemní mrazík, vydatný déšť, nárazy) nejsou výstrahy: oficiální výstrahy vydává jen [ČHMÚ](https://www.chmi.cz/). Za použití dat neručíme.",
      "The forecast is a statistical combination of models, not an official ČHMÚ forecast; whether it beats the best single model is tested every day on the [Compare](compare-models.html) page. The thresholds (frost, ground frost, heavy rain, gusts) are not warnings: only [ČHMÚ](https://www.chmi.cz/) issues official warnings. Use the data at your own risk.")],
  ];
  const split = all.findIndex((block) => block[2] === "releases");
  return { api: all.slice(0, split), more: all.slice(split) };
}

/**
 * What every field of the example under the okres picker means (the Data page): a table
 * per part of the file, in the order the example shows them.
 */
export function exampleBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  const table = (first, rows) => ["table", { head: [first, L("Význam", "Meaning")], rows }];
  return [
    ["h", L("Co znamenají pole v příkladu", "What the fields in the example mean"), "example-fields"],
    ["p", L(
      "Příklad výše je skutečný soubor, jen dlouhé seznamy jsou zkrácené: u řad jsou první hodnoty a `…`, u seznamu částí dne jedna položka. Nahoře každý soubor nese licenci a upozornění.",
      "The example above is a real file with the long lists cut short: series show their first values and `…`, the list of parts of day shows one item. The licence and notice are at the top of every file.")],
    table(L("Záhlaví souboru", "File head"), [
      ["`api`, `docs`", L("Verze API (`v1`) a odkaz na tuto stránku.", "The API version (`v1`) and a link to this page.")],
      ["`licence`, `attribution`, `notice`", L("Licence (CC BY-SA 4.0), text, který uvést u zdroje, a upozornění, že prahy (mráz, vydatný déšť, nárazy) nejsou výstrahy ČHMÚ.", "The licence (CC BY-SA 4.0), the text to credit and the notice that the thresholds (frost, heavy rain, gusts) are not ČHMÚ warnings.")],
      ["`okres`", L("`code` (kód okresu, LAU 1), `name`, `lat` a `lon`: bod, pro který je předpověď.", "`code` (okres code, LAU 1), `name`, `lat` and `lon`: the point the forecast is for.")],
    ]),
    table(L("`forecast`: předpověď", "`forecast`: the forecast"), [
      ["`generated`, `method`, `time_zone_of_parts`", L("Kdy byla předpověď vytvořena (UTC), věta o tom, jak vznikla, a časové pásmo částí dne (`Europe/Prague`).", "When the forecast was made (UTC), a sentence on how it was made and the time zone of the parts of day (`Europe/Prague`).")],
      ["`units`", L("Jednotka každé hodinové řady.", "The unit of every hourly series.")],
      ["`sources`", L("U dalších veličin, odkud jsou: `blend` je naše kombinace modelů, `reference` medián nejlepších modelů. Veličiny, které tu nejsou (teplota, srážky, vítr, oblačnost, svit), jsou vždy z kombinace.", "For the further variables, where they come from: `blend` is our combination of the models, `reference` the median of the best models. Variables not listed (temperature, precipitation, wind, cloud, sunshine) are always from the combination.")],
    ]),
    table(L("`forecast.hourly`: hodinové řady (každá má stejný počet hodnot jako `time`)", "`forecast.hourly`: hourly series (each has as many values as `time`)"), [
      ["`time`", L("Čas každé hodiny v UTC. Pole se čtou po indexu: i-tá hodnota každé řady patří k i-tému času.", "The time of every hour in UTC. Read the arrays by index: the i-th value of every series belongs to the i-th time.")],
      ["`temperature_2m`, `temperature_2m_lo`, `temperature_2m_hi`", L("Teplota ve 2 m (°C) a spodní a horní konec 80% rozpětí kolem ní („±“ v grafu), spočítaného z chyb naší předpovědi za posledních 30 dní.", "Temperature at 2 m (°C) and the lower and upper end of the 80 % range around it (the “±” in the chart), from the errors of our forecast over the last 30 days.")],
      ["`precipitation`", L("Srážky (mm) za hodinu, která v daném čase končí.", "Precipitation (mm) in the hour that ends at the time.")],
      ["`wind_speed_10m`, `wind_gusts_10m`, `wind_direction_10m`", L("Průměrný vítr v 10 m (m/s), nejsilnější náraz v hodině (m/s) a směr, odkud vane (°; `null` v bezvětří).", "Mean wind at 10 m (m/s), the highest gust in the hour (m/s) and the direction it blows from (°; `null` in calm).")],
      ["`cloud_cover`, `cloud_cover_low`", L("Celková a nízká oblačnost (%). Celková je průměr modelů opravený podle pozorování ČHMÚ.", "Total and low cloud cover (%). The total is the mean of the models corrected against ČHMÚ observations.")],
      ["`sunshine_duration`, `shortwave_radiation`", L("Sluneční svit (s za hodinu) a krátkovlnné záření (W/m²).", "Sunshine (s per hour) and shortwave radiation (W/m²).")],
      ["`relative_humidity_2m`, `dew_point_2m`, `pressure_msl`", L("Relativní vlhkost (%), rosný bod (°C) a tlak přepočtený na hladinu moře (hPa).", "Relative humidity (%), dew point (°C) and pressure reduced to sea level (hPa).")],
      ["`visibility`, `snowfall`, `snow_depth`, `snow_depth_water_equivalent`", L("Dohlednost (km, nejvýš 20), nový sníh za hodinu (cm), výška sněhu (cm) a vodní hodnota sněhu (mm).", "Visibility (km, up to 20), new snow per hour (cm), snow depth (cm) and its water equivalent (mm).")],
    ]),
    table(L("`forecast.parts`: části dne (jedna položka za den a část)", "`forecast.parts`: parts of day (one item per day and part)"), [
      ["`day`, `part`", L("Den (pražský čas) a část dne: `night`, `morning`, `afternoon`, `evening` a `day` (celý den).", "The day (Prague time) and the part of day: `night`, `morning`, `afternoon`, `evening` and `day` (the whole day).")],
      ["`tmin`, `tmax`", L("Nejnižší a nejvyšší teplota v části dne (°C).", "Lowest and highest temperature in the part (°C).")],
      ["`precipitation`, `rain_probability`, `heavy_rain_probability`, `heavy_rain`", L("Úhrn srážek (mm), pravděpodobnost srážek ≥ 0,2 mm (0 až 1), pravděpodobnost ≥ 5 mm (0 až 1) a ano/ne, zda se čeká aspoň 5 mm.", "Precipitation total (mm), the probability of at least 0.2 mm (0 to 1), of at least 5 mm (0 to 1) and yes/no whether at least 5 mm is expected.")],
      ["`wind`, `gust`, `gust_over_threshold`", L("Průměrný vítr a nejsilnější náraz (m/s) a ano/ne, zda náraz dosáhne 13,5 m/s.", "Mean wind and the highest gust (m/s) and yes/no whether the gust reaches 13.5 m/s.")],
      ["`cloud`, `sunshine`, `symbol`", L("Oblačnost (%), sluneční svit (h) a symbol počasí (`clear`, `partly`, `cloudy`, `showers`, `rain`).", "Cloud cover (%), sunshine (h) and the weather symbol (`clear`, `partly`, `cloudy`, `showers`, `rain`).")],
      ["`sunrise`, `sunset`", L("Východ a západ slunce (pražský čas); je to astronomie, ne předpověď.", "Sunrise and sunset (Prague time); astronomy, not a forecast.")],
      ["`night_min`, `coldest_site`, `coldest_min`, `frost_probability`, `frost`, `ground_min`, `ground_frost`", L("Mráz, jen u řádků `night` a `day` data, kdy noc končí (jinde `null`): opravené noční minimum ve 2 m (°C), nejmrazivější stanice okresu a její minimum, pravděpodobnost mrazu (0 až 1), ano/ne mráz (minimum ≤ 1 °C), odhad přízemního minima 5 cm nad zemí a ano/ne přízemní mrazík (≤ 0 °C).", "Frost, only on the `night` and `day` rows of the date a night ends (`null` elsewhere): the corrected night minimum at 2 m (°C), the okres's most frost-prone station and its minimum, the probability of frost (0 to 1), yes/no frost (minimum ≤ 1 °C), the estimated minimum 5 cm above the ground and yes/no ground frost (≤ 0 °C).")],
    ]),
  ];
}
