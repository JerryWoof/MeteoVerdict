# MeteoVerdict: Architecture & Roadmap

> Which weather model is most accurate where in Czechia?
> Daily verification of public NWP models against ČHMÚ station observations,
> published as a static web map with rankings per okres and our own combined forecast.

Package: `meteoverdict` · CLI: `mvd`

---

## 1. How it works

```
          ┌──────────────────────┐        ┌───────────────────────────┐
          │ ČHMÚ open data       │        │ Open-Meteo Previous Runs  │
          │ opendata.chmi.cz     │        │ API (forecasts issued     │
          │ station observations │        │ 1–5 days before each hour)│
          └──────────┬───────────┘        └─────────────┬─────────────┘
                     │  fetch-obs                       │  fetch-fc
                     ▼                                  ▼
              ┌─────────────────────────────────────────────────┐
              │  Raw store: Parquet, partitioned by month       │
              │  obs/YYYY-MM.parquet   fc/YYYY-MM.parquet       │
              └───────────────────────┬─────────────────────────┘
                                      │  score
                                      ▼
              ┌─────────────────────────────────────────────────┐
              │  Scores: per station × model × variable ×       │
              │  lead day × day  (small, committed to repo)     │
              └───────────┬───────────────────────┬─────────────┘
                          │ report                │ build-site
                          ▼                       ▼
                 "last updated" badge       GitHub Pages web map
```

**The key trick:** Open-Meteo's Previous Runs API returns, for any past hour, what
each model predicted 1, 2, 3… days earlier (`temperature_2m_previous_day1`, …).
Most models are archived since January 2024. So we do not need to archive
forecasts ourselves, and we can **backfill ~2 years of history on day one** for most
models. Measured exceptions: models added to Open-Meteo later have less history,
notably ČHMÚ ALADIN (from 2026-06-24), and some archives have gaps (UK Met Office) or
start later for one variable (ARPEGE wind); see `docs/data-sources.md#models`.

### Components

| Part | Tech | Where it runs |
|---|---|---|
| Python package + CLI (`mvd`) | Python 3.12, `uv`, `httpx`, `polars`, `duckdb` | anywhere |
| Daily data pipeline | GitHub Actions cron (free for public repos) | GitHub |
| Raw data store | Monthly Parquet files as GitHub Release assets (`data-YYYY-MM`) | GitHub Releases |
| Aggregated scores | `site/data/*.json` committed by the pipeline bot | repo |
| README badge | `site/data/badge.json` ("last updated"), committed by the daily run | repo |
| Web app | Static: Vite + MapLibre GL + Observable Plot, reads JSON | GitHub Pages |
| ALADIN archive | `mvd archive-aladin` every 3 h, one Parquet per run as Release assets (`aladin-YYYY-MM`) | GitHub Actions |
| Backfill | `mvd backfill` daily within the shared 7,400 Open-Meteo calls: one sweep from today into the past, each 14-day window whole (D+N at all stations and the rain gauges, then the single runs' API history of its days) before the next older one; progress in Releases `data-state` and `runs-state` | GitHub Actions |
| Single runs | `mvd fetch-runs` four times a day: every run from Open-Meteo's open-data bucket on AWS (~100 stations, no API calls, catching up the bucket's last 90 days), the Single Runs API only for the bucket's gaps (≤ 400 calls a day); older runs come with the backfill; progress in Release `runs-state` | GitHub Actions |
| Outlook | `mvd outlook` twice a day: combined forecast for every okres (≈ 340 calls) → `outlook.json` in Release `data-latest` | GitHub Actions |
| Development | Claude scheduled task, weekdays, works from this roadmap, opens PRs | Claude (Cowork) |

Two separate loops:

- **Data loop (no AI):** GitHub Actions runs `mvd daily` every morning and commits fresh scores.
- **Development loop:** Claude takes the next unchecked roadmap item, opens a PR, and the maintainer reviews and merges it.

### Running it

```bash
uv sync
uv run mvd backfill --from 2024-01-01      # one-off history
uv run mvd daily                           # fetch yesterday + score + report
uv run mvd report                          # best model per kraj (Markdown)
cd web && npm i && npm run dev              # local web map
```

### Scope v1

- **Variables:** 2 m temperature (hourly), precipitation (hourly → daily sums), 10 m wind speed.
- **Lead times:** D+1, D+2, D+3 (D+4, D+5 where available). Measured: the short-range
  high-resolution models only reach D+1 (ICON-D2, GeoSphere AROME) or D+2 (ALADIN).
- **Regions:** results at three levels:
  - **station** (finest; ~300 stations with hourly temperature, ~200 with wind, ~430 with
    hourly and ~280 more with daily precipitation),
  - **okres** (77 districts),
  - **kraj** (14 regions), plus an elevation class (lowland < 400 m, upland 400–800 m,
    mountain > 800 m).
  An okres or kraj gets a ranking for a variable only if it has enough stations
  measuring it (threshold set in 2.4); otherwise it is shown as "too few stations".
- **Models** (coverage of CZ verified in 1.3; the list lives in `src/meteoverdict/models.yaml`):
  - ČHMÚ ALADIN CZ 1 km and ALADIN Central Europe 2.3 km
  - DWD ICON-D2 and ICON-EU
  - ECMWF IFS HRES 9 km, ECMWF IFS 0.25° (longer history than HRES) and ECMWF AIFS
  - NOAA GFS
  - UK Met Office global
  - Météo-France ARPEGE Europe
  - GeoSphere Austria AROME (covers CZ)
  - KNMI and DMI HARMONIE-AROME also cover CZ; listed but disabled for v1
- **Metrics:**
  - Temperature and wind: MAE, bias, RMSE.
  - Precipitation: MAE of daily sums, plus POD, FAR and ETS for events of at least 0.1 mm/day and at least 5 mm/day.
- **Ranking:** each station, okres and kraj gets, per variable, the model with the lowest MAE over a rolling 90 days and over all time. Long windows compare models only over the period they all cover (archive starts differ, see `docs/data-sources.md#models`). The ranking only shows a model as better when the difference is significant (bootstrap CI).

### Data & licensing

Full review: `docs/licensing.md`.

- **Code:** MIT. **Published scores and maps:** CC BY-SA 4.0 (they include UK Met Office data, CC BY-SA).
- **Open-Meteo:** CC BY 4.0. Free tier is non-commercial and limited to 10k calls/day and 300k/month. Keep the project non-profit, with no ads; batch locations and use 14-day windows.
- **ČHMÚ open data:** CC BY 4.0 (confirmed in the National Open Data Catalogue); credit ČHMÚ in the README and on the site.
- **Point verification:** forecasts are requested at station lat/lon *with station elevation* (Open-Meteo applies elevation downscaling). Document this, since it affects mountain stations.

---

## 2. Roadmap

Each item should fit one PR (≈ one working session). Check items off in the PR that completes them.

### Phase 0: Skeleton
- [x] 0.1 `pyproject.toml` (uv), package `meteoverdict` (CLI `mvd`), `ruff` + `pytest` config, MIT licence, `.gitignore`
- [x] 0.2 CI workflow: lint + tests on PR
- [x] 0.3 CLI entry point (`typer`) with stub commands: `fetch-obs`, `fetch-fc`, `score`, `report`, `daily`, `backfill`
- [x] 0.4 README skeleton: goal, data sources, attribution, empty leaderboard markers

### Phase 1: Data in
- [x] 1.1 Explore `opendata.chmi.cz/meteorology/climate/{now,recent,historical}`: document paths, formats and licence in `docs/data-sources.md`
- [x] 1.2 Station metadata loader → `stations.parquet` (id, name, lat, lon, elevation, active)
- [x] 1.3 Verify which Open-Meteo models cover CZ and their Previous Runs history start; write `models.yaml`
- [x] 1.4 Station → kraj mapping (point-in-polygon with open kraj boundaries) + elevation class
- [x] 1.4b Okres boundaries (ČÚZK, same pipeline as kraje) + station → okres column
- [x] 1.5 `fetch-obs`: hourly T2m, precip, wind for a date range → normalized Parquet (UTC)
- [x] 1.5b Daily precipitation from the ~280 manual rain-gauge stations (`recent/data/daily`, `SRA`), with ČHMÚ's daily accumulation window
- [x] 1.6 `fetch-fc`: Previous Runs client, batched locations, 14-day windows, retries, rate-limit aware (free tier: 600/min, 5k/h, 10k/day, 300k/month)
- [x] 1.7 Raw store: monthly Parquet partitions; upload/download to GitHub Release assets
- [x] 1.8 Unit tests with recorded fixtures (no network in CI): real ČHMÚ, Open-Meteo and ALADIN samples under `tests/fixtures/`, added with each item 1.1–1.7
- [x] 1.9 Archive ALADIN runs from ČHMÚ open data (kept there only 3 days): station values per run → GitHub Release assets, every 3 h

### Phase 2: Scoring
- [x] 2.1 Align obs/fc (time zones, accumulation periods for precip; AIFS and IFS 0.25° only at their native 6-/3-hourly hours, Open-Meteo interpolates the rest)
- [x] 2.2 Metrics module (MAE, bias, RMSE, POD/FAR/ETS) + tests against hand-computed cases
- [x] 2.3 `score`: daily scores table → `scores/YYYY-MM.parquet`
- [x] 2.4 Aggregations: station / okres / kraj × model × variable × lead × window (90 d, season, all) → JSON, with a minimum station count per region
- [x] 2.5 Bootstrap confidence intervals for ranking
- [x] 2.6 `backfill --from 2024-01-01` (resumable, chunked by month, most recent first; all models and stations since 2024 ≈ 333k Open-Meteo calls, so it must be spread over 2+ months of the free quota)
- [x] 2.7 Score precipitation over ČHMÚ's 06–06 UTC climatological day (`precipitation_24h`): manual rain gauges plus automatic stations, ranked and shown in the README leaderboard
- [x] 2.8 Rain gauges in `backfill` and `daily`: gauge observations per month (they arrive ~1 month late), forecasts at the gauge positions (precipitation only; 28-day requests cost the same as 14-day ones)

### Phase 3: Publish
- [x] 3.1 `report --readme`: leaderboard table (kraj → best model per variable, D+1)
- [x] 3.2 GitHub Actions daily cron: `mvd daily` → commit JSON + README, upload raw data. Forecasts in 14-day windows (≈ 6,900 calls each, any shorter window costs the same). Must fetch yesterday's observations from `now/` every day (kept ~3 days; the current month is not in `recent/` yet) and re-fetch months from `recent/` once published
- [x] 3.3 Data quality checks (missing stations, outliers, stale data) that fail loudly
- [x] 3.4 Badge / "last updated" timestamp in README
- [x] 3.5 Compact score files (float32 sums, small integer counts, summed in 64 bits): about a third smaller, as the daily run downloads all score months

### Phase 4: Web app
- [x] 4.1 Vite + MapLibre scaffold, GitHub Pages deploy workflow
- [x] 4.2 Map: stations as dots and okresy/kraje as choropleth, coloured by best model; legend; "too few stations" state
- [x] 4.3 Controls: variable, lead time, window (90 d / season / all)
- [x] 4.4 Station layer + click → per-model error time series (Observable Plot)
- [x] 4.5 Model comparison page: overall ranking, bias by elevation class
- [x] 4.6 Czech / English toggle

### Phase 5: Depth & outreach
- [x] 5.1a Seasonal breakdowns: windows of all winters, springs, summers and autumns
- [x] 5.1b Diurnal breakdowns: temperature errors at 00, 06, 12 and 18 UTC, where every model is native (e.g. ALADIN vs ICON-D2 at night inversions)
- [x] 5.2a Heavy precipitation: POD/FAR/ETS for days with at least 20 mm (ETCCDI index R20mm), daily and 06–06 totals
- [x] 5.2b Heat days: daily maximum temperature (≥ 30 °C) for models with hourly output at that lead day
- [x] 5.3 Ensemble/"best blend" baseline: does a simple mean beat every single model?
- [x] 5.4 Methodology doc (`docs/methodology.md`) with limitations
- [x] 5.5a Upstream survey: ČHMÚ coverage in `wetterdienst` and their AI policy, measured against the live data (`docs/upstream.md`)
- [ ] 5.5b Propose a `recent`/`now` period for wetterdienst's `chmi/observation` in an upstream issue (from the maintainer's account)
- [ ] 5.6 Write-up / blog post with findings

### Phase 6: Every okres, and our own forecast
- [x] 6.1 Rank every okres: okresy with fewer than 3 stations borrow the nearest stations of their neighbours (≤ 30 km beyond the border), same fair comparison
- [x] 6.2 Combination weights per okres × variable × lead day from the 90-day scores (inverse-MSE weights, bias corrections) and a forecast point per okres → `site/data/forecast.json`
- [x] 6.3 Web: MeteoVerdict forecast for a chosen okres: today's Open-Meteo forecasts of all models combined with the 6.2 weights, next to the best single model
- [ ] 6.4 Verify the combination out of sample (weights from earlier days, scored like a model) and rank it against the best single model; compare training windows of 30, 45 and 90 days and a decaying average (`docs/forecast-research.md`)
  - [x] Out-of-sample test against the best model at the time, the best in hindsight, the mean and every model, with day-bootstrap intervals, per lead day, Czechia and okres: `mvd blend-test` → `site/data/blend-test.json`, daily, shown on the comparison page. First result (24 days, September 2026): never clearly worse except wind D+1 (+0.03 m/s), better for daily precipitation at all lead days and temperature at D+2, D+3, D+5; too short to call
  - [ ] Training windows 30 / 45 / 90 days (`--window`) and a decaying average, once the history is longer than 45 days
- [x] 6.5 Review the combination method against operational practice and the literature (`docs/forecast-research.md`); taper models that end early
- [x] 6.6 TV-style forecast: combined forecast for all okresy by part of day (night, morning, afternoon, evening), with precipitation probability and cloud symbols, refreshed twice a day
- [x] 6.7 TV-style forecast map: symbols and temperatures per okres, day and part-of-day controls, click an okres for details
- [x] 6.8 Forecast map: time controls apart from what the map shows; temperature, rain, wind and cloud at once
- [x] 6.9 Model comparison per kraj and okres: map, intervals chart, skill against the mean, MAE by lead day
- [x] 6.10 Forecast map "play": smooth transitions from night to evening, then the next day, cycling the map colour (temperature → rain → wind → cloud) on each round
- [x] 6.13 Score map: hover, model highlighting, okres finder, and an okres panel explaining why its best model wins (margin and interval, skill against the mean, bias, big misses, winners by lead day and time of day, stations)
- [x] 6.14 Drop the README leaderboard (the maps show the rankings); the daily run commits only the badge and meta.json
- [x] 6.12 Forecast map: "play the day" (night to evening, round and round) and "play the week", each round with the next map colour
- [x] 6.11 Open data: static JSON/CSV per okres (combined hourly forecast, parts of day, ranking and weights) with documentation

---

## 3. Rules for the daily development task

1. Pull `main` and pick the **first unchecked item** whose prerequisites are done.
2. Work on a branch `roadmap/<item-id>-<slug>`. Keep the PR small and focused.
3. Tests and `ruff` must pass locally before opening the PR.
4. PR description covers what changed, how it was tested and any open questions. Tick the roadmap item in the same PR.
5. If an item is too big, split it into sub-items in the roadmap instead of shipping a giant PR.
6. Never push to `main` directly and never merge your own PR.
7. If blocked (API change, unclear decision), open an issue describing the blocker and move to the next independent item.
