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
          L("počítá se denně na vlastním stroji (ne v GitHub Actions) a balík `ai.zip` se pak publikuje; čas vydání je v polích `ai_issued`, `sky_issued` a `rain_issued` (teď kolem 08:30 a 17:30 pražského času); na webu po dalším sestavení stránek", "computed daily on our own machine (not in GitHub Actions), then the `ai.zip` package is published; the issue times are in the `ai_issued`, `sky_issued` and `rain_issued` fields (now around 08:30 and 17:30 Prague time); on the site after the next page build")],
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
        ["`api/v1/ai/okresy/{code}.json`", L("Stejný soubor jako okresu (bez `models`), ale s hodnotami **MeteoVerdict AI** (`forecast.model: \"ai\"`, `forecast.ai_issued`). Po částech dne (`forecast.parts`) je vše z AI: teplota, vítr, nárazy, oblačnost, svit, symbol, srážky, pravděpodobnost srážek, vydatný déšť a mráz. Hodinově je z AI teplota a vítr; hodinové srážky, oblačnost, svit a 80% rozpětí teploty jsou z blendu, stejně jako část dne, pro kterou AI nemá řádek. `forecast.sources` říká u každého pole `ai`, `blend` nebo `astronomy` (východ a západ slunce). Experiment.", "The same file as an okres's (without `models`), with the values of the **MeteoVerdict AI** (`forecast.model: \"ai\"`, `forecast.ai_issued`). By part of day (`forecast.parts`) everything is the AI's: temperature, wind, gusts, cloud, sunshine, symbol, precipitation, probability of precipitation, heavy rain and frost. Hourly, the AI's are temperature and wind; the hourly precipitation, cloud, sunshine and the 80 % range of the temperature are the blend's, as is a part of day the AI has no row for. `forecast.sources` says `ai`, `blend` or `astronomy` (sunrise and sunset) for each field. Experimental.")],
        ["`api/v1/obce/{okres}/{id}.json`, `api/v1/ai/obce/{okres}/{id}.json`, `api/v1/obce/index.json`", L("Předpověď jedné obce (test, struktura se může změnit) ve stejných polích jako soubor okresu. Vlastní hodnoty obce: hodinově `temperature_2m` (přepočtená na její výšku), `precipitation`, `wind_speed_10m`, po částech dne `tmin`, `tmax`, `precipitation`, `wind` a mráz; ostatní pole (oblačnost, svit, symbol, pravděpodobnost srážek, nárazy …) jsou hodnoty okresu. `sources` v souboru říká, co je čí. Varianta `ai/obce` (`model: \"ai\"`) má stejná pole z AI. `index.json` seznam všech obcí: `[okres, id, název, lat, lon]`.", "The forecast of one obec (a test, the layout may change) with the same fields as an okres file. The obec's own values: hourly `temperature_2m` (adjusted to its elevation), `precipitation`, `wind_speed_10m`, by part of day `tmin`, `tmax`, `precipitation`, `wind` and frost; the other fields (cloud, sunshine, symbol, probability of precipitation, gusts …) are the okres's values. `sources` in the file says which is which. The `ai/obce` variant (`model: \"ai\"`) has the same fields from the AI. `index.json` lists every obec: `[okres, id, name, lat, lon]`.")],
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

    ["h", L("MeteoVerdict AI: co předpovídá a odkud je to v souborech", "MeteoVerdict AI: what it forecasts and where it is in the files"), "ai"],
    ["p", L(
      "Experimentální strojová korekce 19 modelů, počítaná denně. Stav všech veličin je zatím `unverified`: štítek „funguje“ AI dostane, až porazí náš blend s celým 95% intervalem pod nulou aspoň na 28 změřených dnech (měří se od spuštění 2026-10-19; `ai/ai.json`). Není to oficiální předpověď.",
      "An experimental machine correction of 19 models, computed daily. The status of every variable is still `unverified`: the AI gets the label “works” when it beats our blend with the whole 95 % interval below zero on at least 28 measured days (counted from the launch on 2026-10-19; `ai/ai.json`). It is not an official forecast.")],
    ["table", {
      head: [L("Veličina", "Variable"), L("Jednotka a krok", "Unit and step"), L("Z AI (`source: ai`)", "From the AI (`source: ai`)"), L("Z blendu (`source: blend`)", "From the blend (`source: blend`)")],
      rows: [
        [L("Teplota (`tmin`, `tmax`, `temperature_2m`)", "Temperature (`tmin`, `tmax`, `temperature_2m`)"), L("°C; po hodinách a po částech dne", "°C; hourly and by part of day"), L("všude: `api/v1/ai`, `ai-forecast.json`, `ai/fc/outlook.json`, stanice", "everywhere: `api/v1/ai`, `ai-forecast.json`, `ai/fc/outlook.json`, stations"), L("80% rozpětí `temperature_2m_lo`/`_hi` (AI ho nemá)", "the 80 % range `temperature_2m_lo`/`_hi` (the AI has none)")],
        [L("Vítr (`wind`, `wind_speed_10m`)", "Wind (`wind`, `wind_speed_10m`)"), L("m/s; střední hodinový, v částech dne nejvyšší hodinový", "m/s; hourly mean, in the parts the highest hourly mean"), L("všude jako teplota", "everywhere like temperature"), "–"],
        [L("Nárazy (`gust`, `gust_over_threshold`)", "Gusts (`gust`, `gust_over_threshold`)"), L("m/s po částech dne; práh 13,5 m/s", "m/s by part of day; threshold 13.5 m/s"), L("`api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-sky.json`", "`api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-sky.json`"), "–"],
        [L("Oblačnost (`cloud`) a svit (`sunshine`)", "Cloud (`cloud`) and sunshine (`sunshine`)"), L("% a hodiny po částech dne", "% and hours by part of day"), L("po částech dne: `api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-sky.json`", "by part of day: `api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-sky.json`"), L("hodinové řady `cloud_cover` a `sunshine_duration`", "the hourly `cloud_cover` and `sunshine_duration`")],
        [L("Srážky (`precipitation`)", "Precipitation (`precipitation`)"), L("mm po částech dne", "mm by part of day"), L("po částech dne: `api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-rain.json`", "by part of day: `api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-rain.json`"), L("hodinové srážky (`api/v1/ai/okresy`) a `api/v1/ai/obce`", "the hourly precipitation (`api/v1/ai/okresy`) and `api/v1/ai/obce`")],
        [L("Pravděpodobnost srážek a vydatný déšť (`rain_probability` ≥ 0,2 mm, `heavy_rain_probability` ≥ 5 mm, `heavy_rain`)", "Probability of rain and heavy rain (`rain_probability` ≥ 0.2 mm, `heavy_rain_probability` ≥ 5 mm, `heavy_rain`)"), L("0–1 a ano/ne po částech dne", "0–1 and yes/no by part of day"), L("`api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-rain.json` (+ `p1`: ≥ 1 mm)", "`api/v1/ai`, `ai/fc/outlook.json`, `ai/fc/sky/ai-rain.json` (+ `p1`: ≥ 1 mm)"), "–"],
        [L("Symbol počasí (`symbol`)", "Weather symbol (`symbol`)"), L("po částech dne", "by part of day"), L("`api/v1/ai`, `ai/fc/outlook.json`", "`api/v1/ai`, `ai/fc/outlook.json`"), "–"],
        [L("Východ a západ slunce", "Sunrise and sunset"), L("místní čas po dnech", "local time, by day"), L("(astronomie, `source: astronomy`, ne předpověď)", "(astronomy, `source: astronomy`, not a forecast)"), "–"],
        [L("Mráz, přízemní mrazík (`frost`, `ground_frost`, `night_min`, `ground_min`)", "Frost and ground frost (`frost`, `ground_frost`, `night_min`, `ground_min`)"), L("°C a ano/ne za noc", "°C and yes/no per night"), L("`api/v1/ai`, `ai/fc/outlook.json` (pole `ai` na řádku): odvozené z teploty AI; prahy jsou naše, ne výstrahy", "`api/v1/ai`, `ai/fc/outlook.json` (the row's `ai` field): derived from the AI's temperature; the thresholds are ours, not warnings"), L("`coldest_site` (název stanice)", "`coldest_site` (the station's name)")],
      ],
    }],
    ["note", L(
      "Časový krok: jen teplota a vítr jsou hodinové (`ai-forecast.json`, od hodiny vydání zhruba 5 dní, v bodech stanic okresu; `api/v1/ai` z něj skládá hodinové řady teploty a větru). Ostatní veličiny jsou po částech dne (`night`, `morning`, `afternoon`, `evening`, `day`) na 6 dní (dnes a 5 dalších). `ai/fc/outlook.json` má u řádků pole `ai` se seznamem hodnot, které AI doplnila, a `ai_issued`, `sky_issued` a `rain_issued` s časy vydání. Soubory `ai-sky.json` a `ai-rain.json` jsou označeny `shadow: true` (zkušební výstup).",
      "Time step: only temperature and wind are hourly (`ai-forecast.json`, from the issue hour about 5 days ahead, at the station points of the okres; `api/v1/ai` builds its hourly temperature and wind from it). The other variables are by part of day (`night`, `morning`, `afternoon`, `evening`, `day`) for 6 days (today and the next 5). Each row of `ai/fc/outlook.json` has an `ai` field listing the values the AI filled in, and `ai_issued`, `sky_issued` and `rain_issued` give the issue times. `ai-sky.json` and `ai-rain.json` are marked `shadow: true` (a trial output).")],

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
        ["`station-fc/{station}.json`, `index.json`", L("Předpověď každého modelu a blendu v bodě stanice po dnech (D+1, D+2, posledních 35 dní) vedle naměřeného, pro asi 300 stanic: `obs` a `series[veličina][předstih][model]` (`tmax`, `tmin`, `r`, `wind`, `gust`). Výběr modelu na stránce Naměřeno. AI je zvlášť, viz `ai/fc/stations/`. `err-{den}.json`: chyba modelu (model − naměřeno, desetiny) všech stanic za den, pro barvu teček na mapě.", "Every model's and the blend's forecast at the station point by day (D+1, D+2, the last 35 days) next to the measured values, for about 300 stations: `obs` and `series[value][lead][model]` (`tmax`, `tmin`, `r`, `wind`, `gust`). The model selector of the Measured page. The AI is separate: see `ai/fc/stations/`. `err-{day}.json`: every station's model error (model − measured, in tenths) for a day, for the map's dot colours.")],
        ["`meta.json`, `leads.json`, `blend-test.json`, `rain-calibration.json`", L("Seznam modelů a oken, chyby podle předstihu, denní test, zda kombinace poráží nejlepší model, a kalibrace srážek.", "The models and windows, errors by lead time, the daily test of whether the combination beats the best model, and the rain calibration.")],
        ["`ai/ai.json`, `ai/ai-forecast.json`", L("**Experimentální MeteoVerdict AI.** `ai.json`: stav, pravidlo ověřování, skóre a validace; započítává se jen od spuštění 2026-10-19. `ai-forecast.json`: hodinová teplota a vítr AI po okresech (`okresy.{code}.temperature_2m.ai` a `.combined`, `time` v UTC, `issued`, `ai_status`) a odkazy `parts` na ostatní soubory.", "**Experimental MeteoVerdict AI.** `ai.json`: status, the rule of the verification, scores and validation; counted only from the launch on 2026-10-19. `ai-forecast.json`: the AI's hourly temperature and wind by okres (`okresy.{code}.temperature_2m.ai` and `.combined`, `time` in UTC, `issued`, `ai_status`) and `parts`, the links to the other files.")],
        ["`ai/fc/outlook.json`, `ai/fc/sky/ai-sky.json`, `ai/fc/sky/ai-rain.json`", L("Úplná předpověď AI po částech dne ve stejné tabulce jako `outlook.json` (`columns`, `rows`): teplota, vítr, nárazy, oblačnost, svit, srážky v mm, pravděpodobnost srážek, vydatný déšť a symbol jsou z AI; východ a západ slunce jsou astronomie. `sources` v souboru říká u každé hodnoty `ai` nebo `astronomy`. `ai-sky.json` (oblačnost %, svit h, nárazy m/s) a `ai-rain.json` (`rain_probability`, `p1`, `heavy_rain_probability`, `precipitation`) jsou jejich zdroj po okresech.", "The complete AI forecast by part of day in the same table as `outlook.json` (`columns`, `rows`): temperature, wind, gusts, cloud, sunshine, precipitation in mm, probability of precipitation, heavy rain and the symbol are the AI's; sunrise and sunset are astronomy. `sources` in the file says `ai` or `astronomy` for each value. `ai-sky.json` (cloud %, sunshine h, gusts m/s) and `ai-rain.json` (`rain_probability`, `p1`, `heavy_rain_probability`, `precipitation`) are their source by okres.")],
        ["`ai/fc/verify/{code}.json`, `ai/fc/compare/`", L("Porovnání AI s pozorováním po okresech a její pořadí vedle ostatních modelů.", "The AI's comparison with observations by okres, and its ranking next to the other models.")],
        ["`ai/fc/stations/index.json`, `ai/fc/stations/validation/{id}.json`, `ai/fc/stations/fc/{id}.json`", L("AI v bodech stanic (asi 290 stanic): `validation` je chyba AI na validačním vzorku (teplota, vítr, předstih 1 až 5 dní; čísla jsou optimistická), `fc/{id}.json` (od dalšího denního běhu) předpovědi AI `tmax`, `tmin`, `wind` na D+1 a D+2 za posledních 35 dní vedle naměřeného, pro stránku Naměřeno.", "The AI at the station points (about 290 stations): `validation` is the AI's error on the validation sample (temperature, wind, lead 1 to 5 days; the numbers are optimistic), `fc/{id}.json` (from the next daily run) the AI's `tmax`, `tmin` and `wind` for D+1 and D+2 over the last 35 days next to the measured values, for the Measured page.")],
        ["`ai/fc/heat/`, `ai/fc/temp100m/`", L("Podklady **heatmapy** teploty s rozlišením 100 m (`index.json` a PNG mřížky; teplotu pro hodinu skládá prohlížeč) a mapy po částech dne.", "The inputs of the **heatmap** of temperature at 100 m resolution (`index.json` and PNG grids; the browser composes the temperature for an hour) and the maps by part of day.")],
      ],
    }],
    ["note", L(
      "AI výstupy jsou experiment: nejsou oficiální předpověď a nemají záruku. Soubory AI zatím nenesou pole `licence` a `attribution`. Licence výstupů AI zatím není rozhodnutá; do rozhodnutí je berte jako CC BY-SA 4.0 jako ostatní naše výstupy a uvádějte zdroje níže.",
      "The AI outputs are an experiment: not an official forecast and without a guarantee. The AI files do not yet carry `licence` and `attribution` fields. The licence of the AI outputs is not decided yet; until it is, treat them as CC BY-SA 4.0 like our other outputs and credit the sources below.")],

    ["h", L("Soubory ke stažení: releasy na GitHubu", "Downloads: releases on GitHub"), "releases"],
    ["p", L(
      `Velké soubory jsou v [releasech repozitáře](${REPO}/releases) (Parquet, JSON, ZIP, TAR), každý do 2 GiB. Formát je popsán v [dokumentaci](${REPO}/blob/main/docs/data-sources.md).`,
      `Large files are in the [releases of the repository](${REPO}/releases) (Parquet, JSON, ZIP, TAR), each up to 2 GiB. The formats are described in the [documentation](${REPO}/blob/main/docs/data-sources.md).`)],
    ["table", {
      head: [L("Release", "Release"), L("Obsah", "Contains"), L("Licence", "Licence")],
      rows: [
        [release("data-latest"), L("Měřené hodnoty, archivované předpovědi na stanicích a denní skóre (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), váhy modelů, `blend-interval.json` (rozpětí „±“), `frost.json`, `compare.zip`, `outlook*.zip`, `site-data.zip`. Starší měsíce: " + releases("data-YYYY-MM", "data-20") + ".", "Observed values, archived forecasts at the stations and daily scores (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), model weights, `blend-interval.json` (the “±” range), `frost.json`, `compare.zip`, `outlook*.zip`, `site-data.zip`. Older months: " + releases("data-YYYY-MM", "data-20") + "."), L("CC BY-SA 4.0", "CC BY-SA 4.0")],
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
  const split = all.findIndex((block) => block[2] === "files");
  return { api: all.slice(0, split), more: all.slice(split) };
}
