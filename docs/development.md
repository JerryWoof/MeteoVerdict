# Development

How to run MeteoVerdict yourself: the command-line pipeline (`mvd`), the web pages and
the automated workflows. What the numbers mean is in [methodology.md](methodology.md);
file formats and API details are in [data-sources.md](data-sources.md).

## Setup and checks

Requires [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you) and, for the
web pages, Node 22.

```bash
uv sync                         # create .venv with dev tools
uv run mvd --help               # list commands
uv run ruff check . && uv run ruff format --check . && uv run pytest
cd web && npm ci && npm test && npm run dev   # local pages at http://localhost:5173
```

CI runs the same checks on every pull request. Tests never use the network; external
data comes from recorded fixtures in `tests/fixtures/`. Dates are `YYYY-MM-DD` in UTC.

## The pipeline

| Step | Command | Output |
|---|---|---|
| Stations | `mvd stations` | `data/stations.parquet` |
| Observations | `mvd fetch-obs`, `mvd fetch-gauges` | `data/obs/YYYY-MM.parquet`, `data/obs-extra/YYYY-MM.parquet` (not yet verified elements) |
| Forecasts (archive) | `mvd fetch-fc`, `mvd backfill` | `data/fc/YYYY-MM.parquet` |
| Scores | `mvd score` | `data/scores/YYYY-MM.parquet` |
| Rankings | `mvd aggregate` | `data/aggregates.parquet`, `site/data/**/*.json` |
| Single runs (all models) | `mvd fetch-runs` | `data/runs/YYYY-MM.parquet`, `data/runs-state.json` |
| Error by lead hour | `mvd leads` | `site/data/leads.json`, `leads-aladin.json`, `leads-aladin-kraj.json`, `leads-bands-{90d,all}[-kraj].json` |
| Event skill for farmers | `mvd farm` | `site/data/farm.json` |
| Everything daily | `mvd daily` | all of the above from the stored data |
| ČHMÚ archive (every element) | `mvd chmi-archive`, `mvd chmi-mirror DIR` | releases `chmi-*` ([format](data-sources.md#chmi-archive)) |
| Station pages | `mvd station-pages` | `site/data/station/<WSI>.json` |
| Observed map (no page shows it now; still published) | `mvd observed-map` | `site/data/observed/<YYYY-MM-DD>.json`, `index.json` ([format](data-sources.md#observed-map)) |
| Checks | `mvd check` | exit 1 on stale data or many silent stations |
| Which stations score the models | `mvd station-check` | Markdown ([docs/station-check.md](station-check.md)) |

### Stations

```bash
uv run mvd stations             # ČHMÚ station metadata → data/stations.parquet
uv run mvd models [--all]       # the compared weather models (from models.yaml)
```

`data/stations.parquet` has one row per station: `id` (WIGOS id), `gh_id` (ČHMÚ id),
`name`, `lat`, `lon`, `elevation` (m), `active`, `okres_code` (LAU 1, e.g. `CZ0642`),
`okres`, `kraj_code` (NUTS 3, e.g. `CZ064`), `kraj` and `elevation_class` (`lowland`
< 400 m, `upland` 400–800 m, `mountain` > 800 m). Active stations are those in today's
ČHMÚ list; stations closed since 2024-01-01 are kept as inactive so the backfill can
still use them. Stations outside Czechia are dropped (up to 2 km outside the border
still counts, for stations on the border line). Use `--out PATH` to write elsewhere.

### Observations

```bash
uv run mvd fetch-obs --start 2026-09-01 --end 2026-09-30   # → data/obs/2026-09.parquet
```

One Parquet file per month (`station_id`, `time` in UTC, `variable`, `value`, ČHMÚ
`quality` code, `source`) for `temperature_2m` (°C), `wind_speed_10m` (m/s) and
`precipitation` (mm in the hour ending at `time`). Running it again replaces the values
for the same station, time and variable
([details](data-sources.md#hourly-observations-mvd-fetch-obs)).

### Forecasts

```bash
uv run mvd fetch-fc --start 2026-09-01 --end 2026-09-14 --dry-run   # how many API calls?
uv run mvd fetch-fc --start 2026-09-01 --end 2026-09-14             # → data/fc/2026-09.parquet
uv run mvd backfill --from 2024-01-01 --max-calls 6000              # resumable
```

`mvd fetch-fc` stores, per station, hour, model and lead day (D+1 … D+5), the forecast
temperature, precipitation and wind from the Open-Meteo Previous Runs API. The free API
allows 10,000 weighted calls a day and 300,000 a month; 14 days for all models and
stations cost about 6,900, so `--max-calls` (default 9,000) stops a run in time and
keeps what was fetched ([details](data-sources.md#fetching-mvd-fetch-fc)).
`mvd backfill` fills the history newest first in 14-day windows and remembers its
progress, so it can run a little every day: each window's D+N at every station and the
rain gauges, then the single runs' API history of the same days (`--no-runs-history`
leaves it out), before the next older window
([details](data-sources.md#backfill-mvd-backfill)).

### Scores and rankings

```bash
uv run mvd score --start 2026-09-01 --end 2026-09-30   # → data/scores/2026-09.parquet
uv run mvd aggregate                                   # → data/aggregates.parquet, site/data
uv run mvd report                                      # best model per kraj as Markdown
uv run mvd station-check --out check.md                # rankings with station subsets, odd stations
```

`mvd score` pairs observations and forecasts and writes one row per day, station,
model, lead day and variable with additive error sums
([details](data-sources.md#daily-scores-mvd-score)). `mvd aggregate` combines them per
station, okres, kraj, elevation class and Czechia over the last 90 days, the current
season and all time, compares models only on the station-days they all cover, and lets
okresy with fewer than three stations borrow the nearest stations of their neighbours
([details](data-sources.md#aggregates-mvd-aggregate)).

### Combined forecast

The combined forecast's method is not part of this repository. Its files (`outlook.json`,
`outlook-hourly.json`, `outlook-models.zip`, `obce.zip`, …)
are published in the release `data-latest`, its archives in `outlook-archive`; the pages
and `mvd aggregate` (the forecast pages' `forecast/<okres>.json`) read them from there.

### Daily run

```bash
uv run mvd daily             # capture observations, re-score, aggregate, write the JSON
```

Uses no Open-Meteo calls (forecasts come from the backfill). It captures the last three
days of observations, re-scores the last 100 days, aggregates and ranks everything and
writes `site/data` and the "last updated" badge
([details](data-sources.md#daily-pipeline-mvd-daily)).

## Data store

Monthly files are kept as assets of the GitHub releases `data-YYYY-MM` (`obs-`, `fc-`
and `scores-YYYY-MM.parquet`, CC BY-SA 4.0). Each asset's label is the file's SHA-256,
so unchanged files are skipped in both directions.

```bash
export GITHUB_TOKEN=… GITHUB_REPOSITORY=JerryWoof/MeteoVerdict
uv run mvd store download --from 2026-01 --to 2026-09   # into data/obs and data/fc
uv run mvd store upload                                  # only files that changed
```

The latest results are in the release `data-latest`: `aggregates.parquet`,
`site-data.zip` (unzip it into `site/data` to run the pages locally with data),
`outlook.json` and `outlook-hourly.json`.

**Single runs.** `mvd fetch-runs` stores each 00, 06, 12 and 18 UTC run of all models at
the ~100 stations of `src/meteoverdict/data/run-stations.csv`: first from Open-Meteo's
open-data bucket on AWS (every run of the last 90 days not stored yet, no API calls, at
most `--bucket-minutes`), then from the Single Runs API (free tier) within `--max-calls`
(default 100): the model-runs the bucket lacks once 24 h old, then the runs older than
the bucket's window from the start of the month it starts in (older runs come with
`mvd backfill`, window by window). `--source bucket|api` runs one of the two,
`--run 2026-10-12T06` given runs, `--dry-run` prints what is left and its cost. Progress
is in `data/runs-state.json`; `--github-release` keeps the month files and the state in
the releases `runs-YYYY-MM` and `runs-state`
([details](data-sources.md#single-runs-mvd-fetch-runs)). The station subset is rebuilt
only on purpose with `uv run scripts/build_run_stations.py`, and then the grid cells of
the bucket's models with `uv run mvd bucket-cells` (network, ~1 minute; commit
`src/meteoverdict/data/bucket-cells.csv`).

```bash
uv run mvd fetch-runs --dry-run                       # runs left and their cost
uv run mvd fetch-runs --source bucket                 # the newest runs, no API calls
uv run mvd fetch-runs --run 2026-10-16T00             # one given run (bucket, then API)
uv run mvd fetch-runs --source api --run 2026-07-01T00 --max-calls 800  # API only
```

**Error by lead hour.** `mvd leads` verifies every model's single runs of the last
`--runs-days` (90) days hour by hour (H+1 … H+120) on the fair set and writes
`site/data/leads.json` (the comparison page is gone; the file stays published); it also verifies every archived ALADIN
run of the last `--days` (30) days (H+1 … H+72) into `leads-aladin.json` and
`leads-aladin-kraj.json`. With `--bands` (default) it also ranks the models by lead
band (H+1–6 … H+49–72) over the last 90 days and every single run since `--bands-since`
(default: all) into `leads-bands-90d.json`, `leads-bands-all.json` and their `-kraj`
files ([method](methodology.md#ranking-by-lead-band-hours-ahead)); about a minute and
under 5 GB of memory for four months of runs. `--github-release` downloads the single runs, the archived
runs and the observation months first (read only), `--publish` also puts the JSON into
`data-latest` ([details](data-sources.md#error-by-lead-hour-mvd-leads)).

**ČHMÚ archive.** `mvd chmi-archive` keeps every element of every ČHMÚ station in
every resolution (10 min to yearly, back to 1775) as Parquet in the releases `chmi-*`,
about 3 GB in total ([inventory](chmi-data.md), [format](data-sources.md#chmi-archive));
`mvd chmi-mirror DIR` copies it to a local disk, skipping unchanged files.

**Event skill for farmers.** `mvd farm` verifies the same single runs as yes/no events:
frost nights (≤ 0 and ≤ −2 °C), gusts (≥ 10, 15, 20 m/s in a 3-hour block) and 3-hour
rain (≥ 0.5, 2, 5 mm), per model and lead time bin, and writes `site/data/farm.json`;
`--github-release` and `--publish` as for `mvd leads`
([details](data-sources.md#event-skill-for-farmers-mvd-farm)).

**ALADIN archive.** ČHMÚ keeps ALADIN runs online for only three days, so
`mvd archive-aladin --github-release` saves temperature, wind and precipitation at every
station for every run and lead hour (0–72 h) into the releases `aladin-YYYY-MM`
([format](data-sources.md#aladin-archive)).

**Radar archive.** ČHMÚ keeps its radar composites online for about seven days, so
`mvd archive-radar --products observed --stations data/stations.parquet --github-release`
packs every complete UTC day into one tar per product (max reflectivity, CAPPI 2 km,
echo tops, MERGE precipitation; HDF5 and PNG) in the releases `radar-YYYY-MM`, plus the
hourly MERGE grids, MERGE at the stations and the radar page's frames
([format, sizes](data-sources.md#radar-archive)). `--products forecast` adds the
nowcasts (~50 GB a year, meant for a local disk with `--out-dir`), `mvd mirror-radar
--out-dir DIR` copies the archive to a local disk (`--satellite` also the satellite
archive), and `mvd radar-live --dir DIR` keeps the frames of the last 24 hours (radar,
echo tops, motion fields, storm cells, Meteosat images) and the newest nowcast for the
page ([contract](data-sources.md#radar-live-data-contract)). `mvd archive-satellite
--github-release` keeps ČHMÚ's Meteosat images (~8 days online) in the releases
`satellite-YYYY-MM` ([format](data-sources.md#satellite-images)).

```bash
uv run mvd radar-live --dir /tmp/radar-live --hours 3 --cache /tmp/radar-cache  # live frames, local
uv run mvd archive-radar --day 2026-10-14 --out-dir data/radar  # one day, local
uv run mvd archive-satellite --regions ce --out-dir data/radar  # satellite days, local
```

## Automated workflows

| Workflow | When (UTC) | What |
|---|---|---|
| ALADIN archive | every 3 hours | `mvd archive-aladin --github-release` |
| Radar | a loop of 340 min that pushes every 5 minutes and starts the next loop itself (hourly schedule as safety net); archive every 6 hours | `scripts/radar_live_loop.sh`: `mvd radar-live` → branch `radar-live` (force-pushed) ([live loop](data-sources.md#live-loop)); `mvd archive-radar --github-release`, `mvd archive-satellite --github-release` |
| Backfill | 02:41 | `mvd backfill`, the shared 8,300 Open-Meteo calls a day: one sweep from today into the past, 14-day window by window, each with its D+N (all stations, rain gauges) and the single runs' API history of its days |
| Single runs | 04:20, 10:20, 16:20, 22:20 | `mvd fetch-runs --github-release`: every run of the last 90 days not stored yet from Open-Meteo's open-data bucket (no API calls), then the API for the bucket's gaps (100 calls each, ≤ 400 a day) ([budget](data-sources.md#open-meteo-budget)) |
| Daily | 05:17 | `mvd daily --github-release`, commits the badge, then `mvd leads --github-release --publish` (allowed to fail) |
| CHMI archive | 01:41 and 13:41 | `mvd chmi-archive --part days --part recent --github-release` (the last days of `now/`, changed months of `recent/`), then `mvd station-pages --github-release --publish` and `mvd observed-map --github-release --publish` (`observed-data.zip`; allowed to fail) |
| CHMI backfill | 02:07, up to 5 h | `mvd chmi-archive --part history --part months --github-release`, resumable, same concurrency group |
| Pages | after Daily, CHMI archive and changes in `web/` | builds `web/`, adds the radar frames of the last 7 days from the releases (satellite images 7 days, echo tops 14, a 900 MB guard) and the station index, and publishes it |

## Web pages

`web/` is built with Vite, MapLibre GL and Observable Plot; boundaries are drawn on a
plain background (no third-party map tiles). The pages read `site/data` (scores,
stations, per-station series, outlook), which is published in the release
`data-latest` and not committed. Every page is in Czech or English (Czech for Czech and
Slovak browsers; a button switches and the choice is remembered) and keeps its view in
the URL.

| Page | What it shows | URL state |
|---|---|---|
| `index.html` (home; `forecast.html` redirects here) | combined forecast map: day tabs, parts of the day, "play the day" / "play the week" (each round switches the map colour temperature → rain → wind → cloud), values at the okresy, a "Forecast" selector above the map that switches the whole map (values, colours, headline, legend, play) to one model's raw parts of day (`forecast/models-parts/<model>.json`, models by their mean rank over Czechia, rain in mm, grey "–" beyond the model's horizon, a note with the way back), and a panel per okres with its own "Forecast" selector (our combination or one model's raw values by the outlook's part-of-day rules, from `forecast/models/<okres>.json`; it opens on the map's choice and changes only the panel); neither choice is remembered (no storage, not in the URL); sunrise and sunset (earliest–latest over the okresy) in the headline box and the okres's own in its panel; symbols get a moon when most of the part of day is after sunset or before sunrise. Only the coming days (the page for what was measured is gone; an old link to a past day opens the first day) | `#2026-10-13/afternoon/temperature/tpw/CZ0201` |
| `index.html` | score map: okresy and stations coloured by the best model, legend with win counts, okres finder, a panel explaining why a model wins, per-station error charts | `#temperature_2m/1/90d/CZ0201` |
| `forecast-detail.html` | hourly combined forecast per okres town (72 towns: Praha, Brno, …; Praha-východ/západ, Brno-venkov and Plzeň-jih/sever open their seat city, `seats.js`) next to the best single model, with the weights and a "Forecast" selector (our combination, or one model's raw forecast); all from static files (`forecast/models/<okres>.json`, no request to Open-Meteo), with the issue time; sunrise and sunset per day and the nights shaded in the charts, from `outlook.json` | okres |
| `data.html` | open data: JSON per okres under `api/v1/` ([docs](open-data.md)) | – |
| `radar.html` | ČHMÚ radar: the last 1–24 hours (live frames from the branch `radar-live`) with the nowcast for the next hour after them, marked as forecast; archived days (last 60) with a date picker; MERGE 1-hour precipitation as a second layer; colour scales in dBZ and mm, Prague time ([frames](data-sources.md#radar-page-frames)) | `#live/3/radar+rain/202610151035` |

GitHub Pages: Settings → Pages → Source: GitHub Actions. A fork without Pages enabled
only builds.
