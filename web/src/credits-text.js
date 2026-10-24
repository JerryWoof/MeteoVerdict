// The credits page (zdroje.html): every source, its licence and what we use from it. The
// footer no longer carries these; docs/licensing.md, rule 2, is met by this page (linked from
// every page) and by the attribution control on every map.
const REPO = "https://github.com/JerryWoof/MeteoVerdict";
const CC_BY = "[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)";
const CC_BY_SA = "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)";
const OPEN_METEO_LICENCE = "[open-meteo.com/en/licence](https://open-meteo.com/en/licence)";

export const CREDITS = {
  cs: {
    title: "Zdroje dat a licence",
    blocks: [
      ["p", "MeteoVerdict stojí na otevřených datech. Zde je úplný výčet zdrojů, jejich licencí a toho, co z nich používáme. Zdroje podkladové mapy jsou také přímo v mapě (ikona ⓘ vpravo dole)."],
      ["table", {
        head: ["Zdroj", "Co z něj používáme", "Licence", "Odkaz"],
        rows: [
          ["ČHMÚ", "měření stanic, radar (odrazivost, výška odrazů), družicové snímky Meteosat, předpověď ALADIN", CC_BY, "[opendata.chmi.cz](https://opendata.chmi.cz/)"],
          ["EUMETSAT", "družicová data Meteosat v snímcích ČHMÚ: contains modified EUMETSAT Meteosat data (rok dat), zpracoval ČHMÚ", CC_BY, "[eumetsat.int](https://www.eumetsat.int/)"],
          ["Open-Meteo.com", "předpovědi modelů (rozhraní a otevřená data)", CC_BY, "[open-meteo.com](https://open-meteo.com/)"],
          ["DWD, ECMWF, KNMI, DMI, GeoSphere Austria, CMA", "modely ICON, IFS a AIFS, HARMONIE, AROME, GRAPES (přes Open-Meteo)", CC_BY, OPEN_METEO_LICENCE],
          ["NOAA", "modely GFS a AIGFS (přes Open-Meteo)", "volné dílo vlády USA", "[weather.gov/disclaimer](https://www.weather.gov/disclaimer)"],
          ["Météo-France", "modely ARPEGE (přes Open-Meteo)", "[Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/)", "[meteofrance.com](https://meteofrance.com/)"],
          ["UK Met Office", "modely UKMO (přes Open-Meteo)", CC_BY_SA, OPEN_METEO_LICENCE],
          ["Environment and Climate Change Canada", "model GEM (přes Open-Meteo). Data Source: Environment and Climate Change Canada", "[licence ECCC](https://eccc-msc.github.io/open-data/licence/readme_en/)", "[eccc-msc.github.io](https://eccc-msc.github.io/open-data/)"],
          ["Japan Meteorological Agency", "model GSM (přes Open-Meteo). Source: Japan Meteorological Agency (upraveno)", "[podmínky JMA](https://www.jma.go.jp/jma/en/copyright.html), slučitelné s CC BY 4.0", "[jma.go.jp](https://www.jma.go.jp/)"],
          ["ČÚZK", "hranice krajů a okresů, názvy a polohy obcí", CC_BY, "[cuzk.gov.cz](https://www.cuzk.gov.cz/)"],
          ["ČSÚ", "počet obyvatel obcí (DataStat, sada OBY02A)", "volné užití s uvedením zdroje", "[data.csu.gov.cz](https://data.csu.gov.cz/datastat/data/SADA/OBY02A)"],
          ["OpenFreeMap, OpenMapTiles, OpenStreetMap", "podkladová mapa při přiblížení: © OpenMapTiles, © OpenStreetMap contributors", "[ODbL](https://www.openstreetmap.org/copyright)", "[openfreemap.org](https://openfreemap.org/)"],
          ["Terrain Tiles", "reliéf podkladové mapy: EU-DEM © Copernicus, SRTM/GMTED2010 USGS, DGM Österreich, ETOPO1 NOAA", "otevřená data, zdroje je třeba uvést", "[tilezen/joerd](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)"],
        ],
      }],
      ["h", "Co jsme s daty udělali"],
      ["p", "Hodnoty zpracoval MeteoVerdict: výběr bodů stanic a okresů, převod jednotek, hodnocení a kombinace modelů. Snímky radaru a družic jsme oříznuli a převedli, výšku odrazů, pohyb a bouřkové buňky z nich odvodili. Žádný z uvedených poskytovatelů tyto úpravy neschvaluje ani nepotvrzuje."],
      ["h", "Naše data"],
      ["p", `Naše data (skóre, pořadí modelů, předpovědi, výstupy AI) jsou pod licencí ${CC_BY_SA}, odvozené snímky radaru a družic pod ${CC_BY}. Kód je pod licencí MIT. Podrobnosti v [Metodice](methodology.html), na stránce [Data](data.html) a v [popisu zdrojů a metody](${REPO}/blob/main/docs/methodology.md).`],
    ],
  },
  en: {
    title: "Data sources and licences",
    blocks: [
      ["p", "MeteoVerdict is built on open data. Here is the full list of sources, their licences and what we use from each. The sources of the base map are also credited on the map itself (the ⓘ icon at the bottom right)."],
      ["table", {
        head: ["Source", "What we use", "Licence", "Link"],
        rows: [
          ["ČHMÚ", "station observations, radar (reflectivity, echo tops), Meteosat satellite images, ALADIN forecast", CC_BY, "[opendata.chmi.cz](https://opendata.chmi.cz/)"],
          ["EUMETSAT", "Meteosat data in ČHMÚ's images: contains modified EUMETSAT Meteosat data (year of the data), processed by ČHMÚ", CC_BY, "[eumetsat.int](https://www.eumetsat.int/)"],
          ["Open-Meteo.com", "model forecasts (API and open data)", CC_BY, "[open-meteo.com](https://open-meteo.com/)"],
          ["DWD, ECMWF, KNMI, DMI, GeoSphere Austria, CMA", "ICON, IFS and AIFS, HARMONIE, AROME, GRAPES models (via Open-Meteo)", CC_BY, OPEN_METEO_LICENCE],
          ["NOAA", "GFS and AIGFS models (via Open-Meteo)", "US government work", "[weather.gov/disclaimer](https://www.weather.gov/disclaimer)"],
          ["Météo-France", "ARPEGE models (via Open-Meteo)", "[Licence Ouverte 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/)", "[meteofrance.com](https://meteofrance.com/)"],
          ["UK Met Office", "UKMO models (via Open-Meteo)", CC_BY_SA, OPEN_METEO_LICENCE],
          ["Environment and Climate Change Canada", "GEM model (via Open-Meteo). Data Source: Environment and Climate Change Canada", "[ECCC licence](https://eccc-msc.github.io/open-data/licence/readme_en/)", "[eccc-msc.github.io](https://eccc-msc.github.io/open-data/)"],
          ["Japan Meteorological Agency", "GSM model (via Open-Meteo). Source: Japan Meteorological Agency (edited)", "[JMA terms](https://www.jma.go.jp/jma/en/copyright.html), compatible with CC BY 4.0", "[jma.go.jp](https://www.jma.go.jp/)"],
          ["ČÚZK", "boundaries of kraje and okresy, names and positions of municipalities", CC_BY, "[cuzk.gov.cz](https://www.cuzk.gov.cz/)"],
          ["ČSÚ", "population of municipalities (DataStat, set OBY02A)", "free use with the source named", "[data.csu.gov.cz](https://data.csu.gov.cz/datastat/data/SADA/OBY02A)"],
          ["OpenFreeMap, OpenMapTiles, OpenStreetMap", "base map when zoomed in: © OpenMapTiles, © OpenStreetMap contributors", "[ODbL](https://www.openstreetmap.org/copyright)", "[openfreemap.org](https://openfreemap.org/)"],
          ["Terrain Tiles", "base map relief: EU-DEM © Copernicus, SRTM/GMTED2010 USGS, DGM Österreich, ETOPO1 NOAA", "open data, sources to be credited", "[tilezen/joerd](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)"],
        ],
      }],
      ["h", "What we did to the data"],
      ["p", "Values were processed by MeteoVerdict: extraction at the stations and okres points, unit conversion, scoring and combining the models. Radar and satellite frames were cropped and converted; echo tops, motion and storm cells were derived from them. None of the providers endorses or confirms these changes."],
      ["h", "Our data"],
      ["p", `Our data (scores, model rankings, forecasts, AI outputs) is under ${CC_BY_SA}; derived radar and satellite frames under ${CC_BY}. The code is MIT. Details in the [Methodology](methodology.html), on the [Data](data.html) page and in the [description of sources and method](${REPO}/blob/main/docs/methodology.md).`],
    ],
  },
};
