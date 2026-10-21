# MeteoVerdict 🐸

[![CI](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/ci.yml/badge.svg)](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/ci.yml)
[![Last updated](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FJerryWoof%2FMeteoVerdict%2Fmain%2Fsite%2Fdata%2Fbadge.json)](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/daily.yml)

**Which weather model gets Czechia right?** Weather apps disagree, and nobody tells you
which forecast to trust where you live. MeteoVerdict checks every day how well 19
weather models forecast what ČHMÚ stations then measured, ranks them in every okres,
and combines them into its own forecast: for every okres and, as a test, for every one
of the 6,258 obce.

**→ [jerrywoof.github.io/MeteoVerdict](https://jerrywoof.github.io/MeteoVerdict/)** (Czech and English)

| Page | What you get |
|---|---|
| [Forecast](https://jerrywoof.github.io/MeteoVerdict/forecast.html) (the experimental MeteoVerdict AI forecast is its default model, with its verification and experiments below the map) | TV-style weather map for the next six days: temperature, rain, wind and cloud in every okres, by night, morning, afternoon and evening, with sunrise and sunset and play buttons. Zoom in for relief, rivers and town names, and the forecast for every obec, biggest places first; "Find a place" goes to any obec and opens its panel |
| [On an e-ink display](https://github.com/JerryWoof/MeteoVerdict-TRMNL) | today and tomorrow, the next 24 hours, five days or the weekend on a TRMNL display, in Czech or English; combined or AI forecast |
| [Score map](https://jerrywoof.github.io/MeteoVerdict/) | the most accurate model in every okres, or "no clear winner" where the data cannot tell; click an okres to see why it wins |
| [Compare](https://jerrywoof.github.io/MeteoVerdict/compare.html) | all models ranked for Czechia, a kraj or an okres, with confidence intervals, and every model's error hour by hour after each run (H+1 to H+120) |
| [Forecast per okres](https://jerrywoof.github.io/MeteoVerdict/forecast-detail.html) | the hourly combined forecast for an okres town next to the best single model, with sunrise, sunset and the nights shaded |
| [Measured](https://jerrywoof.github.io/MeteoVerdict/measured.html) | what ČHMÚ's stations measured, as a map like the forecast's: each station (or each okres, next to what our forecast had said) by day and part of day for the last 30 days, the whole day for 60; and for one station what the weather was like there, day by day back to the start of its records (weather symbol, max/min, precipitation, snow, sunshine, gusts, phenomena; week and month views with a summary; the course of recent days), and every element it measures, with its history. Zoomed in, the map shows the stations by name over relief and rivers. A model selector (MeteoVerdict AI, the blend or any single model, D+1 or D+2) puts a model's forecast at the station's own point and height next to what it measured, with the error, in the station panel and the okres's station list |
| [Radar](https://jerrywoof.github.io/MeteoVerdict/radar.html) | ČHMÚ weather radar over Czechia: the last hours with the nowcast for the next hour, hourly precipitation from radar and rain gauges, and archived days |
| [AI heatmap](https://jerrywoof.github.io/MeteoVerdict/heatmap.html) | experimental: MeteoVerdict AI's temperature at 100 m from the terrain (valleys, slopes, frost hollows), hour by hour; click anywhere for the forecast at that place |
| [Data](https://jerrywoof.github.io/MeteoVerdict/data.html) | the forecast and the ranking of every okres as JSON or CSV, free, no key |

## How it works

1. **Measure.** Hourly observations from about 470 automatic ČHMÚ stations and daily
   totals from about 280 rain gauges.
2. **Compare.** What each model forecast 1–5 days earlier for the same place and hour
   (Open-Meteo Previous Runs API, at the station's elevation).
3. **Score.** Errors for 2 m temperature, precipitation and 10 m wind (MAE, bias, RMSE,
   hit rates for rain and heat days), compared only on the days every model covers.
4. **Rank.** Per okres, kraj, elevation class and Czechia, with block-bootstrap
   confidence intervals and Diebold–Mariano tests, so a near tie is shown as a tie, and
   the probability that each model is the best: the map shows "no clear winner" where
   no model reaches 60 %. Summits and other stations more than 300 m above their okres
   are ranked on their own, not in the okres. Okresy with fewer than three stations
   borrow the nearest stations of their neighbours, so every okres is ranked.
5. **Combine.** Our forecast mixes all models for each okres and lead day, weighted by
   how well each did there over the last 90 days (temperature and wind also corrected
   for their usual bias), as operational consensus forecasts such as NOAA's National
   Blend of Models do ([research](docs/forecast-research.md)).
6. **Every obec.** The same combination for each of the 6,258 obce: every model's
   newest run read at the obce's own grid cell from Open-Meteo's open-data bucket, the
   temperature moved to the obec's height, weighted as its okres
   ([details](docs/data-sources.md#forecast-for-every-obec-mvd-obce-forecast)).

Everything runs on GitHub Actions: scores are updated every morning, the forecast four
times a day (04:50, 10:50, 16:50 and 22:50 UTC, after each model run), the obce right
after it. What the results mean and where they can mislead:
[methodology](docs/methodology.md).

**MeteoVerdict AI (experimental).** The AI forecast and the 100 m heatmap are trained and
computed once a day from this project's data; their code is kept
in a private repository, and the site publishes only their results, scored like every
other model. The AI forecasts temperature, wind and gusts, cloud, sunshine, weather symbol,
precipitation (mm), probability of rain and heavy rain; only sunrise and sunset are astronomy. `api/v1/ai/okresy` is the same file as the combined forecast's with the AI's values
([open data](docs/open-data.md)).

## Models

ČHMÚ ALADIN (1 km and 2.3 km), DWD ICON-D2, ICON-EU and ICON global, ECMWF IFS HRES,
IFS 0.25° and AIFS, NOAA GFS and AIGFS, UK Met Office global, Météo-France ARPEGE Europe
and World, GeoSphere AROME Austria, KNMI and DMI HARMONIE-AROME, ECCC GEM Global, JMA GSM
and CMA GRAPES (19 models), plus the mean of all models as a baseline every model has to
beat. ALADIN's "1 km" is ČHMÚ's 2.3 km run post-processed onto a 1 km grid, so the two
ALADINs are near-duplicates. The list
is in [`models.yaml`](src/meteoverdict/models.yaml); archive depth and lead days per
model are in [data sources](docs/data-sources.md#models).

## Status

Early days. The first results (October 2026) cover late September, and the history
fills in from today into the past as the backfill runs (back to 2025-10-01 around
January 2027, to 2024 around April 2027) and ČHMÚ publishes its checked monthly
observations. ALADIN has forecast history only from
June 2026. Our combined forecast is now tested out of sample every day against the
model our ranking would have picked: on the first 24 test days (September 2026) it was
better for daily precipitation and mostly better or equal for temperature and wind,
slightly worse only for wind on the next day; too little history to call it settled
([details](docs/methodology.md#does-it-beat-the-best-single-model-roadmap-64)). The
forecast for every obec and MeteoVerdict AI are tests that may change or go: nothing is
measured at the obce themselves, and an obce forecast is not yet checked against stations
held out of the weights. Next: a
write-up of the findings ([roadmap](ROADMAP.md)).

## Use the data

```bash
curl -s https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/CZ0201.json
```

Every okres has a JSON and a CSV file with the combined hourly forecast, the parts of
the day and the model ranking with weights. Codes, fields and examples:
[open data](docs/open-data.md). Licence CC BY-SA 4.0 (credit MeteoVerdict, Open-Meteo.com
and ČHMÚ).

The forecast for every obec is public too, but not versioned:
`data/scores/forecast/obce-{code}.json` per okres (name, position, height, population,
hourly temperature, precipitation and wind).

On an e-ink display: [MeteoVerdict for TRMNL](https://github.com/JerryWoof/MeteoVerdict-TRMNL)
shows today and tomorrow, the next 24 hours or five days for your okres.

## Run it yourself

```bash
uv sync && uv run mvd --help          # Python 3.12 via uv
cd web && npm ci && npm run dev       # the pages at http://localhost:5173
```

Commands, data store, workflows and the web pages: [docs/development.md](docs/development.md).

## Attribution & licence

- Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): from its APIs and, for the
  single model runs, from its open-data bucket on AWS
  ([Registry of Open Data](https://registry.opendata.aws/open-meteo/), `s3://openmeteo`).
- Observations and ALADIN forecasts: Czech Hydrometeorological Institute (ČHMÚ / CHMI),
  [opendata.chmi.cz](https://opendata.chmi.cz/), licensed under
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). We extract station values
  and convert units.
- Forecast models via Open-Meteo: DWD (ICON), ECMWF (IFS, AIFS), NOAA (GFS, AIGFS),
  Météo-France (ARPEGE, Licence Ouverte 2.0), GeoSphere Austria (AROME), KNMI and DMI,
  Environment and Climate Change Canada (GEM, Data Server End-use Licence), the Japan
  Meteorological Agency (GSM), the China Meteorological Administration (GRAPES) and the
  UK Met Office ([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)).
- Okres and kraj boundaries: © ČÚZK (INSPIRE Administrative Units), CC BY 4.0, via
  [siwekm/czech-geojson](https://github.com/siwekm/czech-geojson); simplified by
  `scripts/build_regions.py`.
- ALADIN station archive (release assets `aladin-YYYY-MM`): CC BY 4.0.
- ČHMÚ station data archive (release assets `chmi-*`, every element of every station,
  [inventory](docs/chmi-data.md)): CC BY 4.0, values unchanged.
- Weather radar: ČHMÚ, [opendata.chmi.cz](https://opendata.chmi.cz/meteorology/weather/radar/),
  CC BY 4.0; archived per day in the release assets `radar-YYYY-MM` (CC BY 4.0), PNG frames
  cropped to the data area for the radar page.
- Population of the obce: [ČSÚ](https://data.csu.gov.cz/datastat/data/SADA/OBY02A)
  (1 January); obce and their positions: ČÚZK RÚIAN, CC BY 4.0.
- Base map when zoomed in: [OpenFreeMap](https://openfreemap.org/),
  [© OpenMapTiles](https://www.openmaptiles.org/),
  [© OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL); relief
  and the obce's heights: [Terrain Tiles](https://github.com/tilezen/joerd/blob/master/docs/attribution.md)
  (EU-DEM © Copernicus, SRTM/GMTED2010 USGS, DGM Österreich, ETOPO1 NOAA).
- Generated scores and maps: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
  because they include UK Met Office data (ShareAlike).
- Details and rules (non-commercial use, rate limits): [docs/licensing.md](docs/licensing.md).
- Code: [MIT](LICENSE).

This is a non-commercial, independent project, not affiliated with ČHMÚ or Open-Meteo.
