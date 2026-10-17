# MeteoVerdict 🐸

[![CI](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/ci.yml/badge.svg)](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/ci.yml)
[![Last updated](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FJerryWoof%2FMeteoVerdict%2Fmain%2Fsite%2Fdata%2Fbadge.json)](https://github.com/JerryWoof/MeteoVerdict/actions/workflows/daily.yml)

**Which weather model gets Czechia right?** Weather apps disagree, and nobody tells you
which forecast to trust where you live. MeteoVerdict checks every day how well 11
weather models forecast what ČHMÚ stations then measured, ranks them in every okres,
and combines them into its own forecast.

**→ [jerrywoof.github.io/MeteoVerdict](https://jerrywoof.github.io/MeteoVerdict/)** (Czech and English)

| Page | What you get |
|---|---|
| [Forecast map](https://jerrywoof.github.io/MeteoVerdict/tv.html) | TV-style weather map for the next six days: temperature, rain, wind and cloud in every okres, by night, morning, afternoon and evening, with sunrise and sunset and play buttons |
| [On an e-ink display](https://github.com/JerryWoof/MeteoVerdict-TRMNL) | today and tomorrow, the next 24 hours or five days for your okres on a TRMNL display, in Czech or English |
| [Score map](https://jerrywoof.github.io/MeteoVerdict/) | the most accurate model in every okres; click an okres to see why it wins |
| [Model comparison](https://jerrywoof.github.io/MeteoVerdict/compare.html) | all models ranked for Czechia, a kraj or an okres, with confidence intervals, and every model's error hour by hour after each run (H+1 to H+120) |
| [Forecast per okres](https://jerrywoof.github.io/MeteoVerdict/forecast.html) | the hourly combined forecast for one okres next to the best single model, with sunrise, sunset and the nights shaded |
| [Stations](https://jerrywoof.github.io/MeteoVerdict/station.html) | what the weather was like at a ČHMÚ station, day by day back to the start of its records (weather symbol, max/min, precipitation, snow, sunshine, gusts, phenomena; week and month views with a summary; the course of recent days), and every element it measures, with its history |
| [Radar](https://jerrywoof.github.io/MeteoVerdict/radar.html) | ČHMÚ weather radar over Czechia: the last hours with the nowcast for the next hour, hourly precipitation from radar and rain gauges, and archived days |
| [Open data](https://jerrywoof.github.io/MeteoVerdict/api.html) | the forecast and the ranking of every okres as JSON or CSV, free, no key |

## How it works

1. **Measure.** Hourly observations from about 470 automatic ČHMÚ stations and daily
   totals from about 280 rain gauges.
2. **Compare.** What each model forecast 1–5 days earlier for the same place and hour
   (Open-Meteo Previous Runs API, at the station's elevation).
3. **Score.** Errors for 2 m temperature, precipitation and 10 m wind (MAE, bias, RMSE,
   hit rates for rain and heat days), compared only on the days every model covers.
4. **Rank.** Per okres, kraj, elevation class and Czechia, with bootstrap confidence
   intervals, so a near tie is shown as a tie. Okresy with fewer than three stations
   borrow the nearest stations of their neighbours, so every okres is ranked.
5. **Combine.** Our forecast mixes all models for each okres and lead day, weighted by
   how well each did there over the last 90 days (temperature and wind also corrected
   for their usual bias), as operational consensus forecasts such as NOAA's National
   Blend of Models do ([research](docs/forecast-research.md)).

Everything runs on GitHub Actions: scores are updated every morning, the forecast four
times a day (04:50, 10:50, 16:50 and 22:50 UTC, after each model run). What the results mean and where they can mislead:
[methodology](docs/methodology.md).

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
([details](docs/methodology.md#does-it-beat-the-best-single-model-roadmap-64)). Next: a
write-up of the findings ([roadmap](ROADMAP.md)).

## Use the data

```bash
curl -s https://jerrywoof.github.io/MeteoVerdict/api/v1/okresy/CZ0201.json
```

Every okres has a JSON and a CSV file with the combined hourly forecast, the parts of
the day and the model ranking with weights. Codes, fields and examples:
[open data](docs/open-data.md). Licence CC BY-SA 4.0 (credit MeteoVerdict, Open-Meteo.com
and ČHMÚ).

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
- Generated scores and maps: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/),
  because they include UK Met Office data (ShareAlike).
- Details and rules (non-commercial use, rate limits): [docs/licensing.md](docs/licensing.md).
- Code: [MIT](LICENSE).

This is a non-commercial, independent project, not affiliated with ČHMÚ or Open-Meteo.
