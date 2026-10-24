// The text of the Data page (data.html) below the okres picker, as two lists of blocks (the API
// part and the downloads) for info-page.js's renderBlocks (one function for both languages:
// L(cs, en)); legalBlocks is the licences, citing and terms fold.

const REPO = "https://github.com/JerryWoof/MeteoVerdict";
const SITE = "https://meteoverdict.cz";

const BY_SA = "https://creativecommons.org/licenses/by-sa/4.0/";

const release = (tag) => `[${tag}](${REPO}/releases/tag/${tag})`;
const releases = (label, query) => `[${label}](${REPO}/releases?q=${query})`;

/** The downloads fold of the Data page: the releases on GitHub. */
export function dataBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  return [
    ["table", {
      head: [L("Release", "Release"), L("Obsah", "Contains"), L("Licence", "Licence")],
      rows: [
        [release("data-latest"), L("Měřené hodnoty, archivované předpovědi na stanicích a denní skóre (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Starší měsíce: " + releases("data-YYYY-MM", "data-20") + ".", "Observed values, archived forecasts at the stations and daily scores (`obs-`, `fc-`, `scores-YYYY-MM.parquet`, `aggregates.parquet`), `compare.zip`, `outlook*.zip`, `site-data.zip`. Older months: " + releases("data-YYYY-MM", "data-20") + "."), "CC BY-SA 4.0"],
        [release("ai-latest"), L("`ai.zip`: výstupy MeteoVerdict AI, denně nové.", "`ai.zip`: the MeteoVerdict AI outputs, new every day."), "CC BY-SA 4.0"],
      ],
    }],
  ];
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
export function fieldBlocks(language) {
  const L = (cs, en) => (language === "cs" ? cs : en);
  // the field names of a group get the path of the group in front: `time` of forecast.hourly is `forecast.hourly.time`
  const group = (prefix, rows) => rows.map(([names, text]) => [names.replace(/`([^`]+)`/g, "`" + prefix + "$1`"), text]);
  return [
    ["p", L(
      "Pole souboru okresu (`api/v1/okresy/{code}.json`; AI soubor a soubor obce mají stejná pole, liší se zdrojem hodnot). Záložka Náhled ukazuje skutečný soubor s dlouhými seznamy zkrácenými.",
      "The fields of an okres file (`api/v1/okresy/{code}.json`; the AI file and an obec file have the same fields and differ in where the values come from). The Preview tab shows a real file with the long lists cut short.")],
    ["table", { head: [L("Pole souboru okresu", "Field of an okres file"), L("Význam", "Meaning")], rows: [
    ...group("", [
      ["`api`, `docs`", L("Verze API (`v1`) a odkaz na tuto stránku.", "The API version (`v1`) and a link to this page.")],
      ["`licence`, `attribution`, `notice`", L("Licence (CC BY-SA 4.0), text, který uvést u zdroje, a upozornění, že prahy (mráz, vydatný déšť, nárazy) nejsou výstrahy ČHMÚ.", "The licence (CC BY-SA 4.0), the text to credit and the notice that the thresholds (frost, heavy rain, gusts) are not ČHMÚ warnings.")],
      ["`okres`", L("`code` (kód okresu, LAU 1), `name`, `lat` a `lon`: bod, pro který je předpověď.", "`code` (okres code, LAU 1), `name`, `lat` and `lon`: the point the forecast is for.")],
    ]),
    ...group("forecast.", [
      ["`generated`, `method`, `time_zone_of_parts`", L("Kdy byla předpověď vytvořena (UTC), věta o tom, jak vznikla, a časové pásmo částí dne (`Europe/Prague`).", "When the forecast was made (UTC), a sentence on how it was made and the time zone of the parts of day (`Europe/Prague`).")],
      ["`units`", L("Jednotka každé hodinové řady.", "The unit of every hourly series.")],
      ["`sources`", L("U dalších veličin, odkud jsou: `blend` je naše kombinace modelů, `reference` medián nejlepších modelů. Veličiny, které tu nejsou (teplota, srážky, vítr, oblačnost, svit), jsou vždy z kombinace.", "For the further variables, where they come from: `blend` is our combination of the models, `reference` the median of the best models. Variables not listed (temperature, precipitation, wind, cloud, sunshine) are always from the combination.")],
    ]),
    ...group("forecast.hourly.", [
      ["`time`", L("Čas každé hodiny v UTC. Pole se čtou po indexu: i-tá hodnota každé řady patří k i-tému času.", "The time of every hour in UTC. Read the arrays by index: the i-th value of every series belongs to the i-th time.")],
      ["`temperature_2m`, `temperature_2m_lo`, `temperature_2m_hi`", L("Teplota ve 2 m (°C) a spodní a horní konec 80% rozpětí kolem ní („±“ v grafu), spočítaného z chyb naší předpovědi za posledních 30 dní.", "Temperature at 2 m (°C) and the lower and upper end of the 80 % range around it (the “±” in the chart), from the errors of our forecast over the last 30 days.")],
      ["`precipitation`", L("Srážky (mm) za hodinu, která v daném čase končí.", "Precipitation (mm) in the hour that ends at the time.")],
      ["`wind_speed_10m`, `wind_gusts_10m`, `wind_direction_10m`", L("Průměrný vítr v 10 m (m/s), nejsilnější náraz v hodině (m/s) a směr, odkud vane (°; `null` v bezvětří).", "Mean wind at 10 m (m/s), the highest gust in the hour (m/s) and the direction it blows from (°; `null` in calm).")],
      ["`cloud_cover`, `cloud_cover_low`", L("Celková a nízká oblačnost (%). Celková je průměr modelů opravený podle pozorování ČHMÚ.", "Total and low cloud cover (%). The total is the mean of the models corrected against ČHMÚ observations.")],
      ["`sunshine_duration`, `shortwave_radiation`", L("Sluneční svit (s za hodinu) a krátkovlnné záření (W/m²).", "Sunshine (s per hour) and shortwave radiation (W/m²).")],
      ["`relative_humidity_2m`, `dew_point_2m`, `pressure_msl`", L("Relativní vlhkost (%), rosný bod (°C) a tlak přepočtený na hladinu moře (hPa).", "Relative humidity (%), dew point (°C) and pressure reduced to sea level (hPa).")],
      ["`visibility`, `snowfall`, `snow_depth`, `snow_depth_water_equivalent`", L("Dohlednost (km, nejvýš 20), nový sníh za hodinu (cm), výška sněhu (cm) a vodní hodnota sněhu (mm).", "Visibility (km, up to 20), new snow per hour (cm), snow depth (cm) and its water equivalent (mm).")],
    ]),
    ...group("forecast.parts.", [
      ["`day`, `part`", L("Den (pražský čas) a část dne: `night`, `morning`, `afternoon`, `evening` a `day` (celý den).", "The day (Prague time) and the part of day: `night`, `morning`, `afternoon`, `evening` and `day` (the whole day).")],
      ["`tmin`, `tmax`", L("Nejnižší a nejvyšší teplota v části dne (°C).", "Lowest and highest temperature in the part (°C).")],
      ["`precipitation`, `rain_probability`, `heavy_rain_probability`, `heavy_rain`", L("Úhrn srážek (mm), pravděpodobnost srážek ≥ 0,2 mm (0 až 1), pravděpodobnost ≥ 5 mm (0 až 1) a ano/ne, zda se čeká aspoň 5 mm.", "Precipitation total (mm), the probability of at least 0.2 mm (0 to 1), of at least 5 mm (0 to 1) and yes/no whether at least 5 mm is expected.")],
      ["`wind`, `gust`, `gust_over_threshold`", L("Průměrný vítr a nejsilnější náraz (m/s) a ano/ne, zda náraz dosáhne 13,5 m/s.", "Mean wind and the highest gust (m/s) and yes/no whether the gust reaches 13.5 m/s.")],
      ["`cloud`, `sunshine`, `symbol`", L("Oblačnost (%), sluneční svit (h) a symbol počasí (`clear`, `partly`, `cloudy`, `showers`, `rain`).", "Cloud cover (%), sunshine (h) and the weather symbol (`clear`, `partly`, `cloudy`, `showers`, `rain`).")],
      ["`sunrise`, `sunset`", L("Východ a západ slunce (pražský čas); je to astronomie, ne předpověď.", "Sunrise and sunset (Prague time); astronomy, not a forecast.")],
      ["`night_min`, `coldest_site`, `coldest_min`, `frost_probability`, `frost`, `ground_min`, `ground_frost`", L("Mráz, jen u řádků `night` a `day` data, kdy noc končí (jinde `null`): opravené noční minimum ve 2 m (°C), nejmrazivější stanice okresu a její minimum, pravděpodobnost mrazu (0 až 1), ano/ne mráz (minimum ≤ 1 °C), odhad přízemního minima 5 cm nad zemí a ano/ne přízemní mrazík (≤ 0 °C).", "Frost, only on the `night` and `day` rows of the date a night ends (`null` elsewhere): the corrected night minimum at 2 m (°C), the okres's most frost-prone station and its minimum, the probability of frost (0 to 1), yes/no frost (minimum ≤ 1 °C), the estimated minimum 5 cm above the ground and yes/no ground frost (≤ 0 °C).")],
    ]),
    ] }],
  ];
}
