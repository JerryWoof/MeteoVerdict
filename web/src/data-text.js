// The text of the Data page (data.html) below the okres picker, as two lists of blocks (the API
// part and the downloads) for info-page.js's renderBlocks (one function for both languages:
// L(cs, en)); legalBlocks is the licences, citing and terms fold.

const REPO = "https://github.com/JerryWoof/MeteoVerdict";
const SITE = "https://meteoverdict.cz";

const BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/";

const release = (tag) => `[${tag}](${REPO}/releases/tag/${tag})`;
const releases = (label, query) => `[${label}](${REPO}/releases?q=${query})`;

/** @param {"cs"|"en"} language */
export function dataBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  const all = [
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

    ["p", L(
      `Velké soubory jsou v [releasech repozitáře](${REPO}/releases) (Parquet, JSON, ZIP, TAR), každý do 2 GiB. Formát je popsán v [dokumentaci](${REPO}/blob/main/docs/data-sources.md).`,
      `Large files are in the [releases of the repository](${REPO}/releases) (Parquet, JSON, ZIP, TAR), each up to 2 GiB. The formats are described in the [documentation](${REPO}/blob/main/docs/data-sources.md).`), "releases"],
    ["table", {
      head: [L("Release", "Release"), L("Obsah", "Contains"), L("Licence", "Licence")],
      rows: [
        [release("data-latest"), L("Měřené hodnoty, archivované předpovědi na stanicích a denní skóre (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Starší měsíce: " + releases("data-YYYY-MM", "data-20") + ".", "Observed values, archived forecasts at the stations and daily scores (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Older months: " + releases("data-YYYY-MM", "data-20") + "."), "CC BY-SA 4.0"],
        [release("ai-latest"), L("`ai.zip`: výstupy MeteoVerdict AI, denně nové.", "`ai.zip`: the MeteoVerdict AI outputs, new every day."), "CC BY-SA 4.0"],
        [L("ostatní", "others"), L("Archivy ČHMÚ (`chmi-*`, `aladin-*`), radar a družice, samostatné běhy modelů: [všechny releasy](" + REPO + "/releases).", "ČHMÚ archives (`chmi-*`, `aladin-*`), radar and satellite, single model runs: [all releases](" + REPO + "/releases)."), L("podle zdroje", "by source")],
      ],
    }],
  ];
  const split = all.findIndex((block) => block[2] === "releases");
  return { api: all.slice(0, split), more: all.slice(split) };
}

/** The Licences, citing and terms fold of the Data page; the full list of sources is on zdroje.html. */
export function legalBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  return [
    ["p", L(
      `Naše výstupy (\`api/v1\`, předpovědi, skóre, výstupy AI) jsou pod licencí [CC BY-SA 4.0](${BY_SA}), kód pod [MIT](${REPO}/blob/main/LICENSE). Každý soubor v \`api/v1\` nese licenci a text ke zdroji. Všechny zdroje a jejich licence jsou na stránce [Zdroje a licence](zdroje.html).`,
      `Our outputs (\`api/v1\`, forecasts, scores, AI outputs) are under [CC BY-SA 4.0](${BY_SA}), the code under [MIT](${REPO}/blob/main/LICENSE). Every file in \`api/v1\` carries the licence and the text to credit. All sources and their licences are on the page [Sources and licences](zdroje.html).`)],
    ["p", L("Jak citovat: zkopírujte pole `attribution` ze souboru, nebo použijte tuto větu:", "How to cite: copy the `attribution` field of the file, or use this sentence:")],
    ["code", L(
      `MeteoVerdict, ${SITE}/ (CC BY-SA 4.0). Data: ČHMÚ, Open-Meteo.com a poskytovatelé modelů; údaje byly kombinovány a opraveny.`,
      `MeteoVerdict, ${SITE}/ (CC BY-SA 4.0). Data: ČHMÚ, Open-Meteo.com and the model providers; the values were combined and corrected.`)],
    ["p", L(
      "Neříkejte, že data schvaluje ČHMÚ, Open-Meteo nebo poskytovatel modelu. Stahujte nejvýš jednou za hodinu: předpověď se mění jen čtyřikrát denně. Je to statistická kombinace modelů, ne oficiální předpověď ČHMÚ; prahy (mráz, přízemní mrazík, vydatný déšť, nárazy) nejsou výstrahy, ty vydává jen [ČHMÚ](https://www.chmi.cz/). Za použití dat neručíme.",
      "Do not imply that ČHMÚ, Open-Meteo or a model provider endorses the data. Please fetch at most once an hour: the forecast changes only four times a day. It is a statistical combination of models, not an official ČHMÚ forecast; the thresholds (frost, ground frost, heavy rain, gusts) are not warnings, only [ČHMÚ](https://www.chmi.cz/) issues those. Use the data at your own risk.")],
  ];
}

/**
 * What every field of the example under the okres picker means (the Data page): a table
 * per part of the file, in the order the example shows them.
 */
export function exampleBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  const table = (first, rows) => ["table", { head: [first, L("Význam", "Meaning")], rows }];
  return [
    ["p", L(
      "Záložka Náhled ukazuje skutečný soubor, jen dlouhé seznamy jsou zkrácené: u řad jsou první hodnoty a `…`, u seznamu částí dne jedna položka. Nahoře každý soubor nese licenci a upozornění.",
      "The Preview tab shows a real file with the long lists cut short: series show their first values and `…`, the list of parts of day shows one item. The licence and notice are at the top of every file.")],
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
