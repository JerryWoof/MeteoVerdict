# Data sources

This page records what we verified about the external data, where it lives and under
which terms. Everything here was checked on **2026-10-11**, by downloading the real
files and calling the real API. Claims we could not verify are marked **unverified**;
do not build on them without checking. Both sources are reachable without
authentication from the development machine and from GitHub Actions.

## ČHMÚ climatological open data (observations)

Base URL: `https://opendata.chmi.cz/meteorology/climate/`

Primary reference: the official description
[`Klimatologicka_data_popis.pdf`](https://opendata.chmi.cz/meteorology/climate/Klimatologicka_data_popis.pdf)
(Czech, last modified 2024-07-08). The sections below summarise it and add what we saw in
real files.

### Directory layout

| Path | Contents | Update cadence (per the PDF) |
|---|---|---|
| `now/data/` | 10-minute (`10m-…`) and hourly (`1h-…`) files per station and day | regenerated hourly and overwritten; on 2026-10-12 it held the last three days (09–11 Oct for 10-minute files) |
| `now/metadata/` | `meta1`…`meta4`, named `metaN-YYYYMMDD.json` | daily; deleted after 10 days |
| `recent/data/{10min,1hour,daily,monthly,pentadic,phenomena}/` | current year, month folders `01/`…`12/` | 10 min / 1 h: twice a day, and the previous two months are regenerated on the 3rd of each month; daily: after each day; monthly / pentadic: start of the next month, re-uploaded after two months |
| `historical/data/{10min,1hour,daily,monthly,pentadic,yearly,phenomena}/` | closed years; 10 min and 1 h data from 2018 | once a year, by the end of February |
| `historical/metadata/` | station and element metadata | once a year |
| `historical_csv/data/…` | the same as CSV, one file per element | once a year |

Implications for us:

- **Backfill (2.6)** reads `historical/` for closed years and `recent/` for the months
  of the last year. `historical/` has 10-minute and hourly data from 2018, which covers
  our 2024+ window.
- **The current month is not in `recent/` yet** (on 2026-10-12, `recent/data/10min/10/`
  still held October 2025, `09/` held September 2026). Until it is published, the only
  source is `now/`, which keeps about three days. **Daily runs (3.2) must therefore
  fetch yesterday from `now/` every day** and re-fetch the month from `recent/` once it
  appears (checked data replaces the unchecked values; `mvd fetch-obs` merges by
  station, time and variable).

### File names

`{WSI}` is the WIGOS Station Identifier (e.g. `0-20000-0-11520`, Praha-Libuš) and
`{PRVEK}` is the element code.

| Data | Pattern |
|---|---|
| `now/` 10 min / 1 h (JSON) | `10m-{WSI}-{YYYYMMDD}.json`, `1h-{WSI}-{YYYYMMDD}.json` (one file per station and day) |
| `historical/` 10 min / 1 h (JSON) | `{YYYY}/10m-{WSI}-{YYYYMM}.json` (one file per station and **month**; the PDF says `YYYYMMDD`, but the real files are monthly, e.g. `historical/data/10min/2025/10m-0-20000-0-11520-202503.json`, 5.8 MB) |
| `recent/` 10 min / 1 h | `10m-{WSI}-{YYYYMM}.json`, `1h-{WSI}-{YYYYMM}.json` (one file per station and **month**, in month folders `01/`…`12/`; a folder holds the latest published year for that month, e.g. `10/` still held `202510` on 2026-10-11) |
| daily | `recent/`: `dly-{WSI}-{YYYYMM}.json`; `historical/`: `dly-{WSI}.json` |
| `historical_csv/` 10 min / 1 h | `10m-{WSI}-{PRVEK}.csv`, `1h-{WSI}-{PRVEK}.csv` |

Example (fetched successfully):
`now/data/1h-0-20000-0-11520-20261011.json`.

### JSON envelope

All JSON files we read (metadata and data) share one envelope:

```json
{
  "zaznamID": "<uuid>",
  "datovyZdrojID": "meteorologie",
  "datovyTokID": "Open.Data.1H",
  "datumVytvoreni": "2026-10-11T23:11:29.159Z",
  "verzeDat": "1.0",
  "data": {
    "type": "DataCollection",
    "data": {
      "header": "STATION,ELEMENT,DT,VAL,FLAG,QUALITY",
      "values": [["0-20000-0-11520", "C-C1Av", "2026-10-11T00:00:00Z", 9074.0, "", 5.0]]
    }
  }
}
```

- `header` is a **comma-separated string**, and `values` is a list of row arrays in
  that column order.
- `datovyTokID` names the stream: `Open.Data.Metadata` for metadata, `Open.Data.1H` for
  hourly data.
- Timestamps are ISO 8601 with a `Z` suffix. The PDF states: "Časy jsou v UTC" (times
  are in UTC).

### Data files (10 min and 1 h)

Columns: `STATION` (WSI), `ELEMENT`, `DT` (UTC timestamp), `VAL` (number), `FLAG`
(string, often empty), `QUALITY` (number, codes from `meta4`: 0 Good, 1 Suspect,
2 Poor, 3 Estimated, 4 Missing, 5 Unknown). `now/` data is mostly unchecked (`5.0`,
some values already `0.0` or `3.0`), `recent/` data is checked (`0.0` for good values).
**Missing values come as an empty string `""`** with `QUALITY` 4, so `VAL` is not always
a number. The rows are long-format: one row per
station × element × time.

Which elements go where (from `meta2`'s `OBS_TYPE` column and real files):

- **Hourly (`1H`) elements** include `SRA1H` (precipitation, 1 h, mm), `P`, `E`, `Td`,
  `N`, `ww`, `VV`, `SSV1H` and the ceilometer `C-…` elements.
- **10-minute (`10M`) elements**, per `meta2` for Praha-Libuš: `T` (Teplota, °C,
  sensor at 2 m), `TMA`/`TMI` (max/min), `F` (Rychlost větru, m/s, 10 m), `Fprum`
  (Rychlost prům, m/s, 10 m), `Fmax`, `D` (direction), `SRA10M` (precipitation, mm),
  plus soil temperatures.
- Element names, units and sensor heights come from `meta2` (`NAME`, `UN_DESCRIPTION`,
  `HEIGHT`). The PDF lists codes without definitions.

### Hourly observations (`mvd fetch-obs`)

2 m temperature and 10 m wind exist only in the 10-minute files, so `mvd fetch-obs`
builds hourly values from them:

| Variable | From | Matches the forecast because |
|---|---|---|
| `temperature_2m` | `T` at HH:00 | Open-Meteo's `temperature_2m` is the value at the hour |
| `wind_speed_10m` | `F` at HH:00 (m/s) | model wind at the hour; `F` is ČHMÚ's main wind speed element |
| `precipitation` | sum of the six `SRA10M` values stamped HH-1:10 … HH:00, only if all six exist | Open-Meteo's hourly precipitation is the sum over the preceding hour |
| `wind_gusts_10m` | largest of the six `Fmax` values (maximum gust in each 10 minutes, m/s) stamped HH-1:10 … HH:00, only if all six exist | Open-Meteo's hourly `wind_gusts_10m` is the maximum of the preceding hour ("Preceding hour max" in its docs, checked 2026-10-15) |

Checks on real data (Praha-Libuš, September 2026): the hourly precipitation equals
ČHMÚ's own `SRA1H` for all 720 hours (22.6 mm both), which also confirms that
timestamps mark the end of each interval. `F` is on average 0.1 m/s above `Fprum`
(equal in 32 % of slots); ČHMÚ does not document how the two are averaged
(**unverified**; possibly scalar vs. vector mean), and the difference is small for
ranking models.

Gusts are stored since 2026-10-15 (earlier months have none) and are used only by the
farmers' event scores (`mvd farm`), not by the D+N scores. `Fmax` is in the 10-minute
files of the run stations (checked: Praha-Vinohrady, 14 Oct 2026, 144 values a day,
e.g. 3.4 m/s with `F` 1.6 m/s); a first fetch of 2026-10-13 to 15 for the 100 run
stations gave 5,556 hourly gusts next to 5,666 temperatures.

Values with `QUALITY` 1 (suspect), 2 (poor) or 4 (missing) are dropped; 0, 3 and 5 are
kept with their code, so scoring can exclude estimated values. Every value also records
its `source` (`recent`, `historical`, `now`).

Only stations with a 10-minute `T`, `F` or `SRA10M` in today's `meta2` are fetched
(`Fmax` does not add stations)
(about 475; the other ~280 active stations are manual rain gauges with daily data
only, see below), plus inactive stations (not in today's `meta2`). One day for all
stations from `now/` took about a minute (468 stations returned data on 2026-10-10).
A monthly `recent/` or `historical/` file is about 5 MB per station, so a month of
history for all stations is about 2.5 GB to download; `historical_csv/` (one file per
element) may be cheaper for the backfill (2.6).

### Manual rain gauges (`mvd fetch-gauges`)

About 280 active stations have no 10-minute data: they are manual rain gauges that
report one daily precipitation total (`SRA`, mm), stamped by ČHMÚ at 06:00 UTC. When
an observer actually reads a gauge is not in the PDF (**unverified**: presumably the
morning climatological term, around 06 UTC). They roughly double the station count
for precipitation.

| Path | Content |
|---|---|
| `recent/data/daily/MM/dly-{WSI}-{YYYYMM}.json` | daily elements (`SRA`, `SNO`, …) of one month, last 12 months; header `STATION,ELEMENT,VTYPE,DT,VAL,FLAG,QUALITY` |
| `historical_csv/data/daily/precipitation/dly-{WSI}-SRA.csv` | all `SRA` values of one station up to the last closed year (about 2.5 MB); header `STATION,ELEMENT,TIMEFUNC,DT,VALUE,FLAG,QUALITY` with a trailing comma on every line |

- **Window:** `DT` is the **start** of the 24-hour window: the value stamped
  `2026-09-04T06:00Z` fell from 4 Sept 06:00 to 5 Sept 06:00 UTC. Checked against the
  hourly totals of Praha-Libuš, which has both: all 30 days of September 2026
  matched. `mvd fetch-gauges` stores it as `precipitation_24h` stamped with the
  window's **end**, like every other value.
- **Delay:** manual readings are published late. In October 2026 July and August were
  complete, while most September rows were still `""` with `QUALITY` 4 (missing).
- **Scoring:** the window is 06–06 UTC, not the calendar UTC day used for automatic
  stations, so the forecasts are summed over the same 24 hours (`precipitation_24h`,
  see "Daily scores").
- **Storage:** `data/gauges/YYYY-MM.parquet` (same columns as `data/obs`), a separate
  kind in the raw data store, so gauge months never overwrite hourly ones.
- **Cost of history:** the historical CSV is about 2.5 MB per station, about 770 MB
  for all gauges, and it holds every closed year. So the history is imported once with
  `mvd fetch-gauges --start 2024-01-01 --end …` (then `mvd store upload`); the
  scheduled runs read only the small monthly files in `recent/`.

A live run for August 2026 (`--start 2026-08-01 --end 2026-08-31`) returned 8,370
daily values from 273 of 307 stations selected as gauges (manual or closed).

### Metadata files

| File | Header (as seen in real files) | Notes |
|---|---|---|
| `meta1` (`now/`) | `WSI,GH_ID,FULL_NAME,GEOGR1,GEOGR2,ELEVATION,BEGIN_DATE` | stations operating today (760 rows on 2026-10-11, of which 3 WIGOS ids appear twice: two re-equipped stations with a new `GH_ID` and `BEGIN_DATE` in 2026, one with two slightly different positions; `mvd stations` keeps the row with the latest `BEGIN_DATE`). **`GEOGR1` is longitude, `GEOGR2` is latitude** (e.g. Cheb 12.39, 50.07). Elevation in m. The PDF omits `BEGIN_DATE`. It includes at least one non-Czech station (Reykjavik), so filter to Czechia. |
| `meta1` (`historical/metadata/meta1.json`) | `WSI,GH_ID,BEGIN_DATE,END_DATE,FULL_NAME,GEOGR1,GEOGR2,ELEVATION` | **one row per validity period**: a station's position and elevation can change between periods (Cheb has six). An open period ends at `3999-12-31T23:59:00Z`. Also lists closed stations. 5,539 rows (created 2026-02-12, so it lags behind closures during the current year). Note the different column order. |
| `meta2` | `OBS_TYPE,WSI,EG_EL_ABBREVIATION,NAME,UN_DESCRIPTION,HEIGHT,SCHEDULE` | elements measured per station, with sensor height in m. The PDF omits `OBS_TYPE` and `SCHEDULE`. |
| `meta3` | `EL_ABBREVIATION,FLAG,DESCRIPTION` | meaning of the `FLAG` column per element (32 rows) |
| `meta4` | `FLAG2,DESCRIPTION` | quality codes 0–5 (see above) |

Neither `meta1` has an "active" flag. `mvd stations` (roadmap 1.2) treats a station
as active when it is in the current `now/metadata/meta1`, and takes its position from
there. Stations only in the historical file are kept as inactive at the position of
their last period, if that period ended on or after 2024-01-01. The historical file
is not reliable as the only source of "active": it is regenerated once a year.

Foreign stations also show up in the historical file, and not always with sensible
coordinates: Marambio (Antarctica) is listed at `GEOGR1` 56.62, `GEOGR2` 64.23, so
latitude and longitude look swapped and unsigned. A Czech bounding box drops them
first, then the kraj polygons drop anything outside Czechia (see below).

On 2026-10-11 `mvd stations` produced 782 stations (756 active, 26 closed since
2024-01-01) in all 14 kraje; none was outside Czechia or needed the border tolerance.

### Kinds of station

All stations in ČHMÚ's open data are ČHMÚ's own network: there are no amateur or
third-party stations. The metadata has **no "station type" or "operator" field**:
`meta1` is `WSI, GH_ID, FULL_NAME, GEOGR1, GEOGR2, ELEVATION, BEGIN_DATE`, `meta2` lists
elements with `OBS_TYPE` (`10M`, `1H`, `DLY`, `PHENO`) and `SCHEDULE`, `meta3`/`meta4` are
flag and quality codes. `stations.network` (used for the station map, `index.json`'s
`network`) derives the kind from the WIGOS id and from which elements the station
still measures, every 10 minutes or once a day:

| `network` | Rule | Active stations on 2026-10-15 |
|---|---|---|
| `main` | WIGOS `0-20000-0-<WMO number>`: the main (synoptic) stations, the only ones with a WMO number: ČHMÚ's professional stations, which report to the WMO (SYNOP) | 40 |
| `climate` | 10-minute air temperature `T` (not a snow station); all also have humidity, most precipitation `SRA10M` and wind `F` | 218 |
| `snow` | 10-minute `T` and automatic snow depth `SCEa`, but no 10-minute precipitation or wind: mountain snow stations (GH_ID with `4` as second character, e.g. `H4CEHO01` Černá hora) | 38 |
| `precipitation_auto` | 10-minute precipitation `SRA10M`, no 10-minute `T` | 179 |
| `precipitation` | no 10-minute elements, daily precipitation `SRA` (06 UTC, i.e. 07 CET; snow `SCE`/`SNO`): read by hand by ČHMÚ's (volunteer) observers | 279 |
| `climate_manual` | no 10-minute elements, daily `T` (06/13/20 UTC terms) | 0 (4 closed since 2024) |
| `other` | nothing of the above in `meta2` (Hradištko, Třinec-Kosmos) | 2 |

"Still measures" means an element of today's `meta2` or a historical `meta2` period
that has not ended (`END_DATE` 3999); a closed station is judged by everything it ever
measured. The current `meta2` lists only `10M` and `1H` elements, so manual stations
appear only in the historical file. WIGOS ids also hint at the kind
(`0-203-0-<5 digits>`, the old national climate numbers: 154 of the 218 automatic climate
stations; `0-203-0-<11 digits>`: mostly precipitation stations), but not reliably
enough to use. That precipitation stations are read by volunteers is ČHMÚ's general
description of its network, not a field of the metadata.

Small real excerpts are in `tests/fixtures/chmi/` (see the README there).

### Access notes

- Directory listings work with plain HTTP (they are large HTML pages). The fetcher
  should still build URLs from the patterns above rather than scrape listings, and
  retry on errors.
- No authentication is needed.

### Licence and attribution

- The PDF and the server do not state a licence. The PDF only says these data replace
  data published under Act No. 123/1998 Coll. (on the right to environmental
  information).
- The ČHMÚ page ["Mohu získat vaše data pro svůj projekt?"](https://www.chmi.cz/-/mohu-z%C3%ADskat-va%C5%A1e-data-pro-sv%C5%AFj-projekt-)
  sends open-data users to opendata.chmi.cz and carries a **CC BY 4.0** badge in its
  footer. This suggests CC BY 4.0, but it is not an explicit statement for the dataset.
- **Confirmed: CC BY 4.0.** The National Open Data Catalogue (data.gov.cz) records
  for the ČHMÚ station data and the ALADIN forecasts list CC BY 4.0, author ČHMÚ
  (checked 2026-10-12, see [licensing.md](licensing.md)). Credit "Czech
  Hydrometeorological Institute (ČHMÚ), opendata.chmi.cz, CC BY 4.0".

## Metrics

`meteoverdict.metrics` (roadmap 2.2). Error = forecast − observed.

| Metric | Formula | Used for |
|---|---|---|
| MAE | Σ\|error\| / n | temperature, wind, precipitation amounts |
| bias | Σ error / n (positive = forecast too high) | same |
| RMSE | √(Σ error² / n) | same |
| POD | a / (a + c) | daily precipitation ≥ 0.1 mm, ≥ 5 mm and ≥ 20 mm (heavy precipitation, the ETCCDI index R20mm) |
| FAR | b / (a + b) | same |
| ETS | (a − a_r) / (a + b + c − a_r), a_r = (a + b)(a + c) / n | same |
| POD, FAR, ETS | as above | daily maximum temperature ≥ 30 °C (a "tropický den", tropical day) |

a = hits, b = false alarms, c = misses, d = correct negatives; an event is "at least the
threshold". Scores are stored as additive sums (`n`, `sum_err`, `sum_abs_err`,
`sum_sq_err`, `a_*`, `b_*`, `c_*`, `d_*`), so they can be summed over days, stations and
regions before the metrics are computed; a metric whose denominator is zero is null.
Stored compactly (one row is one station-day): `n` as uint16, the sums as float32
(about 7 significant digits), the counts as uint8; every aggregation sums them in
64 bits (`metrics.total`).
Checked against Finley's (1884) tornado forecasts (a = 28, b = 72, c = 23, d = 2680:
POD 0.549, FAR 0.72, ETS 0.216).

## Daily scores (`mvd score`)

`mvd score --start D --end D` reads `data/obs` and `data/fc` (the months of the range
plus the next day, for the last day's precipitation) and writes
`data/scores/YYYY-MM.parquet`: one row per `date`, `station_id`, `model`, `lead_day`
and `variable` with `period_h` and the additive sums (`n`, `sum_err`, `sum_abs_err`,
`sum_sq_err`; for `precipitation_daily` and `precipitation_24h` also `a_*`, `b_*`,
`c_*`, `d_*` for 0.1, 1, 5, 10 and 20 mm, 1 and 10 since October 2026, null in rows
written before; for `temperature_max` for 30 °C).

| `variable` | `period_h` | Day of a pair |
|---|---|---|
| `temperature_2m`, `wind_speed_10m` | 0 | UTC date of the hour; only 00, 06, 12 and 18 UTC (ranked) |
| `temperature_2m_hourly`, `wind_speed_10m_hourly` | 0 | UTC date of the hour; every native hour of the model (not ranked) |
| `precipitation` | 1, 3 or 6 (the model's native period) | UTC date the period ends in (01:00 … 24:00) |
| `precipitation_daily` | 24 | the UTC day |
| `precipitation_24h` | 24 | the day ČHMÚ's climatological day starts (06:00 to 06:00 UTC) |
| `temperature_max` | 24 | the UTC day (highest of the 24 hourly values, 00:00 … 23:00) |
| `temperature_2m_00utc`, `_06utc`, `_12utc`, `_18utc` | 0 | UTC date of that hour |
| `wind_speed_10m_00utc` … `_18utc` (since October 2026) | 0 | UTC date of that hour; not aggregated on their own |

Hourly precipitation MAEs of different periods are not comparable, so models are
ranked on `precipitation_daily` and `precipitation_24h`.

`source` (since 2026-10-16) says where the forecasts behind a row came from:
`previous_runs` (the backfill's D+N windows; also rows of older files, which lack the
column) or `single_runs` (D+N rebuilt from the single runs for the days the backfill
has not reached, see [Fresh D+N from the single runs](#fresh-dn-from-the-single-runs)).
A row is `single_runs` if any hour behind it was rebuilt (for `precipitation_daily` the
hours ending 01:00 … 24:00, for `precipitation_24h` 07:00 … 06:00); the blend's rows
if any member's were.

`precipitation_24h` is the window of the manual rain gauges (see "Manual rain gauges"),
so it is the one precipitation score that covers all ~750 stations. A gauge's own
value is used where there is one; at automatic stations the 24 hourly sums ending
07:00 … 06:00 (all must exist). The forecast is the sum of the same 24 hourly values;
like the UTC-day total, each hour comes from its own lead day (the hours after midnight
from the run one day later). Every native period of 3 or 6 hours fits into the window,
so this works for every model. The maps rank precipitation by this score by default;
`precipitation_daily` is also in the map data.

The temperature at the four **synoptic hours** 00, 06, 12 and 18 UTC (roadmap 5.1b)
is also scored on its own (`temperature_2m_00utc` …). Every model, the 6-hourly ones
included, has native output at these hours, so all can be compared by time of day:
06 UTC (07:00 CET, 08:00 CEST) is around the end of the night, when valley inversions
are strongest; 12 UTC is early afternoon. These variables are aggregated (MAE, bias,
RMSE per region, window and season) but not ranked with the bootstrap, which keeps
the daily run short; they add about 40 % to the score rows. Since October 2026 the wind
is scored at each synoptic hour too (`wind_speed_10m_00utc` …), only so that each
pair's error is known for the bias-corrected MAE (`aggregate.bias_corrected`,
[methodology](methodology.md#bias-corrected-mae)); these rows are not aggregated or
published on their own and add about 30 % to a month's score file (September 2026:
35 MB → 47 MB).

**Same hours for every model.** The ranked `temperature_2m` and `wind_speed_10m`
use only 00, 06, 12 and 18 UTC, where every model (also AIFS, IFS 0.25° and the blend,
which are 6- or 3-hourly) has native output. Scoring each model at all its native hours
compared hourly models over 24 hours with 6-hourly ones over 4, and errors depend on
the time of day: on the first real data (21–29 Sept 2026, D+1, about 470 stations)
a model's MAE over its native hours and over the four synoptic hours differed by
0.02–0.05 °C, as much as the gap between several models. The all-hours scores are kept
as `temperature_2m_hourly` and `wind_speed_10m_hourly`, for information only.

`temperature_max` (roadmap 5.2b) compares the highest hourly temperature of each UTC
day, forecast and observed, and counts heat days (at least 30 °C). It is scored only
for models with hourly output at that lead day (not AIFS, IFS 0.25°, nor the
3-hourly lead days of ICON-EU, IFS HRES, GFS and UKMO, nor the blend): the highest
interpolated hour would cut off the afternoon peak. Both sides use values at the full
hour, so the observed maximum is a little below ČHMÚ's own daily maximum (`TMA`).

A day can only be scored once its observations are
published: on 2026-10-12 the latest complete checked month was September 2026 (see
"File names" above). A run over 20 stations and 14 days took 0.2 s.

## Aggregates (`mvd aggregate`)

`mvd aggregate` sums the daily scores per **level** (`station`, `okres`, `kraj`,
`elevation` class, `network`: `main` WMO stations and `other` stations, `cz`) and
**window** ending at the last scored day (`90d`, `season`
= meteorological season so far, `all`), then derives the metrics. The **seasonal
windows** `djf`, `mam`, `jja` and `son` (roadmap 5.1) take every day of that season
in the whole history, e.g. all summers, so models can be compared by season (their
`from` is the first scored day of all).

- **Cost:** with the seasonal windows, aggregating and ranking one variable and lead
  day for 750 stations, 13 models and a year of days takes about 35 s on a laptop
  (bootstrap included; 19 s with only the first three windows).

- **Fair comparison:** within a window, variable, lead day and region only the
  station-days that every model present in that region has scores for are used, so all
  models of a region are compared on the same stations and days. Models with a shorter
  archive or gaps get the same days as the rest. Where a model never reaches some
  stations (ICON-D2 at six stations in the Beskydy), those stations drop out of that
  region's comparison (Moravskoslezský kraj, Czechia, their okres and elevation class)
  for every model, and are compared among the other models at the station level.
  (Consequences: the `all` window for D+1 and D+2 starts when the newest model's archive
  starts, ALADIN in June 2026; while the backfill has fetched a model for only part of
  the stations, regions are compared on that part.) A window's `from` is its start or
  the first scored day, whichever is later.
- A region needs at least 3 stations (`enough_stations`); stations are always
  rankable on their own.
- **Borrowed stations (roadmap 6.1):** an okres with fewer than 3 stations of its own
  for a variable adds the nearest stations of other okresy, closest to its border first,
  up to 3 and at most 30 km beyond its border (`meteoverdict.neighbours`). A station
  only counts if it survives the fair comparison at D+1; one that some of the okres's
  models never reach is replaced by the next nearest. `borrowed` (in the okres rows)
  counts them; a borrowed station still counts in its own okres. On the 2026-09 scores
  (90 days, D+1) this borrows for 25 okresy for temperature, 39 for wind and 5 for the
  06–06 precipitation, and all 77 okresy are ranked for all three (before: 52, 38 and
  72). Only the okres level borrows.
- Output: `data/aggregates.parquet` (all columns, including the sums) and
  `site/data/meta.json` plus `site/data/<window>/<level>/<variable>.json` as
  `{"columns": […], "rows": […]}` with floats rounded to 3 decimals. `meta.json` has
  `as_of` (the last scored day, with the single runs usually yesterday) and `sources`:
  the first and last day scored from each source, e.g.
  `{"previous_runs": {"from": "2026-07-08", "to": "2026-10-04"}, "single_runs":
  {"from": "2026-10-04", "to": "2026-10-15"}}`.
- **Models with too short a record.** Per window, variable and lead day only the models
  with scores on at least 80 % of the window's scored days are compared and ranked
  (`aggregate.coverage`, `MIN_COVERAGE`); the fair station-days are those every one of
  them has. The others (a model added recently, whose backfill has reached only its
  newest weeks) get rows of their own with `short_record` true, over their own
  station-days among the fair ones (smaller `days` and `n`), no rank and no weight.
  Every row has `coverage` (the model's share of the window's scored days). `meta.json`
  lists them per window (`short_record`: `{window: {model: {coverage, days,
  variables}}}`, with `min_coverage`). Without the rule, on 16 October 2026 the eight models added on 15
  October (scores from 21 September) cut the 90-day window of every model from 38–40
  days (temperature, wind) and 37–52 (precipitation) to 9–10. With it, those eight are
  listed separately; for the 06–06 precipitation (gauges), six models whose gauge
  history so far starts on 7 September (38 of 52 days, 72–74 %) are also listed
  separately until the gauge backfill reaches further back.
- **Added in October 2026** (older files lack them; readers must not require them):
  the level `network` (regions `main`, the main WMO stations, WIGOS `0-20000-0-…`, and
  `other`; about 180 kB per window), the columns `pod_1`, `far_1`, `ets_1`, `pod_10`,
  `far_10`, `ets_10` for precipitation (not in the station-level files, to keep them
  small; `aggregates.parquet` has them), and `mae_bc` for temperature and wind (the MAE
  once the model's own bias at the station and hour, from the 30 days before the
  forecast, is removed; every level but `station`;
  [methodology](methodology.md#bias-corrected-mae)). `meta.json` describes them under
  `networks` and `bias_corrected`.
- For the web map also `site/data/stations.json` (position, okres, kraj) and
  `site/data/series/<station>.json`: each model's daily MAE at that station over the
  last 90 days, for the ranked variables at D+1 and D+2 (about 65 kB per station, so
  only in the release `data-latest`).

## Combination weights (roadmap 6.2)

`mvd aggregate` also writes, for the web map's own forecast, how to combine the models
in each okres (`meteoverdict.combine`), from the okres scores of the last 90 days
(window `90d`, same fair station-days, borrowed stations included). Only the models
compared there get a weight: those with scores on at least 80 % of the window's scored
days (`aggregate.MIN_COVERAGE`). A model with a shorter record (`short_record`, e.g.
added recently, its backfill so far only reaching its newest weeks) gets no weight and
does not cut the others' training days; it is weighted from the day it has them.
`mvd aggregate` prints the models left out, and `mvd check` warns about them. The
temperature and wind regression (`mos`) uses the same models (and its own 80 % rule
on the training rows).

| Open-Meteo variable | Weights from | Bias correction |
|---|---|---|
| `temperature_2m` | `temperature_2m` (synoptic hours, where every model is native) | yes |
| `wind_speed_10m` | `wind_speed_10m` | yes |
| `precipitation` | `precipitation_daily` (daily totals) | no |

- Weight of a model ∝ `1 / (RMSE² − bias²)` (the error left after removing its mean
  error) where it is bias-corrected, `1 / RMSE²` for precipitation; error variances
  below 0.01 count as 0.01.
- Shrinkage towards the plain mean, by the number of scored days: weight
  `s · w + (1 − s) / models` with `s = days / (days + 30)`, correction `c · bias` with
  `c = days / (days + 5)` (the bias is stable enough to be removed almost in full;
  shrinking it like the weights cost 7–10 % of wind MAE out of sample).
- Combined forecast: `Σ weight · (forecast − correction)` over the models available
  for the hour, weights rescaled to sum to 1; a model ending before the others gets ¾,
  ½ and ¼ of its weight in its last three hours.
- Files: `site/data/forecast/okresy.json` (`code`, `name`, `lat`, `lon` of a point
  inside each okres: the centroid of its largest part, or the nearest inside point;
  `weights` false where the okres has no scores yet) and
  `site/data/forecast/<okres>.json` (`variable`, `lead_day`, `model`, `weight`,
  `correction`, `mae`, `rank`, `days`, then `mos_weight`, `mos_models`,
  `correction_00`, `correction_06`, `correction_12`, `correction_18`; about 8 kB each).
  Only in the release `data-latest`, like the okres scores.
- **Temperature and wind, regression blend** (`meteoverdict.mos`, written by
  `mvd daily`, which has the last 100 days of `obs/` and `fc/` at hand): `mos_weight`
  (sums to 1 over the `mos_models` models, may be negative) and the corrections at
  00/06/12/18 UTC at the okres's point (elevation term at half strength), interpolated
  linearly in UTC hour in between; for wind an okres where the regression did worse
  than the method before on the last 7 days of its window has none.
  An hour where all `mos_models` models have a value (none fading out) is
  `Σ mos_weight · (forecast − correction)`; otherwise the inverse-error `weight` with
  the same hourly corrections, rescaled over the models present. `correction` holds
  the mean of the four, for readers that know only `weight` and `correction`. With
  fewer than 14 days of pairs, or `mvd aggregate` alone, `mos_weight` is null and the
  slot corrections equal `correction`. The method: [methodology.md](methodology.md#temperature-and-wind-regression-blend).
- `data/forecast-weights.parquet` (also in `data-latest`): the same table for all
  okresy, read by `mvd outlook` (it falls back to `combine.weights` of
  `aggregates.parquet` where the file is missing).
- `src/meteoverdict/data/okres-elevations.csv`: the elevation of each okres's point
  (Open-Meteo Elevation API, rebuilt by `scripts/build_okres_elevations.py`).
- Whether the combination beats the best single model: see the out-of-sample test below.

### Out-of-sample test (`mvd blend-test`, roadmap 6.4)

`meteoverdict.blendtest` replays the combination on the stored D+N forecasts
(`fc-YYYY-MM.parquet`) with only earlier scores; method and result in
[methodology.md](methodology.md#does-it-beat-the-best-single-model-roadmap-64).

- **Training:** for day *d* at lead day *N*, `aggregate.aggregate` (okres level, window
  `90d`, or `--window 30d` etc.) over the scores up to *d − N*, then `combine.weights`
  and the okres's lowest-MAE model; tested only with ≥ 14 scored training days
  (`--min-training-days`).
- **Scoring:** the combination per okres and station (pools as in the ranking,
  `combine.combine_values`, ≥ 2 models per hour) as a 6-hourly model through
  `scoring.daily_scores`; `temperature_2m`, `wind_speed_10m`, `precipitation_daily`;
  fair station-days per okres with the combination as one more model.
- **Run:** daily in `daily.yml` after the lead hours (`--github-release --publish`, allowed
  to fail), testing the last 180 scored days (`--days`); about 35 s and 3.6 GB for 38
  scored days locally.
- **Output:** `site/data/blend-test.json` (release `data-latest`, about 220 kB):
  `generated`, `method`, `training_window`, `shrink_days`, `bias_shrink_days`,
  `min_training_days`, `min_okres_days`, `first_scored`, `from`, `to`, `test_days`,
  `warm_up_days` (scored days before the first test day), `units`, `models`, and two `{"columns", "rows"}`
  tables: `groups` (one row per `level` `cz`/`okres`, region, variable and lead day:
  `days`, `stations`, `best_oos` (most often chosen model), `best_oos_models` (how many
  different ones), `best_hindsight`, `mae_combined`, `mae_best_oos`,
  `mae_best_hindsight`, `mae_blend`, and `diff_*`, `low_*`, `high_*` of `combined`,
  `best_hindsight` and `blend` minus `best_oos` with the 95 % interval; okresy with at
  least 10 test days) and `single_models` (Czechia: `variable`, `lead_day`, `model`,
  `mae`, `diff`, `low`, `high`, same differences).

## Outlook (`mvd outlook`, roadmap 6.6)

The TV-style forecast for every okres (`meteoverdict.outlook`):

- **Request:** one Open-Meteo **Forecast API** request (`api.open-meteo.com/v1/forecast`)
  for the forecast points of all 77 okresy, all models with weights,
  `hourly=temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration`,
  `forecast_days=6`, UTC; 77 × 5 × models / 10 weighted calls: ≈ 420 with 11 models,
  ≈ 732 with all 19 (refused above 800). A request is at most 500 calls (Open-Meteo
  allows 600 a minute), so with more than 12 models the okresy go in two equal requests
  61 s apart, merged into one answer. Checked live on 2026-10-12: a JSON list of 77
  results, columns `<variable>_<model>`, 2.7 MB, under a second.
- **New models** enter only once they have weights, i.e. once `mvd aggregate` has 90-day
  okres scores for them (the D+N backfill fetches their current windows first). Weights
  are per okres, variable and lead day; a model without weights in an okres is left out
  there (the join with the weights), and the request asks only for models with weights
  somewhere. The forecast page (`forecast.js`, `weightedModels`) does the same.
- **Combination:** as on the forecast page (bias correction, weights of the hour's lead
  day, models fading out over their last 3 hours, at least 2 models). Cloud cover and
  sunshine are the plain mean of the models (all 13 models report sunshine, checked
  2026-10-12), then corrected against ČHMÚ observations (`meteoverdict.sun_cloud_gust`,
  [methodology](methodology.md#sunshine-cloud-and-gusts)): sunshine per UTC day as a
  share of the day length, the hours scaled to the corrected day; cloud
  `clip(a + b·mean, 0, 100)`. The coefficients come from `sun-cloud-gust.json` in the
  release `data-latest` (refitted nightly by `mvd sun-cloud-gust`, workflow
  `sun-cloud-gust.yml`), or the bootstrap in the package.
- **Archive (training data, no extra calls):** every run appends the plain model means
  of cloud cover and sunshine of all okresy and hours (`okres`, `issued`, `time`,
  `cloud_cover`, `sunshine_duration`) to `outlook-archive-YYYY-MM.parquet` in the
  release `outlook-archive` (about 11,000 rows a run); a failure there does not fail
  the outlook.
- **Periods** in Prague time: night 0–6, morning 6–12, afternoon 12–18, evening 18–24,
  and the whole day; a part needs at least 4 hours and a day 18 (the answer starts at
  00 UTC, 02:00 in Prague in summer time).
- **Per period:** `tmin`, `tmax`, `precipitation` (sum of the combined hourly values),
  `rain_probability` (share of the models whose own total is ≥ 0.2 mm, among those
  covering the whole period, every model counting the same: the amount weights favour
  AIFS, the worst model at rain or no rain; for parts of day blended 50/50 with a
  calibrated probability from `rain-calibration.json`, refitted nightly by `mvd daily`,
  see [methodology.md](methodology.md#probability-of-precipitation-and-heavy-rain-meteoverdictrain_calibration)),
  `wind` (highest combined hourly mean,
  m/s), `cloud` (%), `sunshine` (hours, sum of the hourly mean), `symbol`: `rain` / `sleet` / `snow` (≤ 2 / ≤ 0.5 °C mean temperature) when the
  share of models is ≥ 50 % and the total ≥ 0.3 mm, `showers` at a calibrated
  probability ≥ 40 % (≥ 30 % of the models without a calibration), otherwise `clear`
  (< 30 % corrected cloud), `partly` (< 65 %) or `cloudy` (thresholds chosen so the
  shares match the observed < 25 / 25–70 / ≥ 70 %: the correction narrows the spread). The whole day's symbol uses the cloud
  of 6–18. With a calibration also `heavy_rain_probability` (P(≥ 5 mm)) and
  `heavy_rain` (true/false), null without; a whole day takes the highest of its parts.
- **Sunrise and sunset** (`sunrise`, `sunset`, Prague time "HH:MM") at the okres point,
  computed with the NOAA solar equations (`meteoverdict.sun`, no request; within half a
  minute of almanacs), the same on every row of a day.
- **Frost** (`night_min`, `coldest_site`, `coldest_min`, `frost_probability`, `frost`,
  `ground_min`, `ground_frost`) on the `night` and `day` rows of the date a night ends:
  the models' night minima (18–06 UTC) corrected with `frost.json` (`mvd frost-fit`,
  daily) and the night means of their cloud and wind; empty without `frost.json`.
  Each run also stores the models' nights at the okres points (minimum, mean wind and
  cloud, lead, point elevation) in `outlook-nights-YYYY-MM.parquet` of `data-YYYY-MM`
  for refitting the clear-calm term, from the same answer (no extra calls).
  [methodology.md](methodology.md#frost-night-minimum-frost-and-ground-frost).
- **Gusts** (`gust`, `gust_warning`, after the frost fields): no Open-Meteo calls. The
  outlook downloads the month file(s) of the single runs (release `runs-YYYY-MM`, a
  few MB to ~50 MB at a month's end) and takes the newest run with gusts of at least
  3 models, at most 36 h old (runs are fetched once 10 h old, so it is usually 10–16 h
  old). Per lowland run station of the okres (≤ 750 m and ≤ 300 m above the okres
  point; an okres without one takes the nearest such station within 30 km): each
  model's largest hourly gust in the part of day, mean over the models (a model must
  reach the part's end; at least 3 models; the part wholly after the run's start),
  corrected with `gust_part` of `sun-cloud-gust.json`, then the mean over the okres's
  stations; a whole day takes the largest of its four parts. `gust_warning` when
  `gust` ≥ 13.5 m/s. `null` beyond the run (about 5 days, the last part cut) and
  when no run is available (`meteoverdict.gusts`,
  [methodology.md](methodology.md#gusts-in-the-outlook)).
- **Output:** `site/data/outlook.json` `{"generated", "time_zone", "parts", "days",
  "okresy": [{code, name, lat, lon}], "columns", "rows"}` (about 110 kB);
  `.github/workflows/outlook.yml` runs it at 05:52 and 17:52 UTC and uploads it to the
  release `data-latest`, after which the Pages workflow rebuilds the map.
- **Budget:** two runs a day ≈ 850 calls with 11 models, ≈ 1,465 with 19; priority 1 in
  the [budget split](#open-meteo-budget) with the backfill and the single runs.

## Ranking with confidence intervals (roadmap 2.5)

`meteoverdict.ranking` (run by `mvd aggregate`) ranks the models of every level,
region, window, variable and lead day by MAE, on the same fair station-days as the
aggregates. Ranked variables: `temperature_2m`, `wind_speed_10m`,
`precipitation_daily`, `precipitation_24h` (hourly precipitation periods differ between
models).

- **Bootstrap:** 1,000 resamples of whole **days** with replacement. All stations and
  models of a day stay together, because forecast errors on one day are correlated
  across stations; resampling hours or stations would make the intervals too narrow
  (a test checks that copying the same errors to more stations does not narrow them).
- `diff_to_best`, `diff_ci_low`, `diff_ci_high`: the MAE difference to the best model
  and its 95 % interval. `tied_with_best` when that interval contains 0;
  `clear_winner` for the best model when no other model is tied with it (never with a
  single model).
- Each group draws from its own seed (a fixed base seed and the group's key), so results
  are reproducible and do not depend on which other groups are computed.
- **Not handled:** autocorrelation between consecutive days (a moving-block bootstrap
  would widen intervals slightly).
- Cost: about 10 s per window for 100 stations × 90 days × all models (measured); the
  full network takes a few minutes, mostly at station level.

### Blend baseline (roadmap 5.3)

Does a plain mean of all models beat every single one? `mvd score` (and the backfill
and daily runs) also score `blend`, the mean of the models' forecasts per station,
hour and lead day and variable, wherever at least 3 models have a value.

- **Members** change with the lead day (D+1 has all models, D+5 only the global ones)
  and with the archive starts; no weighting, no bias correction.
- **Time resolution:** some members are 3- or 6-hourly (Open-Meteo interpolates the
  hours in between), so the blend is scored like a 6-hourly model: temperature and wind
  at 00, 06, 12 and 18 UTC, precipitation over 6-hour periods, the UTC day and the
  06–06 day.
- **Fair comparison:** the blend counts as one more model covering a station, so a day
  without a blend (fewer than 3 members) is dropped for every model there.
- **Ranking:** the blend is not ranked (`rank` null) and never takes the win from a
  model. Its `diff_to_best` and interval are relative to the best single model, so
  `diff_ci_high` below 0 means the mean beats every model in that region; the model
  comparison page shows it next to the ranked models.

## Backfill (`mvd backfill`)

`mvd backfill --from 2024-01-01 [--to D] [--max-calls N] [--github-release]` fills
history newest first in 14-day windows counted from `--from` (a window costs the same
Open-Meteo quota as one day, so windows run across month boundaries). Only **complete**
windows are processed; the newest one is picked up once its 14th day has passed, so
fresh forecasts reach the scores within two weeks. Progress keys include the window's
start and end. For each window:
the observations of its months (once per month), the forecasts of every enabled model
from its archive start, then the window's daily scores.

- **Progress:** in GitHub Actions each run adds a job summary (windows and calls of the
  run, windows scored so far out of all complete windows since `--from`, final months).
- **Resumable:** `data/backfill-state.json` records published observation months,
  finished `model|window` pairs and scored windows. A run stops at `--max-calls` or at
  Open-Meteo's daily limit, keeps what it fetched, and the next run continues. The
  same holds when Open-Meteo keeps failing: server errors, network errors and answers
  that are not JSON (once an empty answer to a request mid-run, 12 Oct 2026) are retried
  after 30, 60 and 120 s, and if they persist the run stops cleanly with the reason in
  its summary instead of failing and losing the window's forecasts fetched so far.
- A month whose observations came from `now/` only (not yet published) is not final:
  its windows are fetched but scored only once ČHMÚ publishes the month.
- With `--github-release` the month files and the state are pulled from and pushed to
  GitHub Releases (`data-YYYY-MM`, state in `data-state`) after every window, so the
  scheduled workflow `.github/workflows/backfill.yml` (daily, the shared 7,400 calls,
  see the [budget split](#open-meteo-budget)) can continue from any machine.
- **Current windows first, older ones last** (`--older-windows always|never|
  after-runs-history`): the complete windows ending in the last 90 days
  (`backfill.CURRENT_DAYS`, the 90-day ranking and the combination weights) are always
  processed; older ones only when allowed (the workflow: once the single-runs history is
  complete). The job summary says which and why, and the calls used today.
- **Priority windows: one full year first, thin** (`--priority-from 2025-10-01
  [--priority-stations CSV]`, since 2026-10-16): while older windows are held back, the
  windows ending on or after `--priority-from` are fetched right after the current ones
  (and before the single-runs history), but only at the ~100 stations of the single runs
  (`run-stations.csv`: every okres, the mountains, spread out), without the rain
  gauges. That gives every season (last winter's biases before this winter, seasonal
  windows, tests of 30/45-day training) for about a fifth of the calls: **~2,000 calls a
  window, ~40,500 for the 21 windows** back to 2025-10-01 (fewer models in the older
  ones). Progress keys `model|start|end|subset`. Once older windows are allowed, these
  windows get the other ~400 stations and their gauges (the subset is not asked again).
  `mvd fetch-runs --backfill-priority-from` reads the same date, so the single-runs
  history waits for them too.
- **How long** (simulated day by day from the live state of 2026-10-17, 7,400 shared
  calls a day since the newest single runs come from Open-Meteo's bucket, a new window
  every 14 days): the current and the priority windows are done around **2026-10-30**
  (with the 4,500 before: 2026-11-08); the single runs' API history (~75,000 calls) then
  follows with what the share leaves, done around **2026-11-10**, and the older windows
  back to 2024-01-01 around **2027-02-05** (before: July 2027). Scheduled runs start late
  or are skipped sometimes, so take these dates as a few days optimistic
  ([budget](#open-meteo-budget)).
- **Models added later:** a `model|window` key that is not in the state is pending, also
  in windows already scored; such a window is fetched again (only the new model) and
  scored again. Because windows go newest first, a new model is fetched for the current
  windows first. Until it is, the fair comparison limits a region's ranking to the days
  every model there has, so the 90-day ranking briefly covers fewer days.
- Budget: about 6,900 calls per window for the first 11 models at ~500 stations, plus
  about 1,550 for the rain gauges (measured on the first real runs, 12 Oct 2026: 5,913 +
  3,785 calls for the newest window); with all 19 models ~11,970 per window and
  ~5,320 per 28-day gauge window one model per request, and since 2026-10-16, with
  models of the same lead days sharing requests (see
  [fetching](#fetching-mvd-fetch-fc)), **~10,070 per window** (−16 %) and **~3,860 per
  gauge window** (−27 %) (`forecasts.estimate_calls`). 2024-01-01 to now is about
  72 windows, fewer models in older ones (archive starts): ~1 million calls, at the
  lowest priority (see [how long](#open-meteo-budget)). The free tier counts calls per IP
  address and GitHub's runners share addresses, so a run can meet the daily limit early;
  it then stops cleanly. ČHMÚ downloads are about 2.5 GB per month of history. Checked
  live on 3 stations × one window (41 calls, 6,270 score rows; a second run did
  nothing).
- **Rain gauges** (the ~280 manual gauges; closed stations are already verified
  hourly): precipitation forecasts only, for 28-day windows counted from `--from`
  (two 14-day windows; progress key `gauges|model|start|end`). With at most 5 lead
  days that is at most 5 variables, so 28 days still cost one call per location: about
  3,100 calls per 28 days for 11 models, ~5,360 for 19, roughly +22 % on the station
  forecasts. The
  newer 14-day window fetches its 28-day gauge window and re-scores both halves, so
  windows scored before the gauges were added get them too. Gauge observations come
  from `recent/` per month into `data/gauges`; a month is final once it ended 62 days
  before `--to` (manual readings arrive about a month late), newer ones are refreshed
  by the daily run.

## Daily pipeline (`mvd daily`)

Run every morning by `.github/workflows/daily.yml` (05:17 UTC, after the backfill, same
concurrency group because both write release assets). No Open-Meteo calls.

1. Pull the months of the last 100 days from the releases, and the single runs'
   months of the last ~36 days (`runs-YYYY-MM`, read only).
2. Capture the last 3 days of observations from `now/` (the current month reaches
   `recent/` only after it ends), and read the rain gauges' months of the last 62 days
   again from `recent/` (about 280 small files a month), as the manual readings arrive.
3. Rebuild D+N of the last 30 days from the single runs for the hours the backfill has
   not delivered (below), and log how both sources agree where both exist.
4. Re-score the last 100 days, so captured observations, forecast windows completed by
   the backfill (replacing the rebuilt forecasts), and checked data replacing unchecked
   data all reach the scores.
5. Push changed months, pull all score months, aggregate and rank, write `site/data`
   and `site/data/badge.json`, and replace `aggregates.parquet` and `site-data.zip` in
   the release `data-latest`.
6. The workflow commits `site/data/badge.json` and `site/data/meta.json` (the README
   no longer has a generated leaderboard; roadmap 6.14).
   The score JSON is only in `data-latest` and on GitHub Pages: even the summary levels
   are about 3 MB a day (first real data, October 2026), too much for the git history.

Freshness: at the ~500 stations forecasts are up to 2-3 weeks behind (complete backfill
windows); at the ~100 run stations up to yesterday (rebuilt from the single runs, below);
observations daily (unchecked first, replaced by checked data once ČHMÚ publishes the
month). A day is scored only when it has both: `now/` keeps about 3 days, so days the
daily run missed (1–9 October 2026, before it was scheduled) wait for the month in
`recent/`. The daily run logs its last scored day and, when that is before the day it
processed, which of those days have forecasts and which have observations.

### Fresh D+N from the single runs

`meteoverdict.fresh` (since 2026-10-16; method and checks in
[methodology.md](methodology.md#fresh-scores-from-the-single-runs)). No Open-Meteo calls:

- **Definition matched:** `<variable>_previous_dayN` at hour T = the newest run that
  started at least 24·N hours before T. From the stored single runs (`runs/`, every
  00/06/12/18 UTC run, leads 1-120): for lead day N the rows with lead 24·N … 24·N+23,
  the newest run per model, station and hour. A run that does not reach the hour hands
  over to the one before (as in the archive).
- **Archive details** (measured live 2026-10-16 by comparing both APIs, `models.yaml`):
  `previous_runs_step_h` 3 for ICON-D2, GeoSphere and DMI, 1 for KNMI (the archive also
  has runs in between, so only hours where a 00/06/12/18 UTC run is the newest are
  rebuilt: 00-02, 06-08, … UTC; KNMI the synoptic hours); `previous_runs_max_lead_h`
  `{6: 47, 18: 47}` for UKMO (the archive's D+2 comes from the 00/12 UTC runs only).
- **Missing runs and hours:** an hour whose first-choice run (the newest of the model's
  `run_hours` at least 24·N h back) is not among the stored runs (not fetched yet, or a
  gap at Open-Meteo) is left out, not taken from an older run. Checked per hour (since
  2026-10-17): an older run stands in only where the first-choice run ends before the
  hour (or the archive keeps it shorter: UKMO), never where that run merely has no row
  at the hour.
- **Native steps** (runs from the bucket, since 2026-10-17): the stored runs have no
  interpolated hours. Temperature and wind are rebuilt at the native hours only (the
  only ones `align` scores where the step is coarser); the precipitation total of a 3-
  or 6-hour step is spread evenly over its hours (`fresh.spread`), as Open-Meteo does in
  the Previous Runs API, so the daily and 06-06 UTC totals add up. Runs stored hourly
  before (the API) are used as they are.
- **D+5** only at leads of exactly 120 h (single runs stop there): the synoptic hours.
- **Merge:** only for model, lead day and hour that `fc/` lacks; the scores get
  `source = single_runs`. Rows are not stored in `fc/` (the backfill's files stay pure
  Previous Runs); they are rebuilt every day for the last 30 days (`fresh.DAYS`).
- **Check, live (2026-10-16):** 11 stations × 11 models × D+1-2 × 14-15 Oct, and 5
  stations × 19 models × D+1-5 × 16-18 Oct (102 weighted calls). Temperature and wind
  identical at every native hour (20,892 values compared; the differences left are
  interpolated hours of 3-/6-hourly models, up to 3.3 °C, never scored, and 7 of 180
  UKMO D+2 values after its output becomes 3-hourly at 54 h). Scores of the ranked
  variables on 14-15 Oct: temperature and wind MAE identical for all 11 models,
  `temperature_max` within 0.009 °C (UKMO D+2), daily precipitation identical except
  AIFS (+0.09 mm) and IFS 0.25° (+0.02 mm), both 6-/3-hourly.
- **Ongoing check:** where both sources exist (the last days of each new backfill
  window), the daily log prints e.g. "single runs vs Previous Runs on 20,892
  overlapping values: mean |difference| 0.030, largest …" (`fresh.compare`, with the
  observations: the MAE of both).
- **Effect** (2026-10-16, real data): the last scored day moves from 2026-10-04 (the end
  of the newest backfill window) to yesterday, so `meta.json` `as_of`, the 90-day
  ranking and the combination weights and bias corrections include the last days.
  D+1 and D+2 at once; D+3 to D+5 fill in as the single runs reach back far enough
  (stored from 2026-10-13 00 UTC; the single-runs history adds older runs).

## Data quality (`mvd check`)

Run by the daily workflow after `mvd daily` and before the commit. An **error** fails
the run, so GitHub notifies the owner and nothing is committed; the report
also appears on the run page (job summary).

| Check | Error | Warning |
|---|---|---|
| newest observation | older than 30 h | |
| newest forecast, newest score | older than 21 days (complete backfill windows lag up to 15) | |
| published scores (`site/data/meta.json`, `mvd check --meta`) | `as_of` more than 21 days before `generated` (forecasts come in 14-day windows, so up to ~20 is normal) | file missing; models left out of the 90-day ranking and weights for too short a record (`short_record`, under 80 % of the days; normal for a few weeks after a model is added) |
| stations reporting in the last 3 days, of those that reported in the last 30 | under 80 % | the stations missing |
| temperature MAE per station over 90 days (all models) | | above 3 x the network median and above 3 °C: sensor or metadata problem |

Before that, observations outside physically plausible limits are dropped when they are
read: temperature −50…50 °C (Czech records −42.2 and 40.4 °C), wind 0…75 m/s, hourly
precipitation 0…120 mm.

## Raw data store

`mvd store upload` and `mvd store download --from YYYY-MM [--to YYYY-MM]` keep
`data/{obs,gauges,fc,scores}/YYYY-MM.parquet` as the assets
`{obs,gauges,fc,scores}-YYYY-MM.parquet`
of the release `data-YYYY-MM`. GitHub
cannot overwrite a release asset, so a changed file is deleted and uploaded again; the
asset label holds the file's SHA-256 so unchanged files are skipped. Downloads go
through the API (`Accept: application/octet-stream`), which redirects to GitHub's storage
host; httpx drops the token on that redirect. Checked end to end on 2026-10-12 with a
throwaway release (upload, skip, replace, download byte for byte, then deleted). Release
assets may be up to 2 GiB each.

## ALADIN archive

ČHMÚ publishes ALADIN runs (00, 06, 12, 18 UTC) at
`opendata.chmi.cz/meteorology/weather/nwp_aladin/{CZ_1km,Lambert_2.3km}/{HH}/`, one
bz2-compressed GRIB1 file per field and run, e.g.
`ALADCZ1K4opendata_2026101100_CLSTEMPERATURE.grb.bz2`. Field names and units are in
`Popis_obsahu.xlsx` in that folder. **Only the last three days are kept** (runs from
2026-10-09 to 2026-10-11 on 2026-10-11), so older runs are gone for good unless someone
archived them. Licence: CC BY 4.0, author ČHMÚ (National Open Data Catalogue datasets
"Numerické předpovědi počasí modelu ALADIN/ČHMÚ: produkty na oblasti ČR" and
"… produkty v projekci Lambert").

What we verified in the files (run 2026-10-11 00 UTC):

| Domain | Grid | Steps |
|---|---|---|
| `CZ_1km` (`chmi_aladin_cz_1km`) | regular lat/lon, 501 × 290, 0.014° × 0.009°, lat 48.5–51.098, lon 12.0–18.995 | 0–72 h hourly |
| `Lambert_2.3km` (`chmi_aladin_central_europe_2km`) | Lambert conformal, 1053 × 837 | 0–72 h hourly |

**"ALADIN CZ 1 km" is not a 1 km model run.** ČHMÚ's own description of the files
(`Popis_obsahu.xlsx`, checked 2026-10-16) calls the `CZ1K` sheet "Výstupy modelu ALADIN:
post-processingová oblast CZ1K, pravidelný rastr v zeměpisných souřadnicích app 1km"
(a post-processing area on a regular ~1 km lat/lon grid), and the `Lambert` sheet "vnitřní
výpočetní oblast, modelový grid v rozlišení 2.3 km" (the model's own computational grid).
The operational model is ALADIN in its ALARO configuration at 2.3 km (Mašek 2023,
https://doi.org/10.59984/978-80-7653-063-8.06); a real ~1 km configuration is a plan of
ČHMÚ's new supercomputer project. So Open-Meteo's `chmi_aladin_cz_1km` and
`chmi_aladin_central_europe_2km` are the **same model run** on two grids, and they score
almost alike: on the same runs and stations they differ by about 0.13 °C and 0.15 m/s on
average and 97 % of their daily precipitation values are identical (review of
2026-10-16). In the ranking they are near-duplicates (and both count in the mean of all
models).

- `CLSTEMPERATURE`: 2 m temperature, K, instantaneous.
- `CLSWIND_SPEED`: 10 m wind speed, m/s, instantaneous.
- `SURFPREC_TOTAL`: total precipitation in kg/m² (= mm), **accumulated since the start
  of the run**; there is no step 0.
- `SURFGEOPOTENTIEL`: model orography as geopotential (m²/s²); ÷ 9.80665 gives the
  model terrain height.
- About 55 MB per run for these fields on the 1 km grid, about 250 MB on the 2.3 km grid.

`mvd archive-aladin` (run every three hours by `.github/workflows/archive-aladin.yml`)
stores, for each run still on the server, one Parquet file per domain and run with one
row per station and lead hour:

| Column | Meaning |
|---|---|
| `model`, `run`, `lead_h`, `valid_time` | model id, run time (UTC), lead in hours (0–72), `run + lead_h` |
| `station_id` | WIGOS id from `mvd stations` |
| `temperature_2m` | °C (converted from K) |
| `wind_speed_10m` | m/s |
| `precipitation_accum` | mm since the run started; null at lead 0. Hourly sums are differences of consecutive leads. |
| `grid_lat`, `grid_lon`, `grid_elevation`, `grid_distance_km` | the grid point used (nearest to the station), its model terrain height (m) and its distance from the station |
| `published` | when ČHMÚ published the run (UTC): the latest HTTP `Last-Modified` of the four files read; null in files archived before 2026-10-13 and if the server sends no header |

Values are taken at the **nearest grid point, without elevation correction**, unlike
Open-Meteo, which downscales to the station elevation. `grid_elevation` makes a
correction possible later. Stations more than 3 km from every grid point are skipped
(none in Czechia: the largest distance was 0.7 km on the 1 km grid, 1.6 km on the 2.3 km
grid). Files are about 0.5 MB per run and domain, so roughly 4 MB a day.

Check against Open-Meteo, Praha-Libuš, run 2026-10-11 18 UTC + 24 h and + 25 h, compared
with Open-Meteo's `chmi_aladin_cz_1km` `_previous_day1` at the same grid cell
(`cell_selection=nearest`, `elevation=290`): 8.53 °C vs 8.6 °C and 7.40 °C vs 7.4 °C;
wind 1.20 vs 1.2 m/s and 0.93 vs 0.9 m/s.

The files are published as assets of the GitHub release `aladin-YYYY-MM` of this
repository (`chmi_aladin_cz_1km_2026101100.parquet`, …), with the CC BY 4.0
attribution and our changes stated in the release notes.

**Publication time.** opendata.chmi.cz (nginx) sends `Last-Modified` with every file,
and the directory listing shows the same time to the minute (checked 2026-10-13: the
listing's `12-Oct-2026 10:24` for `…2026101206_CLSTEMPERATURE.grb.bz2`, header
`Mon, 12 Oct 2026 10:24:09 GMT`). Over the runs of 2026-10-11 to 2026-10-13 the four
fields we read appeared on the 1 km domain, after the run's start: 00 UTC run 3 h 30–3 h 34, 06 UTC
4 h 24–4 h 25, 12 UTC 3 h 13–3 h 14, 18 UTC 4 h 22–4 h 25 (the Lambert domain's
temperature a few minutes earlier than its precipitation). Since 2026-10-13 the archive
stores this as `published`; readers of older files get null (polars
`concat(how="diagonal_relaxed")`). It is not used in any score yet; it is there for a
later "what could a user actually see" score (the newest run published before the
time of use).

ČHMÚ's checked station observations stay online (`recent/` the last 12 months,
`historical/` all closed years), but the unchecked 10-minute and hourly data of `now/`
are kept for only about three days; the [ČHMÚ archive](#chmi-archive) keeps them, and
everything else ČHMÚ publishes for the stations.

<a id="chmi-archive"></a>

## ČHMÚ archive

`mvd chmi-archive` (module `meteoverdict.chmi_archive`) keeps **every element of every
station in every resolution** that ČHMÚ publishes under `meteorology/climate/`, also
what the scores do not use. What exists and how big it is: [chmi-data.md](chmi-data.md).
Licence CC BY 4.0, ČHMÚ; the values are unchanged, only converted from JSON to Parquet.

### Format

Every file has the same long table, one row per station, time and element (and, for
the statistics, time function and statistic), sorted by `station`, `resolution`,
`time`, `element`, `vtype`, `func`; zstd-compressed Parquet with column statistics, so
a reader can filter by station or time without reading everything:

| Column | Type | From ČHMÚ |
|---|---|---|
| `station` | string | `STATION` (WIGOS id) |
| `resolution` | string | `10min`, `1hour`, `daily`, `pentadic`, `monthly`, `yearly`, `phenomena` |
| `time` | timestamp (ms, UTC) | `DT` (end of a 10-minute or hourly interval, ČHMÚ's daily stamp); for statistics the start of the period: pentade *p* of a month starts on day 5(*p*−1)+1, a month on the 1st, a year on 1 January; phenomena the day at 00:00 |
| `element` | string | `ELEMENT`, or `PHENOMENON` (e.g. `BO`) |
| `vtype` | string | daily `VTYPE` (`AVG`, `SUM`, `06:00`, …) or `TIMEFUNCTION` of the statistics |
| `func` | string | `MDFUNCTION` of the statistics (`AVG`, `MAX`, `MIN`, `SUM`, `GE(30)` = number of days ≥ 30, …) |
| `value` | float32 | `VAL` / `VALUE`; null where ČHMÚ sends `""` (missing, quality 4); null for phenomena |
| `flag` | string | `FLAG` (meanings in `meta3`), or `FLAG_REPEAT` of the statistics |
| `flag2` | string | `FLAG_INTERRUPTED` of the statistics |
| `quality` | uint8 | `QUALITY` (`meta4`: 0 good, 1 suspect, 2 poor, 3 estimated, 4 missing, 5 unknown = not checked yet) |

Recent monthly and pentadic files have no `YEAR`/`MONTH` columns; they come from the
file name. ČHMÚ's missing rows (`""`, quality 4) are kept: they say a value was
expected.

### Files and releases

Each file is an asset of a GitHub release of this repository (labels hold the SHA-256);
`mvd chmi-archive --out-dir DIR` writes the same layout to a disk,
`DIR/<release>/<file>`:

| Release | Files | What | Size |
|---|---|---|---|
| `chmi-now-YYYY` | `chmi-now-YYYY-MM-DD.parquet` | one UTC day, 10-minute and hourly rows of all stations as first published (from `now/`, mostly not checked; from `recent/`'s day files if the day already left `now/`) | ~0.8 MB a day |
| | `chmi-meta-YYYY-MM-DD.zip` | `meta1`…`meta4` of that day as published (JSON) | ~55 kB |
| `chmi-YYYY` | `chmi-10min-YYYY-MM.parquet`, `chmi-1hour-YYYY-MM.parquet` | one month of all stations, checked (`historical/` for closed years, else `recent/`) | 10 min ~21 MB, 1 h ~1.2 MB |
| | `chmi-{daily,monthly,pentadic,phenomena}-YYYY-MM.parquet` | one month of all stations from `recent/`, for months not in the station histories yet (the current year; the current month grows daily) | < 2 MB |
| `chmi-history-D` (D = last digit of the WSI) | `chmi-history-<WSI>.parquet` | all closed years of one station: daily, monthly, pentadic, yearly and phenomena (`historical/`), back to 1775 | 0.1–5 MB, ~1 GB for 1,550 stations |
| `chmi-state` | `chmi-archive-state.json` | progress: for each month and station, a fingerprint of the ČHMÚ files it was built from | small |

Per-station history files (not per year) because that is how ČHMÚ publishes the
closed years (one file of up to 100 MB per station), which makes the backfill
resumable station by station and gives the station pages one file per station.
Ten releases keep each under GitHub's 1,000 files. A year in both a station history
and `chmi-…-YYYY-MM` month files (after ČHMÚ's yearly update) is the same data; the
history is the reference.

Reading it (after `mvd chmi-mirror DIR`):

```python
import polars as pl

libus = pl.read_parquet("DIR/chmi-history-0/chmi-history-0-20000-0-11520.parquet")
t = (
    pl.scan_parquet("DIR/chmi-2025/chmi-10min-2025-*.parquet")
    .filter(pl.col("station") == "0-20000-0-11520", pl.col("element") == "T")
    .collect()
)
```

### Units of work and schedule

Work is split into units, one file each, done in this order (newest first) until the
time budget (`--max-minutes`) is used up; the state remembers each unit's fingerprint
(names, sizes and dates in ČHMÚ's directory listing), so a unit is done again only
when ČHMÚ changes its files, and a stopped run resumes with the next unit:

| `--part` | Unit | When |
|---|---|---|
| `days` | a complete UTC day not archived yet | `chmi-archive.yml`, 01:41 and 13:41 UTC (two chances per day; `now/` keeps ~3) |
| `recent` | a month of one resolution in `recent/` whose files changed | same runs; daily data change every day, 10 min and 1 h after ČHMÚ's checks (the 3rd of the month) |
| `history` | one station's closed years | `chmi-backfill.yml`, 02:07 UTC, 5 hours a run |
| `months` | a closed month of 10-minute or hourly data (2018 on, hourly first) | same |

Both workflows share the concurrency group `chmi-archive`, so they never write the
state at the same time; neither calls Open-Meteo. Downloads use 4 parallel
connections and the retries of `mvd fetch-obs` (2, 5 and 15 s on network or server
errors and unreadable bodies). A listed file that still cannot be read (ČHMÚ
sometimes serves an empty body) is left out and counted in the run's summary
("unreadable files left out"), like a missing station-day in `mvd fetch-obs`.

**Backfill estimate** ([details](chmi-data.md#what-the-archive-costs)): about 157 GB of
JSON to download, about 3.1 GB of Parquet stored; at the measured 2–8 MB/s about 6–9
hours, i.e. two or three daily runs. Then about 0.6 GB a year.

```bash
uv run mvd chmi-archive --part days --out-dir data/chmi           # the last days
uv run mvd chmi-archive --part history --station 0-20000-0-11520 \
    --out-dir data/chmi                                         # one station's history (a trial)
uv run mvd chmi-mirror /Volumes/disk/chmi                         # copy the archive (needs GITHUB_TOKEN)
```

`--station` limits `recent`, `history` and `months` to some stations, for trials; the
files are then partial, so the state is not saved.

<a id="station-pages"></a>

### Station pages

`mvd station-pages` (module `meteoverdict.station_pages`) writes one JSON per station
for `web/station.html`, from the archive (`--github-release` first downloads the files it
needs into `--archive`, default `data/chmi`; `--publish` uploads the folder as
`station-data.zip` to `data-latest`, which the Pages workflow unpacks into
`data/scores/station/`):

- `station/index.json`: `{"generated", "stations": [{id, name, okres, kraj, lat, lon,
  elevation, active, network, views, elements}]}` for the search and the station map
  (`network`: the [kind of station](#kinds-of-station); `elements`: the codes with
  values, without the ceilometer's and the phenomena). The map guesses the kind from the
  id, elements and views for an older index without `network`;
- `station/<WSI>.json`: `station` (from `mvd stations`), `elements` (from ČHMÚ's
  `meta2`: Czech name, unit, sensor height, kinds `10M`/`1H`/`DLY`/`PHENO`, first and
  last day, and the `views` that have it), `series` and `source`.

Each series is `{"start", "step", "values": {element: [...]}, "how": {element: label}}`;
value *i* is at `start + i × step`, null where there is none, rounded to 0.1:

| View | Step | Covers | From |
|---|---|---|---|
| `10min` | 10 min | the last 3 days up to the newest value | month files, else the captured days |
| `1hour` | 1 h | the last 30 days | hourly elements, and 10-minute elements at the full hour (not `SRA10M`, `SSV10M`, whose hourly totals are `SRA1H`, `SSV1H`) |
| `daily` | 1 day | the last 3 years and this one | station history, then the recent month files after it; one series per element: the daily mean (`AVG`) where there is one, else the sum, else the only observation time |
| `monthly` | 1 month | the whole history | ČHMÚ's monthly statistics: the mean (`AVG AVG`) where there is one, else the total, maximum or minimum; `how` says which |

Sizes (measured 2026-10-15): Praha-Libuš 469 kB (10 min 37, hourly 196 with 35
ceilometer elements, daily 149, monthly 69), Brno-Tuřany 380 kB, Lysá hora 507 kB
(118, 100 and 106 kB gzipped as GitHub Pages serves them); the 10-minute and hourly
part of all 476 automatic stations 28 MB. Estimated for all ~780 stations: about
120 MB (≈ 40 stations with hourly synoptic elements at ~0.5 MB, ~440 automatic stations
at ~0.2 MB, ~300 rain gauges at ~0.05 MB); at most 0.4 GB even if every station were
as big as Lysá hora, well under GitHub Pages' 1 GB. Building all of them took 16 s
and 2 GB of memory.

## Radar archive

ČHMÚ publishes its weather radar composites (radars Brdy-Praha and Skalky) at
`opendata.chmi.cz/meteorology/weather/radar/composite/`, described in
`radar/radar_description_en.pdf` (version 1.3, 2026-05-26). **Files stay online for only
about seven days** (on 2026-10-15 the oldest was 2026-10-08 00:05). The folders `sites/`
(3D volumes of each radar, not archived) and `scl/` (the colour scales) sit next to
`composite/`. The server sends no CORS headers, so a browser cannot read it directly.

Licence: CC BY 4.0, author ČHMÚ. Checked 2026-10-15 in the National Open Data Catalogue
(data.gov.cz SPARQL, `pu:autorské-dílo` and `pu:databáze-jako-autorské-dílo` of each
distribution): "Radarová data ČHMÚ", "Sloučená informace maximální radarové odrazivosti
MAX_Z pro území Česka", "… PseudoCAPPI_2km …", "… výšky radarových odrazů ECHO_TOP …",
"Kombinovaný odhad plošných 1hodinových srážkových úhrnů MERGE na území Česka" and the
two "Extrapolační předpověď …" datasets.

### Products

| Key (`--products`) | Folder | File name (time in UTC) | Step | MB a day¹ |
|---|---|---|---|---|
| `maxz-hdf5` | `maxz/hdf5` | `T_PABV23_C_OKPR_YYYYMMDDhhmm00.hdf` | 5 min | 12.7 |
| `maxz-png` | `maxz/png` | `pacz2gmaps3.z_max3d.YYYYMMDD.hhmm.0.png` | 5 min | 2.6 |
| `maxz-png_masked` | `maxz/png_masked` | same name; echoes not reaching the ground in lighter colours | 5 min | 2.7 |
| `cappi2km-hdf5` | `pseudocappi2km/hdf5` | `T_PANV23_C_OKPR_…hdf` | 5 min | 6.7 |
| `cappi2km-png` | `pseudocappi2km/png` | `pacz2gmaps3.z_cappi020.….0.png` | 5 min | 1.9 |
| `echotop-hdf5` | `echotop/hdf5` | `T_PADV23_C_OKPR_…hdf` (no PNG) | 5 min | 5.7 |
| `merge1h-hdf5` | `merge1h/hdf5` | `T_PASV23_C_OKPR_…hdf` | 10 min | 2.6 |
| `merge1h-png` | `merge1h/png` | `pacz2gmaps3.merge.YYYYMMDD.hhmm.60.png` | 10 min | 0.8 |
| `fct_maxz-hdf5` | `fct_maxz/hdf5` | `T_PABV23_C_OKPR_YYYYMMDD.hhmm.ft60s10.tar` (6 HDF5, +10 … +60 min) | 5 min | 46.1 |
| `fct_maxz-png` | `fct_maxz/png` | `pacz2gmaps3.fct_z_max.YYYYMMDD.hhmm.ft60s10.tar` (6 PNG) | 5 min | 15.3 |
| `fct_maxz-png_masked` | `fct_maxz/png_masked` | same name | 5 min | 16.0 |
| `fct_cappi2km-hdf5` | `fct_pseudocappi2km/hdf5` | `T_PANV23_C_OKPR_….ft60s10.tar` | 5 min | 42.1 |
| `fct_cappi2km-png` | `fct_pseudocappi2km/png` | `pacz2gmaps3.fct_z_cappi020.….ft60s10.tar` | 5 min | 13.5 |

¹ Measured on 2026-10-14 (a day with a frontal rain band), as uncompressed tars of the
day's files. Sizes grow with the area of echoes, so days with widespread rain or many
storms are larger. The files are
already compressed (HDF5 with internal compression, PNG), so a compressed tar would not
be smaller.

- **Times.** Composites: the end of the 5-minute interval. MERGE: the end of the hour
  it sums (`T_PASV23_…20261014040000.hdf` = 03:00–04:00 UTC), the same convention as
  our hourly observations. Nowcasts: the tar is named by the time of the calculation,
  each member by its valid time and lead (`….20261015.1115.40.png` = 11:15, +40 min).
- **Latency.** Composites and nowcasts appear within a minute; MERGE 20 minutes to
  1.5 hours after the hour (it waits for the rain gauges).
- **Grid** (HDF5 `/where`, the same in every product): Web Mercator (EPSG:3857 sphere,
  `+proj=merc +a=6378137`), 598 × 378 cells of 1555.7 m (about 1 km at 50° N), outer
  edges 11.266869–19.623974° E, 48.047275–51.458369° N. The PDF gives the same bounds
  rounded (E 11.267–19.624, N 48.047–51.458).
- **PNG** files are 680 × 460 with an 8-bit palette: the grid in the bottom-left
  598 × 378 pixels (rows 82–459), side views of the maximum above and to the right,
  the title over the top-left corner, black frame lines (palette index 145), grey
  outside the radar coverage (index 242) and transparent background (index 0); the
  whole image spans E 11.267–20.770°, N 48.047–52.167° (PDF). We checked the crop
  against the HDF5 of the same time: cells with ≥ 4 dBZ and coloured pixels overlap
  99.6 % (test `test_png_crop_lines_up_with_the_hdf5_grid`).
- **Values.** MAX_Z and PseudoCAPPI: `DBZH = 0.5 × code − 32`, code 0 = no echo, 255 =
  no data. Echo top: `HGHT`. MERGE (`ACRR`): `mm = 0.1 × code`, 32766 = no precipitation
  detected, 32767 = outside its domain (a rotated rectangle around Czechia).
- **Colour scales**: `radar/scl/scl-dbz-mmh.png` (4–60 dBZ in steps of 4, with mm/h by
  Marshall–Palmer) and `scl-mm.png` (0.1–100 mm); the radar page copies both.

### What `mvd archive-radar` stores

Once a UTC day is complete (3 hours after midnight, for MERGE), each product of that
day becomes one uncompressed tar of the files as published, named after the product and
day, as an asset of the monthly release `radar-YYYY-MM`:

```
radar-2026-10/
  maxz-hdf5-20261014.tar              288 files
  maxz-png_masked-20261014.tar        …
  merge1h-hdf5-20261014.tar           144 files
  merge1h-hourly-20261014.npz         derived: the 24 hourly MERGE grids
  merge1h-stations-20261014.parquet   derived: MERGE at the ČHMÚ stations
  web-20261014.tar                    derived: the radar page's frames of that day
```

The asset label says how many files the tar has (`files=288`), so gaps on ČHMÚ's side
show without downloading. Days already in the release are skipped; a failed file or
upload leaves that asset out and the next run tries again (as long as ČHMÚ still has
the day). `--day YYYY-MM-DD` archives given days, `--out-dir DIR` writes the same layout
to a local folder, `--no-derived` skips the derived files.

- **`merge1h-hourly-YYYYMMDD.npz`** (numpy `savez_compressed`, ~0.1 MB): `acrr` uint16
  `(hours, 378, 598)` codes of the MERGE fields at full hours (rows north → south),
  `time` (`YYYYMMDDhhmm`, end of the hour), `gain`, `offset`, `nodata`, `undetect`,
  the grid edges and `projdef`.
- **`merge1h-stations-YYYYMMDD.parquet`**: `station_id` (WIGOS id from `mvd stations`),
  `time` (UTC, end of the hour), `precipitation` (mm; 0 when nothing was detected, null
  outside the MERGE domain), `grid_row`, `grid_col` (the cell containing the station:
  no interpolation). On 2026-10-14 at the 469 stations with hourly observations the
  hours line up exactly with ours (correlation 0.79 at the same hour, 0.26 and 0.20
  one hour off), and many gauge stations match to 0.1 mm, since MERGE is fitted to the
  gauges (kriging with external drift): it is not an independent check of them.
- **`web-YYYYMMDD.tar`**: `index.json` and the frames of the radar page (below) for the
  day: radar, echo tops, motion, cells and satellite images, 5–21 MB.

**Size.** The observed products (`--products observed`, what the Radar workflow
stores) were 35.7 MB on 2026-10-14 plus 3 MB derived: about 1.2 GB a month and
**14 GB a year**, more in a wet year (plan 15–25 GB a year). The nowcasts
(`--products forecast`) are 133 MB a day: **4 GB a month, 49 GB a year**, so together
the archive would pass 50 GB within a year. Every asset stays far below GitHub's
2 GiB per asset (the largest, `fct_maxz-hdf5`, is ~50 MB) and a month has at most
16 × 31 = 496 assets. The nowcasts are therefore not archived on GitHub; they can be
kept on a local disk (below). If even the observed archive grows too large, the PNG
products (`maxz-png`, `cappi2km-png`, 4.5 MB a day) are the first to move to a local
disk only: they can be redrawn from the HDF5.

**Local copy.** The release layout maps 1:1 to a folder:

```bash
uv run mvd mirror-radar --out-dir /Volumes/data/radar            # all radar-YYYY-MM assets
uv run mvd mirror-radar --out-dir /Volumes/data/radar --since 2026-10
# the same with the GitHub CLI
for tag in $(gh release list --limit 1000 --json tagName -q '.[].tagName' | grep '^radar-'); do
  gh release download "$tag" --dir "/Volumes/data/radar/$tag" --skip-existing
done
# the nowcasts, straight from ČHMÚ into the same layout (run at least every 5 days)
uv run mvd archive-radar --products forecast --out-dir /Volumes/data/radar
```

`mirror-radar` skips files that are already there with the same size. The pipeline
never depends on the local copy.

### Radar page frames

The radar page (`radar.html`) shows `maxz/png_masked` (echoes that probably do not
reach the ground in lighter colours), the `fct_maxz/png_masked` nowcast and
`merge1h/png`. For the page each PNG is cropped to the grid (rows 82–459, columns
0–597), so it can be placed with the exact grid edges as a MapLibre image source; the
frame lines and title (index 145) become transparent, the grey outside the radar
coverage faint (fully transparent for MERGE and the nowcast, whose title lies on it);
the palette, and so ČHMÚ's colours, stay. A frame is 2–13 KB.

### Radar live data contract

A frame folder (the branch `radar-live`, and each day's `web-YYYYMMDD.tar` unpacked to
`radar/days/YYYYMMDD/` of the site) has `index.json` and the files it lists. Times are
UTC stamps `YYYYMMDDhhmm`; radar frames are named by the end of their 5-minute interval,
satellite frames by the start of their scan. Every image is Web Mercator and covers
exactly the `bounds` given for it, so it can be a MapLibre image source with the corners
`[west, north], [east, north], [east, south], [west, south]`.

```
index.json
maxz/<stamp>.png          max reflectivity (ČHMÚ PNG, cropped; ČHMÚ colours), every 5 min
merge1h/<stamp>.png       MERGE 1-hour precipitation ending at <stamp>, every 10 min
nowcast/<valid>.png       the newest nowcast, +10 … +60 min (live only)
echotop/<stamp>.png       echo top, every 5 min (ours, from the ECHO_TOP HDF5)
motion/<stamp>.json       motion of the echoes from the frame before to <stamp>
cells/<stamp>.json        storm cells at <stamp>
satellite/<product>/<stamp>.webp   Meteosat image (vis-ir, night-M, wv062), every 15 min
```

`index.json`:

| Key | Value |
|---|---|
| `version` | `1` (keys are only ever added) |
| `bounds` | `[[west, south], [east, north]]` of the radar grid (`maxz`, `merge1h`, `nowcast`, `echotop`, and the grid of `motion` and `cells`): 11.266869, 48.047275, 19.623974, 51.458369 |
| `maxz`, `merge1h`, `echotop`, `motion`, `cells` | sorted stamps of the files present. `motion` has no entry for a frame without a frame ≤ 15 min before it (the first frame of an archived day, gaps) |
| `nowcast` | `{"base": stamp of the run, "frames": [{"time": valid stamp, "lead": minutes}, …]}` (live only) |
| `satellite` | `{product: {"bounds": [[west, south], [east, north]], "ext": "webp", "frames": [stamps]}}` for `vis-ir`, `night-M`, `wv062`; always present, `frames` may be empty (`vis-ir` only by day, `night-M` only by night, days older than 7 on Pages) |
| `scales` | `{"maxz": [[dBZ, "#hex", mm/h, "label_en", "label_cs"], …], "merge1h": [[mm, "#hex"], …], "echotop": [[km, "#hex"], …]}`; each entry is the lower edge of a colour class |
| `generated` | time the folder was updated, `YYYY-MM-DDThh:mm:ssZ` (live only) |
| `attribution` | radar credit (ČHMÚ, CC BY 4.0, our changes) |
| `satellite_attribution` | satellite credit, present when there are satellite frames: "Satellite images: contains modified EUMETSAT Meteosat data <year> (CC BY 4.0), processed by ČHMÚ (opendata.chmi.cz, CC BY 4.0); cropped and converted to WebP by MeteoVerdict." ([licensing](licensing.md)) |

**`maxz` scale** (ČHMÚ's `scl-dbz-mmh.png`, the palette of its PNG composites): 4, 8, …,
60 dBZ from `#380070` to `#fcfcfc`; mm/h is the Marshall–Palmer rate at the lower edge
(Z = 200 R^1.6: 20 dBZ 0.65, 28 dBZ 2.05, 40 dBZ 11.5, 52 dBZ 65 mm/h); labels from 4 dBZ
drizzle/mrholení, 16 light/slabé, 28 moderate/mírné, 40 heavy/silné, 48 very heavy/velmi
silné, 56 hail possible/možné kroupy. **`merge1h`**: ČHMÚ's `scl-mm.png`, 0.1 … 100 mm.
**`echotop`** (ours, ČHMÚ publishes no echo-top scale): 2 km classes from 0 (`#a6bddb`;
blues and greens for shallow rain) to 14 km (`#800026`), yellow from 8 km, orange to red
from 10 km, where storm tops reach. ECHO_TOP is the highest altitude (above sea level)
with at least **4 dBZ**, so it is higher than the more usual 18 dBZ echo top. A frame is
an 8-bit PNG (index 0 transparent: no echo or no data), 1–35 KB.

**`motion/<stamp>.json`**: `{"nx": 19, "ny": 12, "dt_s": 300, "u": […], "v": […]}`,
`u` and `v` row-major (`ny` rows from the north, `nx` columns from the west), in **radar
grid cells (maxz pixels) per `dt_s`** (1 cell = 1555.7 Web Mercator metres ≈ 1.0 km at
50° N). `u` positive = towards increasing columns (east), `v` positive = towards
increasing **rows (south, down the image)**. The field at `<stamp>` is the motion from the
frame before to `<stamp>`: an echo at grid position (x, y) in the frame `dt_s` seconds
before is at (x + u, y + v) at `<stamp>`. The blocks span the grid evenly: value (j, i)
belongs to column (i + 0.5) × 598 / nx and row (j + 0.5) × 378 / ny; interpolate
bilinearly between block centres. `dt_s` is normally 300; after a missing frame it is the
real gap (≤ 900). Method: dense optical flow (OpenCV DIS, preset medium; the "Dense"
model of rainymotion, Ayzel et al. 2019, doi:10.5194/gmd-12-1387-2019) between the two
MAX_Z grids (10–60 dBZ as grey levels), averaged per block weighted by the echoes
(weight 0 below 10 dBZ, 1 from 30 dBZ), blocks with few echoes blended with their
neighbours (Gaussian σ 1.5 blocks), empty blocks filled from farther echoes (σ 6 blocks)
or the mean motion of all echoes, which shrinks towards 0 when echoes cover less than
0.5 % of the grid; then smoothed (σ 0.8 blocks). Warping the earlier frame with the field
cut the mean squared reflectivity difference to the later one by about two thirds on
2026-10-10 (frontal rain moving 50 km/h to the north-east: 75 → 28 dBZ²) and on the
evening of 2026-10-15 (weak showers: 1340 → 450), while the opposite sign made it worse.
About 2 KB a frame.

**`cells/<stamp>.json`**: a list, strongest first:

```json
[{"id": "202610101020-3", "lon": 13.9652, "lat": 50.0391, "max_dbz": 45.0,
  "echotop_km": 7.1, "area_km2": 11, "speed_kmh": 51, "dir_deg": 67, "hail": false,
  "track": [[13.5515, 49.9073], …, [13.9652, 50.0391]]}]
```

- A **cell** is a contiguous (8-connected) area of MAX_Z ≥ **40 dBZ** of at least
  **5 km²** (true area: grid cell side 1.5557 km × cos φ). `lon`/`lat`: centroid weighted
  by linear reflectivity. `max_dbz`: strongest echo; `echotop_km`: highest echo top in
  the cell and one grid cell around it (tops lean downwind), `null` without ECHO_TOP.
- `speed_kmh`, `dir_deg`: mean optical flow inside the cell (as for `motion`, before the
  block averaging); `dir_deg` is the direction it moves **to** (0 = north, 90 = east).
  Both `null` for the first frame or after a gap > 15 min; `dir_deg` also at 0 km/h.
- **`hail`**: `max_dbz ≥ 55` and `echotop_km ≥ 10`. 55 dBZ is the usual radar hail
  threshold (Mason 1971; used e.g. for the European hail climatology of Fluck et al.
  2021, NHESS 21, 683–701); the echo-top condition stands in for the height criteria that
  Skripniková and Řezáčová (2014, Atmos. Res. 144, 175–185,
  doi:10.1016/j.atmosres.2013.06.002) found best over Czechia (Waldvogel: 45 dBZ at least
  1.4 km above the freezing level). We have neither the 45 dBZ height nor the freezing
  level, so this is a **rough indicator ("hail possible")**, not a hail detection.
- **Ids** stay while a cell overlaps (or, without overlap, lies within 8 km of) a cell of
  the frame before moved by that cell's motion; the largest overlap wins, so after a split
  one part keeps the id. New ids are `<stamp>-<n>`. Frames more than 15 minutes apart are
  not matched; cells of an archived day start fresh at 00:00. `track`: the centroids of
  the last 30 minutes (up to 7 points, oldest first, the current one last).
- On 2026-10-10 (frontal rain with embedded showers): 373 cell records in 288 frames,
  150 ids, tracks up to 7 points, no hail flag; 0.07 MB for the day. The cells of the
  newest frame wait for its ECHO_TOP file if it is not out yet.

**Satellite frames**: the `ce` images of ČHMÚ ([Satellite images](#satellite-images)),
cropped to 3.492–25.509° E, 44.493–55.504° N (787 × 616 pixels of 3114.2 Web Mercator
metres, ~2 km at 50° N) and saved as **WebP** (quality 70; about half the size of a JPEG
of the same look: a noon `vis-ir` 51 KB against 93 KB). 3–60 KB a frame.

### Live loop

`mvd radar-live --dir DIR --hours 24 [--satellite-hours H] [--cache CACHE]` downloads only
missing frames, makes the missing echo tops, motion fields and cells from the HDF5
composites (kept in `CACHE` for an hour so the next round does not fetch them again),
deletes everything older than the window, replaces the nowcast when a newer one exists
and rewrites `index.json`. The Radar workflow runs it in a **loop** (job "Live loop",
`scripts/radar_live_loop.sh`): every 5 minutes, 1 minute after each 5-minute mark (ČHMÚ
publishes a composite within that minute), it updates the folder and force-pushes it as
a single commit to `radar-live`. The folder is a clone of the branch, so a push sends only
the new files (~100 KB). A loop runs for 340 minutes (job timeout 355; GitHub's maximum
is 6 h); about 7 minutes before its end it starts the next run of the workflow
(`gh workflow run radar.yml -f live=true -f handover=true`). This is allowed with
`GITHUB_TOKEN`: GitHub's docs (Automatic token authentication) say events triggered by
it do not create new runs, except that "workflow_dispatch and repository_dispatch events
always create workflow runs"; it needs `actions: write`. The new run's loop waits in the
concurrency group `radar-live` and starts as soon as the old one ends. An hourly schedule
(`7 * * * *`) is the safety net: its first job ("Live loop running?") lists the
workflow's active runs and starts a loop only if none has a "Live loop" job queued or
running, so it exits within seconds while a loop runs (and the concurrency group would
queue a second one anyway). A failed round is logged and the next one tries again.

**Expected delay** for a visitor: ČHMÚ has a composite within a minute of its time; the
loop fetches at +1 min and has pushed by about +1.5 min (a round takes 10–20 s; the first
round of a new loop up to ~2 min); raw.githubusercontent.com caches for up to 5 minutes
(`Cache-Control: max-age=300`). So a frame is visible **2–7 minutes after its time**
(up to 12 if ČHMÚ misses the minute), against up to 2 hours with the old `*/10`
schedule, which GitHub ran only every ~2 hours (2026-10-15: 15:38, 17:19, 19:24 UTC).
A handover loses no round; if a run is lost, the hourly schedule starts a new loop within
the hour. Satellite images appear on ČHMÚ ~15 minutes after the scan start, so they lag
15–20 minutes; MERGE comes 20–90 minutes after its hour.

Size of the branch with 24 hours: radar 1–3 MB, echo tops 0.5–1.5 MB, motion 0.6 MB,
cells < 0.1 MB, satellite 3–6 MB, nowcast 50 KB: about 6–12 MB. A 3-hour folder with
8 hours of satellite measured on the evening of 2026-10-15: 1.8 MB. The loop uses about
23 runner hours a day (free for public repositories).

Why this design:

- GitHub Pages cannot be redeployed every few minutes (deployments are slow, rate
  limited and would rebuild the whole site); the branch decouples the radar from it.
- jsDelivr (`cdn.jsdelivr.net/gh/…@radar-live`) also sends CORS headers but caches a
  branch for 12 hours (`s-maxage=43200`, checked), far too long for `index.json`.
- Release assets cannot be read by a browser: their download host sends no CORS
  headers (checked 2026-10-15).
- One force-pushed commit keeps the branch small; the replaced commits are garbage
  collected by GitHub.
- Trade-offs: raw.githubusercontent.com is not meant as a CDN and may rate-limit a
  very popular page (each visitor loads ~40 frames for 3 hours); GitHub disables
  schedules in repositories without activity for 60 days (the daily commits prevent
  that; the dispatch chain does not depend on schedules). If either becomes a problem,
  the frames can move to any static host with CORS without changing the page
  (`VITE_RADAR_LIVE`).

**Archived days**: `web-YYYYMMDD.tar` (made by `mvd archive-radar` once the day is
complete, ~3 hours after midnight) holds the same layout for the whole day, without the
nowcast. Measured for 2026-10-10 (a wet day): maxz 8.0 MB, merge1h 1.2, echotop 4.5,
motion 0.6, cells 0.07, satellite 5.6 (vis-ir 2.9, night-M 2.2, wv062 0.5): 21 MB.
`mvd archive-radar --day D --products maxz-png_masked --redo web --out-dir …` (or
`--github-release`) remakes a day's set while ČHMÚ still has the day. Days archived
before this change have only `maxz` and `merge1h`.

The Pages workflow unpacks the `web-YYYYMMDD.tar` of the last 60 days into
`radar/days/YYYYMMDD/` and lists them in `radar/days.json`. To stay well under the 1 GB
Pages limit it keeps the satellite images only for the **last 7 days** and the echo tops
for the **last 14** (deleting the files and emptying their lists in `index.json`), and
if the site would still exceed 900 MB it leaves out the oldest days, with a warning.
Budget: station pages and scores ~160 MB (`site-data.zip` 123 MB and `station-data.zip`
31 MB unpacked, 2026-10-15); 60 radar days of `maxz` and `merge1h` at 2–10 MB
(the archived days so far: 2.2–9.6, mean 4.8) plus 0.65 MB of motion and cells:
170–640 MB, typically ~330 MB; echo tops 14 × 1–4.5 MB = 15–65 MB; satellite
7 × ~5.6 MB = 40 MB. Total typically **~0.55 GB**, up to ~0.9 GB in a very wet spell,
where the guard trims the oldest days. A day appears there at the first Pages deployment
after it was archived (usually the next morning); until then the live branch covers the
last 24 hours. Older days stay in the releases.

### How the radar page uses the frames

The page decodes every PNG in the browser (canvas, then each pixel's colour → ČHMÚ class
4 … 60 dBZ, "aloft" for the lighter colours of `png_masked`, or no coverage) and draws
the classes itself (`web/src/radar-palette.js`), so it can hide weaker echoes ("Show
from": all / light / moderate / heavy / hail, with the lower bounds from the labels of
`scales.maxz` in `index.json`, else 20 / 28 / 40 / 56 dBZ; echoes aloft are hidden by
every setting but "all"). Between two frames it draws one image a minute
(`web/src/radar-motion.js`): each pixel takes the earlier frame at x − τ·d and the
later one at x + (1 − τ)·d, d being `motion/<later stamp>.json` (grid pixels per
`dt_s`, u east, v down the rows) scaled to the interval, and the classes blended by τ;
the nowcast uses the newest motion file; without one it cross-fades. Rain at a place
reads the class of its grid cell in the frames of the last 2 hours and the nowcast.
Every newer key of `index.json` (`echotop`, `motion`, `cells`, `satellite`, `scales`) is
optional: archived days without them show the radar and the 1-hour sums as before.

## Satellite images

ČHMÚ publishes Meteosat images at
`opendata.chmi.cz/meteorology/weather/satellite/geo/<product>/`, a JPG every 15 minutes
per product and region: `YYYYMMDDhhmm_geo_<product>_<region>.jpg`, the time being the
start of the scan (it is printed in the image's top right corner); a file appears about
15 minutes later. Regions `cz`, `ce` (Central Europe) and `eu`; products `24M`,
`airmass`, `ir108`, `ir108BT`, `night-M`, `vis-ir`, `wv062` (we use `vis-ir`, the
daytime visible/infrared composite; `night-M`, the night microphysics RGB; `wv062`,
water vapour 6.2 µm, greyscale, day and night). On 2026-10-15 the files went back to
2026-10-07 04:45, **about 8.5 days**. No description or metadata file exists on the
server, and the images are not in the National Open Data Catalogue. Licence: CC BY 4.0
from both EUMETSAT and ČHMÚ ([licensing](licensing.md)).

**Projection of `ce`** (not documented; determined by us): all images are 1160 × 800.
Fitting the Natural Earth 1:50m coastlines to the land/sea edge of a cloud-free composite
(per pixel the second-darkest of 24 noon `vis-ir` images, 2026-10-08 … 15) with several
projections gave a clear answer: **Web Mercator** (spherical, EPSG:3857) with square
pixels fits with a mean distance of 1.9 pixels; plate carrée (3.6), Lambert conformal and
azimuthal, polar stereographic and the geostationary view (7.5–9.3) do not, and an
ellipsoidal Mercator needs non-square pixels. Fitted: west edge −190 501 m, north edge
7 690 826 m, pixel 3114.2 m, i.e. **W −1.7113°, S 42.2566°, E 30.7397°, N 56.6594°**
(centred on 14.51° E; pixels of 2.0 km at 50° N). Lake Constance, the northern Adriatic
and the Baltic coast lie within about a pixel (3 km) of the Natural Earth outlines (Swiss
lakes were under fog in most composites). The scale is equally good between 3111 and
3115 m, so the edges far from Czechia may be off by 1–2 pixels; around Czechia the error
is under a pixel. `cz` is a ~2.5× zoom (not used), `eu` is not Mercator (not used).

### What `mvd archive-satellite` stores

Once a UTC day is complete (1 hour after midnight), every product and region of that day
becomes one uncompressed tar of the JPGs as published, an asset of the monthly release
`satellite-YYYY-MM`: `vis-ir-ce-20261014.tar`, `night-M-eu-20261014.tar`, … (label
`files=N`). Resumable like the radar archive: assets already there are skipped, a failed
download leaves the asset out for the next run. `--products`, `--regions`, `--day`,
`--out-dir DIR` (same layout locally); `mvd mirror-radar --satellite` (or
`--only-satellite`) copies these releases too. The Radar workflow's archive job runs it
every 6 hours for all products and regions.

**Size** (from the server listing, 2026-10-08 … 14, per day): `ce` vis-ir 4.5 MB (49
files), night-M 4.2 (45), wv062 1.9 (94); `cz` 3.6, 3.7, 1.3; `eu` 5.4, 3.8, 3.1. All:
**31.5 MB a day, ~11.5 GB a year** (`--regions ce`: 10.6 MB a day, ~3.9 GB a year).
In summer `vis-ir` has more files and `night-M` fewer; the total stays similar.

## Single runs (`mvd fetch-runs`)

A **single run** is one model run as it was issued, which the Previous Runs API (D+N,
above) cannot give: there each hour mixes runs. The stored runs (every 00, 06, 12 and
18 UTC run of the 19 models at the ~100 stations below, leads 1–120 h) feed the error by
lead hour (`mvd leads`), the farmers' events (`mvd farm`), the outlook's gusts and the D+N
of the most recent days, before the backfill reaches them
([Fresh D+N](#fresh-dn-from-the-single-runs)).

**Sources, since 2026-10-17** (column `source`):

1. **Open-Meteo's open-data bucket on AWS** (`bucket`; [below](#single-runs-from-the-bucket)):
   every run, no API calls. The bucket keeps per-run files for about three months, so
   each scheduled run also stores any run of the last 90 days not stored yet, and the
   history from 2026-07-15 came from a one-off harvest of it
   ([import](#history-from-the-bucket-one-off-import)).
2. **Open-Meteo's Single Runs API** (`api`; [below](#single-runs-api)): only for a
   model-run the bucket does not have complete once it is 24 h old (the fallback, ≤ 400
   calls a day), and for the history older than the bucket's window, back to
   2026-06-23 (with what the D+N backfill leaves of the shared budget).

Before 2026-10-17 the newest runs came from the API alone (3,400 calls a day); rows
stored then have no `source` (null) and every hour filled
([rows](#fetching-and-storage)).

### Single runs from the bucket

`meteoverdict.bucket`, checked 2026-10-16/17:

- **Layout:** `s3://openmeteo` (AWS Registry of Open Data, us-west-2), read anonymously
  over HTTPS at `https://openmeteo.s3.amazonaws.com/`:
  `data_run/<model>/<YYYY>/<MM>/<DD>/<HHMM>Z/<variable>.om` plus `meta.json`
  (`valid_times`, the grid's `crs_wkt` with its `BBOX`), and the model surface height in
  `data/<model>/static/HSURF.om`. One `.om` file per run and variable holds all lead
  times, chunked as strips of grid points × all times, so one station is a few range
  requests of ~1 kB (`omfiles`, through `bucket.Bucket`, which retries dropped
  connections, timeouts, 429 and 5xx up to 6 times; S3 answers 403 for a missing key).
- **Retention:** about three months (oldest runs on 2026-10-16: 2026-07-14 18 UTC for
  IFS, IFS 0.25°, UKMO, JMA and CMA, 2026-07-15 00 UTC for the rest; older ones are
  deleted daily). So the bucket's window is the last 90 days (`runs.BUCKET_DAYS`).
- **Model names:** GFS from `ncep_gfs013` (gusts from `ncep_gfs025`), GEM Global from
  `cmc_gem_gdps_15km` (00 and 12 UTC, only from 2026-08-18 12 UTC), ARPEGE World from
  `meteofrance_arpege_world025`; the others under their own id (`bucket.SOURCES`).
  Wind speed is the native `wind_speed_10m` for ALADIN (both), AROME AT, UKMO, KNMI, DMI
  and GEM, else `hypot(u, v)`. AIFS, JMA GSM and AIGFS have no gusts there (null, as for
  AIFS in the API).
- **Grid cell:** the nearest one, as the API (checked against it run by run: identical
  for ICON-D2, ALADIN CE and ARPEGE Europe at every station), from `data/bucket-cells.csv`
  (committed: per bucket model and station the array index, the cell's position,
  distance and model surface height; rebuilt with `mvd bucket-cells` when the stations
  or a grid change; a run on another grid is not read but left to the API). Regular
  lat/lon grids, Lambert conformal (ALADIN CE, DMI: projected with pyproj) and rotated
  (KNMI) grids from the WKT; IFS HRES's O1280 reduced Gaussian grid from its Gaussian
  latitudes (4i + 16 points on ring i). Where the nearest cell is water (surface height
  −999: DMI at the Rozkoš reservoir) the nearest land cell of the 3 × 3 around it, as
  the API does.
- **Same conventions as the API:** temperature corrected from the cell's surface height
  to the station's elevation with 0.65 K per 100 m (AIFS with the IFS 0.25° height, AIGFS
  with the GFS 0.25° height, as the API; ICON-D2 has no data at one station in the far
  east); precipitation below 0 (packing artefacts, e.g. JMA −0.1) as 0. **Time
  axis:** files of totals or maxima over the preceding step (precipitation of every
  model but ALADIN and AROME AT; the gusts of ICON, ICON-EU, ICON-D2, IFS, IFS 0.25°,
  both ARPEGEs and CMA) leave out the run's first step and start at the second valid
  time (`bucket.file_times`; e.g. IFS 0.25° precipitation: 84 steps for 85 times, its
  first value = the 0–3 h total).
- **Native steps, nothing invented:** a run's rows are its own output times (ICON-EU and
  ICON hourly to 78 h then 3-hourly, IFS HRES hourly to 90 h then 3-hourly, UKMO 54 h,
  ARPEGE World 48 h, GEM 84 h, GFS 120 h; IFS 0.25° and CMA 3-hourly, AIFS, AIGFS and
  JMA 6-hourly; `step_hours`/`coarser_after_h` in models.yaml, checked to match the
  bucket at every lead for every model). Precipitation at a native time is the total
  since the previous one. The API interpolates the hours in between (precipitation
  spread evenly); those hours are not stored (see [rows](#fetching-and-storage)).
- **Complete or not at all** (`bucket.read_run`): a model-run is stored only when its
  `meta.json` is there, its `valid_times` reach every native lead up to the model's usual
  horizon (ALADIN 72, ICON-D2 48, DMI 59, AROME AT and KNMI 60, ARPEGE 102, UKMO 06/18
  UTC 60, the rest 120 h; ECMWF first writes IFS to 72 h and the rest ~1–3 h later),
  every variable file is there with those time steps, every variable has values at
  half the stations or more, and no value is implausible (a file read while it is being
  replaced). Otherwise it is looked for again at the next schedule, and once it is 24 h
  old (`runs.BUCKET_FINAL_H`; the latest complete runs seen were 13.4 h old) it is
  recorded as missing in the bucket (`bucket_missing` in the state) and the API is
  asked for just that model-run. Seen 2026-07-15 to 10-16: 0–3 runs missing per model,
  and partly written runs (meta.json there, variables missing) for ARPEGE Europe and
  World and KNMI on 2026-09-02 18 and 09-03 00 UTC, JMA 09-02 12 and 18 UTC, ICON-D2
  08-22 00 UTC (no v wind) and ICON 08-14 12 UTC (no gusts).
- **When:** the runs reach the bucket 2–10 h after their start (median: ICON-D2, KNMI,
  DMI ~2–3 h; ALADIN ~4 h; ICON, ARPEGE ~4 h; GFS, AIFS, GEM, CMA ~5–6 h; IFS ~7 h, UKMO
  ~8 h, JMA ~10 h). Each schedule stores whatever is complete (runs at least 1 h old),
  model by model.
- **Cost:** one run of all 19 models at 100 stations is ~17,000 range requests and
  ~7 MB, ~45 s with 4 models and 48 requests in parallel (2.8 min one model at a time,
  measured from Prague; GitHub's runners are closer to us-west-2). Free: anonymous
  access, no quota.
- **Validation** (2026-10-15 00 UTC, all 19 models, the bucket's rows against the API's
  stored ones at the same native hours, 125,452 values, 2,494 with rain; `eq` = share
  within 0.11, the API rounds to 0.1):

  | Model | t2m MAE | t2m eq | precip MAE | wind eq | gust eq |
  |---|---|---|---|---|---|
  | ALADIN CZ 1 km / CE 2.3 km | 0.033 / 0.030 | 98.6 / 99.2 % | 0.000 | 98.6 / 99.3 % | 98.5 / 99.2 % |
  | ICON-D2 / ICON-EU / ICON | 0.044 / 0.042 / 0.036 | 97.4 / 98.2 / 99.1 % | 0.000 | 97.6–99.2 % | 97.2–99.1 % |
  | AROME AT / KNMI / DMI | 0.043 / 0.033 / 0.054 | 97.3 / 99.1 / 95.9 % | 0.000 | 97.5 / 99.1 / 96.3 % | 97.3 / 99.1 / 95.5 % |
  | IFS HRES | **0.233** | **47.4 %** | 0.000 | 87.6 % | 87.1 % |
  | IFS 0.25°, GFS, GEM, ARPEGE ×2, CMA, UKMO | 0.023–0.034 | 99.1–100 % | 0.000–0.013 | 99.2–100 % | 99.1–100 % |
  | AIFS, JMA, AIGFS (6-hourly) | 0.024–0.025 | 100 % | 0.014–0.022 | 100 % | – |

  The remaining differences: on the high-resolution grids a few stations where the
  API's cell differs by one (at a cell edge); **IFS HRES**, where on the O1280 grid the
  API takes a neighbouring cell for ~12 % of the stations and corrects the temperature
  only at some, a rule not reproduced (accepted: the bucket's value is the nearest cell
  with the usual correction); the 6-hourly models' precipitation, which the API rounds
  after spreading. Scores from either source agree within the API–bucket difference
  (temperature MAE +0.000…+0.009 for most models, +0.03–0.04 for IFS HRES on 4 days).
  A one-off harvest of 2026-07-15 to 10-16 read the same way agrees row for row with
  live reads (after the import's corrections below).

### Single runs API

Open-Meteo's **Single Runs API**, the fallback and the source of the history older than
the bucket's window. Checked live on 2026-10-13 without an API key (free tier):

- Endpoint `https://single-runs-api.open-meteo.com/v1/forecast`, the Forecast API's
  parameters plus `run=YYYY-MM-DDTHH:MM` (the run's **start**, UTC). Several models per
  request (`models=a,b,c`, columns `<variable>_<model>`) and several locations
  (comma-separated `latitude`, `longitude`, `elevation`; a JSON list, `location_id` on
  all but the first) work as in the other APIs, and `elevation` is used for the
  elevation correction as there.
- The answer starts at the run's start (lead 0); `forecast_hours=121` gives leads 0 to
  120 (`forecast_days=N` gives N × 24 hours from the run's start). Lead 0 is not stored.
- If **any** requested model does not have that run, the whole request fails: HTTP 400
  `{"error":true,"reason":"The requested model run is not available. Model: X, run: …"}`.
  X is Open-Meteo's internal name, which can differ from the id we ask for:
  `dwd_icon_d2_native`, `dwd_icon_eu_native`, `ncep_gfs013` (for `ncep_gfs_global`),
  `cmc_gem_gdps_15km` (for `gem_global`), `meteofrance_arpege_world025` (for
  `meteofrance_arpege_world`; checked 2026-10-15); the others report their own id
  (`dwd_icon`, `ncep_aigfs025`, `jma_gsm`, `cma_grapes_global`, KNMI, DMI).
  `mvd fetch-runs` drops X and asks again for the rest.
- A model without data at one location (ICON-D2 in the far east) is **left out of that
  location's answer** instead of failing the request; if only one model is left, the
  columns lose their model suffix (`temperature_2m`). A one-model request fails there
  with "No data is available for this location", as in the Previous Runs API.
- Every model has every 00, 06, 12 and 18 UTC run, except **GEM Global: 00 and 12 UTC
  only** (`run_hours` in models.yaml, so the 06 and 18 UTC runs do not ask for it).
  Horizons seen (temperature, lead hours with a value, runs of 2026-10-12 and
  2026-10-14): ALADIN (both) 72; ICON-D2 48; DMI 59, KNMI 60; GeoSphere AROME 60; ARPEGE
  Europe and World 102; ICON-EU, ICON global, IFS HRES, IFS 0.25°, AIFS, GFS, AIGFS, GEM
  Global, JMA GSM and CMA GRAPES 120 (asked for); UK Met Office 120 from 00 and 12 UTC,
  60 from 06 and 18 UTC. The API fills every hour: between a model's native steps the
  values are interpolated, as in the Previous Runs API (AIGFS has no values for leads
  1–5); its rows are stored at the native steps only ([rows](#fetching-and-storage)).
- **Archive start:** the 2026-04-02 00 UTC runs are there for every model except ALADIN,
  GEM Global and JMA GSM, the 2026-04-01 12 UTC runs only for IFS HRES (the docs say IFS
  HRES from 2024-03-14). ALADIN (both domains) from the **2026-06-23 00 UTC** run
  (2026-06-22 18 UTC is missing), JMA GSM from 2026-05-12 12 UTC, GEM Global from
  2026-05-28 00 UTC (`runs_from` in models.yaml, measured 2026-10-15 by bisection, so a
  gap just before could hide an earlier start). Gaps after that are possible (KNMI misses
  2026-09-01 12 UTC, CMA GRAPES 2026-10-01 00 UTC).
- **Delivery:** the API was never seen ahead of the bucket (2026-10-16 19:09 UTC: the
  12 UTC runs of IFS 0.25°, JMA, UKMO and CMA missing in both), so a young run missing in
  the bucket is not asked from the API; only a model-run still missing there at 24 h.
- **Cost** (Open-Meteo's formula: locations × max(1, variables × models / 10 ×
  max(1, days / 14))): 121 hours count as 6 days, under 14, so the whole 5 days cost the
  same as one day: variables × models / 10 per station, at least 1. With 4 variables
  (temperature, precipitation, wind and gusts) **760 calls a run of all 19 models** at
  the 100 stations (720 at 06 and 18 UTC), but **100 for one or two models** (measured
  live on 2026-10-15: 28.5 calls for 5 stations × 19 models × 3 variables). Requests
  that fail count too (we do not know whether Open-Meteo counts them). One request stays
  at or below 500 calls (`runs.MAX_REQUEST`, Open-Meteo allows 600 a minute): equal
  requests of at most 100 stations.

### History from the bucket (one-off import)

The bucket's three months were harvested once on 2026-10-16 (runs 2026-07-14 18 UTC to
2026-10-16 12 UTC, ~6,900 model-runs, no API calls; local tool outside the repository,
the same reading as `meteoverdict.bucket`) and added to the releases with
`mvd import-runs runs-2026-07.parquet … --github-release` (2026-10-17). The import:

- converts to the stored format (leads 1–120, `source` = `bucket`, precipitation below
  0 as 0);
- **corrects the harvest's precipitation**, which it had put one native step early for
  every model but ALADIN (both) and AROME AT (their files keep the first step; the
  others' start at the second valid time, `bucket.file_times`; found when checking the
  harvest against the API on rainy hours: ICON-EU MAE 0.35 mm on the same lead, 0.00
  one step later). The gusts were already right;
- reads again from the bucket the stations whose cell the harvest chose differently
  from `bucket-cells.csv` (DMI at Rozkoš, a water cell: the harvest's temperature was
  8 °C off there; dropped where the bucket no longer has the run);
- leaves out the model-runs that are not complete by the rule above (11, e.g. the
  partly written runs of 2026-09-02/03) and records them, and every model-run of the
  harvested runs it lacks (GEM Global before 2026-08-18, the bucket's missing runs), as
  missing in the bucket, so the API is asked for them;
- **prefers the bucket for all models**: a model-run of the harvest replaces every
  stored row of that model-run (the API's runs of 2026-10-13 to 10-16, stored hourly),
  so a run's rows always come from one source. The API's runs stored after the harvest
  stay as they were.

### The station subset

Asking every run at all ~500 stations would cost about 1,650 calls a run, 6,600 a day.
We use about 100 stations instead (`src/meteoverdict/data/run-stations.csv`, committed,
so the set does not change from run to run). The rule (`runs.select_stations`,
regenerated with `uv run scripts/build_run_stations.py`):

1. **One per okres** (all 77): among the okres's active stations, those with the most of
   our three elements at 10 minutes in ČHMÚ's `meta2` (`T`, `F`, `SRA10M`), and of
   these the one closest to the okres's forecast point (the same point as the outlook).
   Blansko has only precipitation stations, so its station verifies precipitation only.
2. **Mountains:** every other station with all three elements above 800 m (13).
3. **Spread** up to 100: repeatedly the full station farthest from all chosen ones,
   counting 100 m of height difference as 10 km (10 stations).

Ties go to the lower WIGOS id. Result on 2026-10-13: 100 stations in all 77 okresy,
47 lowland, 39 upland and 14 mountain, 99 with all three elements. The CSV records why
each station is in (`reason`: `okres`, `mountain`, `spread`).

### Fetching and storage

`mvd fetch-runs [--source bucket|api|all] [--mode recent|history|all]
[--run YYYY-MM-DDTHH …] [--max-calls N] [--bucket-minutes M] [--shared-calls N
[--shared-from A] [--shared-to B] [--backfill-from 2024-01-01]] [--history-from D]
[--github-release] [--dry-run]`:

- **1. The bucket** (`--source bucket` or `all`): every run of the last 90 days at least
  1 h old, newest first, every model not stored yet and not recorded as missing in the
  bucket (`bucket.collect`): 4 models at a time, a run's complete models are written to
  its month file at once; stops after `--bucket-minutes` (40) or when the bucket keeps
  failing (20 model-runs in a row after their retries) and continues next time. Month
  files and state go up once at the end (the bucket costs nothing, so a run cut short
  is simply read again).
- **2. The API** (`--source api` or `all`), newest first, within `--max-calls`: the
  model-runs recorded as missing in the bucket (`--mode recent`), and every model-run
  of the runs older than the bucket's window back to `--history-from` (default
  **2026-06-23 00 UTC**, `runs.HISTORY_FROM`; `--mode history`). All models still to
  fetch of a run go in one request; when the budget left does not cover them all, as
  many as it covers (`runs.affordable`: 100 calls cover two). Retries, the daily limit
  and persistent failures behave as in `mvd fetch-fc` (`forecasts.request`); a run
  stopped by the budget or by Open-Meteo is not kept and is asked again next time. A
  model the API does not have is recorded as missing for good (a gap). `--run` asks
  for the given runs only (bucket first, then the API for what it lacks).
- **Why the API history stops at 2026-06-23:** it is the first run with ALADIN (both
  domains) in the archive. The runs from 2026-04-02 to 2026-06-22 lack ALADIN (and
  before mid/late May JMA GSM and GEM Global), so on the fair common set (every model
  verified on the same runs, stations and hours) they add nothing for ALADIN; with
  ALADIN missing from most runs of a period, it would even be left out by the 80 %
  rule. They would cost ~216,000 calls (328 runs × ~660) for hours that `mvd leads` and
  `mvd farm` (last 90 days) never read. Decided 2026-10-17: not fetched by default;
  `--history-from 2026-04-02` can add them once the D+N backfill is complete (~29 more
  days of the share).
- **Rows:** `data/runs/YYYY-MM.parquet` by the month of the run's start, one row per
  `run`, `model`, `station_id`, `lead_h` (1–120) **at the model's native output steps**,
  with `valid_time` (= run + lead), `temperature_2m` (°C), `precipitation` (mm since the
  previous native step: the hour for hourly output, 3 or 6 hours for the coarser steps),
  `wind_speed_10m` (m/s), `wind_gusts_10m` (m/s, Open-Meteo's maximum of the preceding
  hour; null for AIFS, JMA GSM and AIGFS, and in API runs stored before 2026-10-15) and
  `source` (`bucket` or `api`), sorted by run. A model-run is written whole and replaces
  any stored rows of it (`partitions.write_monthly(..., replace=["run", "model"])`), so
  a run's rows always come from one source. The API's answers are converted before
  they are stored (`runs.native`: only the native hours, precipitation summed over the
  native step, e.g. the three hourly values of IFS 0.25°, which Open-Meteo spreads
  evenly). **Rows stored before 2026-10-17** (the API, every hour, no `source`) are
  converted the same way where they are read (`runs.native` in `mvd farm`;
  `fresh.spread` keeps them hourly for the D+N). `mvd leads` scores native hours only
  either way. About 125,000 rows a run, ~45 MB a month.
- **State:** `data/runs-state.json`: per run (`YYYYMMDDHH`) the models stored
  (`fetched`), the models the API does not have (`missing`, gaps for good) and the
  models missing in the bucket (`bucket_missing`, asked from the API).
- **Release storage** (`--github-release`): the month files as `runs-YYYY-MM.parquet` in
  the releases `runs-YYYY-MM` (a family of their own, CC BY-SA 4.0 like the other data
  files, with release notes crediting Open-Meteo, CC BY 4.0, and the source services),
  the state as `runs-state.json` in the release `runs-state`; labels hold the SHA-256 so
  unchanged files are skipped. A month file is pulled before runs are added to it. Only
  `runs.yml` writes these releases, so it has its own concurrency group; `mvd leads` in
  the daily workflow only reads them.
- **Schedule** (`.github/workflows/runs.yml`): at 04:20, 10:20, 16:20 and 22:20 UTC (and
  13:20 for the shared budget): the bucket, then the API with 100 calls (the bucket's
  gaps), at 10:20 and 13:20 also with what the D+N backfill leaves of the shared budget
  (below). A run typically takes 2–5 minutes.

### Open-Meteo budget

All workflows share the free tier's 10,000 weighted calls a day, 5,000 an hour and
300,000 a month (per IP address; GitHub's runners share addresses, so a run can still
meet the daily limit early and then stops cleanly). Each workflow has its own call
budget (`--max-calls`); `forecasts.Budget` also paces one run below 550 a minute and
4,800 an hour, and no single request weighs more than 500 (`runs.MAX_REQUEST`,
`outlook.MAX_REQUEST`).

**Priorities** (decided 2026-10-15, with all 19 models: "the backfill has the lowest
priority; fill it from the date closest to today into the past"; since 2026-10-17 the
newest single runs come from the bucket and their API calls go to the backfill):

1. **Outlook** (user-facing, `outlook.yml`): only the models with weights are asked,
   77 okresy × 5 variables × models / 10: ~732 calls a run with all 19 (refused above
   800), twice a day; 1,700 a day budgeted with retries.
2. **The bucket's gaps** (`runs.yml`, 100 at 04:20, 10:20, 16:20 and 22:20, ≤ 400 a
   day): the single runs the bucket lacks once 24 h old, newest first. Usually nothing
   (a run or two a week); the rest of the time this goes to the history below.
3. **The current D+N windows** (`backfill.yml` at 02:41): the complete 14-day windows
   ending in the last 90 days, which the 90-day ranking and the combination weights
   read (`backfill.CURRENT_DAYS`). Usually only the newest one is pending; after a model
   is added, all of them are for that model. A window of all 19 models costs **~10,070
   calls** at the ~500 stations with the shared requests of models with the same lead
   days (~11,970 one model per request; measured live: 7.5 calls for 5 stations × 14
   days of ICON global, 1.5 a station), plus ~3,860 (~5,360) for the rain gauges'
   28-day window with every other window.
3b. **The priority D+N windows** (since 2026-10-16, `--priority-from 2025-10-01`): one
   full year back, at the ~100 stations of the single runs only, ~2,000 calls a window,
   ~40,500 for all 21 (see [backfill](#backfill-mvd-backfill)).
4. **History, newest first:** (a) the single runs' API history: the runs older than the
   bucket's window back to 2026-06-23 (88 runs of 2026-06-23 to 07-14, ~65,000 calls),
   GEM Global before 2026-08-18 (~70 runs, ~6,900) and the bucket's gaps beyond what (2)
   covers; it extends the hourly, run-by-run record over the whole ALADIN period and is
   cheap (~10 days of the share), so it comes before (b) the D+N windows back to
   2024-01-01 and the other stations of the priority windows (~570,000 calls). The
   single runs before 2026-06-23 are not fetched (see
   [fetching](#fetching-and-storage)).

The recent days need no calls of their own: their D+N is rebuilt from the single runs
([Fresh D+N](#fresh-dn-from-the-single-runs)).

Priorities 3 and 4 share **7,400 calls a day** (before 2026-10-17: 4,500; the newest
single runs then cost 3,400 a day):

- The backfill (02:41, `--max-calls 7400`, ~1.5 h at its pace of 4,800 an hour) spends
  them first on its current windows, newest first, then on its priority windows. It
  fetches older windows only with `--older-windows after-runs-history`, i.e. once the
  single runs' API work is done (at most 4 runs left, `runs.history_done`, from the
  state in the release `runs-state`; held back if that cannot be read). It records the
  calls of the day in its state (`calls_on`, `calls_used`).
- `runs.yml` at 10:20 takes the part 0–3,700 and at 13:20 the part 3,700–7,400 of what
  the backfill left (`mvd fetch-runs --shared-calls 7400 --shared-from A --shared-to B`,
  `backfill.share_left`, from the backfill's state in the release `data-state`):
  - a current or priority window still pending (the backfill has not finished it, or
    not run yet; `--backfill-priority-from 2025-10-01`): nothing;
  - a current window becomes due tomorrow (one ending today): nothing, so this history
    and the backfill's next big day are 24 hours apart by the schedules (safe even if
    Open-Meteo counted a rolling 24 hours; scheduled runs can start up to ~5 hours late,
    see below);
  - the backfill called Open-Meteo today: 7,400 minus what it used (nothing if the
    amount is not recorded);
  - otherwise (the current windows are done; older windows do not count): all 7,400;
  - if the state cannot be downloaded or read: nothing.
- Once the single runs' API work is done, the backfill spends the whole share on its
  current and then its older windows every day, so nothing is left for `runs.yml`.

Both job summaries say what was decided and why, e.g. "3800 calls (100 normal + 3700
shared; 7400 of 7400 left, this run takes 0-3700: the backfill's current windows (last
90 days) are done)", "100 calls (normal; no shared calls: 0 of 7400 left, this run takes
0-3700; 1 current backfill window pending (newest 2026-10-05..2026-10-18))", and
"Priority: the 6 current windows (last 90 days) first; older windows held back (63 not
looked at): single-runs history first: 92 runs since 2026-06-23 pending".

| Per day (caps) | Outlook | Single runs (API fallback) | Shared (backfill + API history) | Total |
|---|---|---|---|---|
| Before 2026-10-17 | ≤ 1,600 | 3,400 (newest runs) | 4,500 | ≤ 9,500 |
| **Since 2026-10-17** | ≤ 1,700 | **≤ 400** (bucket gaps) | **7,400** | **≤ 9,500** |
| In 31 days | ≤ 52,700 | ≤ 12,400 | 229,400 | **≤ 294,500** |

No day exceeds 9,500 and no 31-day month 294,500, whoever spends the share, as long as
the runs start on time; a late 22:20 single runs schedule slipping into the next UTC day
adds at most 100 there (9,600). Hours: the backfill's ≤ 4,800 an hour (02:41), 10:20
≤ 100 + 3,700, 13:20 ≤ 3,700, the outlook ≤ 800 at 05:52 and 17:52, the other single
runs ≤ 100 each. `tests/test_budget.py` checks these sums against the workflows.

**The times above are when the runs are scheduled, not when they start.** GitHub starts
scheduled workflows **up to ~5 hours late** (on 2026-10-15 every scheduled run started
2.5–5 h late, e.g. the backfill of 02:41 at 07:43, the outlook of 05:52 at 10:21, the
single runs of 04:20 at 09:11) and sometimes skips a slot altogether (the 3-hourly
ALADIN archive ran 4 of 8 times that day). So the budget assumes:

- **Runs may overlap in one clock hour.** The backfill may still run (~1.5 h for its
  7,400) when a late outlook or the 10:20 single runs start. `forecasts.Budget` paces
  each run below 4,800 an hour, but two runs in the same hour can together pass
  Open-Meteo's 5,000; Open-Meteo then answers 429, which the runs retry after a pause
  (and stop cleanly on the daily limit, continuing next time).
- **A run can slip into the next UTC day** (the single runs of 22:20 starting after
  00:00): only the 100 fallback calls move, inside the 500-call margin below 10,000;
  the outlook (17:52) and the shared parts (10:20, 13:20) cannot cross midnight even 5 h
  late.
- **The share's 24-hour gap is nominal:** "the backfill and its next big day are 24
  hours apart" holds for the schedules; with the delays the real gap can be ~19–29 h.
- **The single runs no longer lag:** the bucket is read at every schedule, model by
  model as runs arrive (2–10 h after their start), so a run is stored at the first
  schedule after it is complete there, also when a schedule is late.
- `mvd outlook` prints the Open-Meteo calls it used (retries included) to the log and the
  job summary, so a day's total can be added up from the job summaries.

**How long the histories take** (simulated day by day from the live states of
2026-10-17, 7,400 shared calls a day plus the 400 fallback, a new window every 14 days,
costs from `forecasts.estimate_calls` and `runs.run_cost`; scheduled runs start late or
are skipped sometimes, so take these dates as a few days optimistic):

- **Current and priority D+N windows** (the 6 current windows for all 19 models with
  their gauges, then one year back at the ~100 stations): done around **2026-10-30**
  (with the old 4,500: 2026-11-08). Every new window afterwards costs ~10,100 (+ ~3,900
  gauges every other one), about two days of the share every 14 days.
- **(a) Single runs' API history** (~75,000 calls: 2026-06-23 to 07-14, GEM Global
  before 2026-08-18, the bucket's gaps): done around **2026-11-10** (before: all of
  2026-06-23 to now through the API, ~333,000 calls, early February 2027).
- **(b) D+N backfill back to 2024-01-01** (per model from its archive start: ALADIN
  2026-06-24, AIGFS 2026-01-22, AIFS 2025-02-18, IFS HRES 2025-10-01, GeoSphere
  2026-03-26, UKMO 2024-08-08, KNMI/DMI 2024-06-29, the others 2024-01-19 or earlier) and
  the other ~400 stations of the priority windows, with their gauges: ~570,000 calls,
  complete around **2027-02-05** (before: July 2027).

Until then the "all time" and season windows cover only what has been fetched (and,
by the fair comparison, only the days every model of a region has); the 90-day ranking
is complete for all 19 models after the first ~2 weeks.

## Error by lead hour (`mvd leads`)

Run-based verification (see [methodology](methodology.md#run-based-verification-by-lead-hour)
for what it means). `meteoverdict.leads` has two parts.

### Every model, from the single runs (`leads.json`)

1. Reads the single runs started in the last `--runs-days` days (default 90) from
   `data/runs/` (with `--github-release` it first downloads changed months from the
   releases `runs-YYYY-MM`, and the observation months from `data-YYYY-MM`).
2. Per model, run, station and lead hour 1–120: temperature and wind as given (instant
   values at `valid_time`), precipitation as given (mm in the hour ending at
   `valid_time`, no differencing). Only **native output hours** are scored: AIFS every
   6 h, IFS 0.25° every 3 h, ICON-EU after 78 h, IFS HRES after 90 h and UK Met Office
   after 54 h every 3 h (`step_hours`, `coarser_after_h` in models.yaml); hourly
   precipitation only where the output is hourly. The runs are stored at native steps
   (from the bucket since 2026-10-17; [rows](#fetching-and-storage)), so these are
   exactly the hours there are; the API's runs stored hourly before have their
   interpolated hours too, which are skipped the same way.
3. **Fair set.** A model's horizon per run hour is the median over its runs of the last
   lead hour with a temperature. For each run hour (00, 06, 12, 18 UTC), lead hour and
   variable, the *required* models are those whose horizon reaches the lead with a
   native output hour; only the (run, station) pairs where every required model has a
   value (and the observation exists) are scored. For "all" run hours a model must reach
   the lead in every run hour (UK Met Office therefore ends at 60 h there, ARPEGE at
   102 h). So the set of models shrinks with the lead hour, and a model missing from a
   run takes that run out of the comparison at the leads it would reach. Only models
   with at least 80 % of the period's runs take part (`runs.coverage`, counted over
   the run hours the model has, so GEM Global without 06 and 18 UTC runs counts fully):
   a model whose single runs are fetched only since it was added would otherwise cut
   every model's runs to its few days (on 16 October 2026 the eight models added on 15
   October cut `leads.json` and `farm.json` to the four runs of that day, of twelve
   since 13 October). They are listed under `short_record` until they have them.
4. Sums errors per run hour stratum (`all`, `00`, `06`, `12`, `18`), model, variable
   and lead hour, 24 runs at a time (the sums are additive, so months of runs fit in
   memory), plus the 2×2 counts for ≥ 0.1 mm in the hour.

`site/data/leads.json` (with `--publish` also in the release `data-latest`, from where
the Pages build takes it):

| Key | Meaning |
|---|---|
| `generated`, `first_run`, `last_run` | UTC, `YYYY-MM-DDTHH:MMZ` |
| `source`, `about`, `fair_set` | where the data come from and the comparison rule |
| `stations` | stations with at least one pair |
| `models` | per model: `name`, `runs` and `pairs` used (run hour "all"), `horizon_h` per run hour, `publication_delay_h` (ALADIN only, from our archive; null for the others) |
| `short_record` | models left out for fewer than 80 % of the period's runs: `{model: {runs, of, coverage}}` |
| `variables`, `region`, `regions` | units; Czechia only (`cz`) |
| `columns`, `rows` | one row per `run_hour`, `model`, `variable`, `lead_h`: `runs`, `stations`, `n`, `mae`, `bias`, `rmse` (3 decimals), `a_0p1`, `b_0p1`, `c_0p1`, `d_0p1` (precipitation only) |

About 0.6 MB with two run hours (6,586 rows: "all", 00 and 12 UTC), about 1 MB with all
four (≈ 11,000 rows); no kraj file
(100 stations are only about 7 per kraj).

First real numbers, 2026-10-13: 5 runs (2026-04-15 12, 2026-07-15 00, 2026-10-10 00 and
12, 2026-10-13 00 UTC), observations of 99 stations from `recent/` (April, July) and
`now/` (2026-10-11 00 to 2026-10-13 13 UTC; `now/` no longer had 2026-10-10). Temperature
MAE in °C, all run hours (runs, pairs per model):

| Model | H+1 | H+6 | H+12 | H+24 | H+48 | H+72 |
|---|---|---|---|---|---|---|
| ALADIN CZ 1 km | 1.33 | 1.58 | 1.13 | 1.23 | 1.12 | 1.67 |
| ALADIN CE 2.3 km | 1.35 | 1.57 | 1.13 | 1.23 | 1.12 | 1.70 |
| ICON-D2 | 1.06 | 1.20 | 1.07 | 1.17 | 1.12 | – |
| GeoSphere AROME | 1.43 | 1.73 | 1.22 | 1.12 | 1.36 | – |
| ICON-EU | 1.41 | 1.54 | 1.20 | 1.18 | 1.20 | 1.59 |
| ECMWF IFS HRES | 1.48 | 1.57 | 1.10 | 1.18 | 1.22 | 1.40 |
| ECMWF IFS 0.25° | – | 1.73 | 1.14 | 1.21 | 1.23 | 1.45 |
| ECMWF AIFS | – | 1.51 | 1.15 | 1.17 | 1.25 | 1.37 |
| NOAA GFS | 2.28 | 2.47 | 1.26 | 1.49 | 1.31 | 1.79 |
| UK Met Office | 1.61 | 1.59 | 1.27 | 1.17 | 1.29 | 1.70 |
| ARPEGE Europe | 1.53 | 1.50 | 1.01 | 1.35 | 1.24 | 2.01 |
| runs (pairs per model) | 2 (194) | 2 (193) | 3 (288) | 3 (289) | 3 (291) | 3 (292) |

(– : no native output at that hour, or the model has ended.) The April run has no
ALADIN, so it counts only beyond H+72. Five runs of three weather situations: a check
that the pipeline works, not a result.

### ALADIN from our own archive (`leads-aladin.json`)

1. Reads the archived runs of the last `--days` days (default 30) from
   `<archive-dir>/aladin-YYYY-MM/*.parquet` (with `--github-release` it first downloads
   the missing ones from the releases `aladin-YYYY-MM`; files already there are kept).
2. Per model, run, station and lead hour 1–72 (lead 0, the analysis, is left out):
   temperature and wind as stored (instant values at `valid_time = run + lead_h`);
   precipitation as `precipitation_accum(h) − precipitation_accum(h − 1)`, i.e. mm in
   the hour ending at the valid time (lead 1 = its accumulation, as there is none at
   lead 0; small negative differences from GRIB packing → 0; missing previous lead →
   no value).
3. Joins the observations (`data/obs`, same conventions as the D+N scores: T and F at
   the full hour, precipitation summed over the hour ending there) on station, valid
   time and variable, and keeps only the run, station, lead hour and variable that
   **both** domains have, so they are compared on the same sample.
4. Sums errors (`metrics.error_sums`) and, for precipitation, the 2×2 counts for
   ≥ 0.1 mm in the hour, per lead hour: for Czechia over all runs and per run hour
   (00, 06, 12, 18 UTC), and per kraj over all runs.

`site/data/leads-aladin.json` (Czechia) and `site/data/leads-aladin-kraj.json` (kraje),
with `--publish` also in the release `data-latest` (until 2026-10-13 these were
`leads.json` and `leads-kraj.json`). Same keys as `leads.json` plus a `region` column
(`cz` or a kraj NUTS 3 code) and `regions`. The web page shows the all-model file; this
one stays as a check of Open-Meteo's ALADIN (nearest grid point, no elevation
correction, all ~290 stations) and it is where the **publication time** comes from:
the median delay from run start to `published` per ALADIN domain goes into
`leads.json` (`publication_delay_h`) and shades the hours not yet published on the
chart. About 230 KB for Czechia (2,160 rows), 650 KB for the kraje.

First real run, 2026-10-13 (runs 2026-10-09 00 UTC to 2026-10-13 06 UTC, 18 per
domain; observations from `now/` for 2026-10-10 00 UTC to 2026-10-13 12 UTC, as
`now/` no longer had 2026-10-09; 291 stations with temperature): temperature MAE in °C

| | H+1 | H+6 | H+12 | H+24 | H+48 | H+72 |
|---|---|---|---|---|---|---|
| ALADIN CZ 1 km | 0.93 | 1.11 | 1.11 | 1.10 | 1.27 | 1.61 |
| ALADIN Central Europe 2.3 km | 0.99 | 1.17 | 1.17 | 1.15 | 1.31 | 1.62 |
| runs (pairs per domain) | 14 (4,041) | 15 (4,327) | 15 (4,327) | 15 (4,327) | 11 (3,174) | 7 (2,023) |

Four days of one October spell: an illustration that the pipeline works, not a result.

## Event skill for farmers (`mvd farm`)

What it means: [methodology](methodology.md#event-skill-for-farmers). `meteoverdict.farm`
reads the same single runs and observations as `mvd leads` (last `--runs-days`, 90;
`--github-release` downloads them first, read only; `--publish` puts `farm.json` into
`data-latest`). In `daily.yml` it is the last step, optional like the `mvd leads` step
before it (`continue-on-error`), and reuses what that step downloaded; `pages.yml`
fetches `farm.json` from `data-latest` like `leads.json`. No Open-Meteo calls.

Units and events (thresholds inclusive):

| Event | Unit | Observed | Forecast | Thresholds |
|---|---|---|---|---|
| `frost` | station × night, 18:00–09:00 Europe/Prague (16 full hours, 15/17 when the clocks change), keyed by its end | minimum of the hourly `T`, every hour required | minimum over the model's own output hours in the night, every one required; the whole night after the run's start | ≤ 0, ≤ −2 °C |
| `gust` | station × 3-hour block 00–03, 03–06, … UTC, keyed by its end | maximum of the three hourly gusts (each from six `Fmax`), all required | maximum of `wind_gusts_10m` at the model's own output hours in the block (3 for hourly output, the end for 3-hourly); 6-hourly not scored | ≥ 10, 15, 20 m/s |
| `rain3h` | the same blocks | sum of the three hourly sums, all required | the model's own 3-hour total: the sum of its three hourly values for hourly output, the value at the block's end for 3-hourly output (stored at native steps: the total since the step before; runs stored hourly before 2026-10-17 are converted, `runs.native`); 6-hourly not scored | ≥ 0.5, 2, 5 mm |

The lead bins (1–6, 7–12, 13–24, 25–48, 49–72, 73–120) go by the lead of the unit's end.
Runs start at 00/06/12/18 UTC, so blocks end at leads 3, 6, 9, … and never straddle a
run's start; a night ends at H+19 (12 UTC run), H+25 (06), H+31 (00) or H+37 (18 UTC),
each a day later at the longer leads, so H+1–6 and H+7–12 have no frost nights and
H+13–24 holds only the 12 UTC runs' coming night.

**Fair set.** A model's coverage of a variable is the median first and last lead with
a value per run hour (narrowest over the run hours in which any model has the variable;
gusts exist only in runs fetched since 2026-10-15). Per event and bin the required
models are those covering the whole bin (for blocks also with an output step of at most
3 h throughout); only units that every required model has, with an observation, count.
Models with fewer than 80 % of the period's runs (added recently) are left out until
they have them (`short_record`, as in `leads.json`).
Measured coverage of the gusts (run of 2026-10-13 00 UTC): ALADIN 1–72, ICON-D2 1–48,
AROME 2–60, ICON-EU, IFS HRES, GFS, UKMO 1–120 (UKMO 60 from 06/18 UTC), ARPEGE 1–102,
IFS 0.25° 3–92 (temperature to 120), AIFS none.

`site/data/farm.json`:

| Key | Meaning |
|---|---|
| `generated`, `first_run`, `last_run` | UTC, `YYYY-MM-DDTHH:MMZ` |
| `runs`, `stations` | runs and stations with at least one scored unit |
| `bins`, `small_sample` | the lead bins; fewer observed events than this are flagged (20) |
| `events` | per event: `variable`, `unit` (`night`, `3h`), `op` (`<=`, `>=`), `thresholds`, `definition` |
| `models` | per model: `name`, `runs` scored, `leads` (coverage per variable, `[first, last]`) |
| `short_record` | models left out for fewer than 80 % of the period's runs: `{model: {runs, of, coverage}}` |
| `columns`, `rows` | one row per `event`, `threshold`, `bin`, `model`: `units` (nights or blocks, station × run; the same for every model of a bin), `runs`, `stations`, `events` (observed), `hits`, `misses`, `false_alarms`, `correct_negatives`, `pod`, `far`, `csi`, `ets`, `bias` (frequency bias; 3 decimals, null when the denominator is 0) |

About 35 kB with 11 runs (all events, thresholds and bins); it grows with the bins and
models filled, not with the runs (at most 8 × 6 × 11 rows).

**First real numbers, 2026-10-15** (read only towards GitHub; 1,320 Open-Meteo calls):
the runs of 2026-10-11 12 UTC, 2026-10-12 00 and 12 UTC fetched with gusts, plus the 8
runs of 2026-10-13 00 to 2026-10-14 18 UTC from the release `runs-2026-10` (no gusts);
observations of the 100 stations from the release `data-2026-10` (10–14 Oct) and
ČHMÚ `now/` (13 Oct 00 to 15 Oct 09 UTC, with gusts). The nights of 12/13 and 13/14
October had frost at many stations (down to −8.4 °C on 13 Oct).

| Event | Bin | Units | Events | Best ETS (POD / FAR) |
|---|---|---|---|---|
| frost ≤ 0 °C | H+13–24 | 378 nights | 39 | ICON-D2 0.18 (0.23 / 0.31) |
| frost ≤ 0 °C | H+25–48 | 849 | 79 | ICON-D2 0.17 (0.20 / 0.30) |
| frost ≤ 0 °C | H+49–72 | 474 | 15 ⚠ | none above 0 |
| gust ≥ 10 m/s | H+25–48 | 1,937 blocks | 87 | ICON-D2 0.41 (0.79 / 0.52); AROME 0.39 |
| gust ≥ 10 m/s | H+49–72 | 2,228 | 173 | ALADIN 2.3 km 0.35 (0.55 / 0.43) |
| gust ≥ 15 m/s | H+49–72 | 2,228 | 22 | ALADIN 1 km 0.09 (0.14 / 0.75) |
| rain ≥ 0.5 mm / 3 h | H+1–6 | 2,141 | 97 | ALADIN 1 km 0.33 (0.49 / 0.45) |
| rain ≥ 0.5 mm / 3 h | H+13–24 | 3,892 | 119 | UKMO 0.40 (0.56 / 0.39) |
| rain ≥ 0.5 mm / 3 h | H+25–48 | 5,441 | 122 | UKMO 0.36 (0.54 / 0.47) |

Every model forecast far too few frost nights (frequency bias 0.15 to 0.9 at H+13–48,
mostly 0.3–0.5; ICON-D2 caught 9 of 39 at H+13–24):
the 2 m temperature at the station's elevation stays above 0 °C in clear, calm nights
when the station drops below. Gusts ≥ 20 m/s and 3-hour rain ≥ 5 mm hardly occurred
(0 and 12 events). A handful of runs in one cold spell: a check that the pipeline works,
not a result.

## Okres and kraj boundaries

`src/meteoverdict/data/kraje.geojson` holds the 14 kraje with their NUTS 3 code
(`CZ010` … `CZ080`) and name; `okresy.geojson` the 77 okresy with their LAU 1 code
(`CZ0100` for Praha, `CZ0201` … `CZ0806`) and name. The first five characters of an
okres code are its kraj's code. Built by `scripts/build_regions.py` from:

- ČÚZK INSPIRE Administrative Units (`services.cuzk.gov.cz/gml/inspire/au/`). ČÚZK
  publishes its open data under CC BY 4.0 ("ČÚZK poskytuje otevřená data pod licencí
  Creative Commons CC-BY 4.0", cuzk.gov.cz, Otevřená data – základní informace).
- converted to GeoJSON by [siwekm/czech-geojson](https://github.com/siwekm/czech-geojson)
  (CC BY 4.0), pinned to commit `6e77140c`. Names and ids are top-level feature fields
  there (`name`, `id` = `CZ0100000000`), not `properties`.

The script simplifies each level as one coverage (`shapely.coverage_simplify`,
tolerance 0.002°) so neighbours keep identical shared borders, and rounds to 4
decimals: 9 MB → 240 KB for kraje, 20 MB → 550 KB for okresy; borders move by at most
~0.006° (about 0.6 km). Středočeský kraj has a hole (Praha), Brno-venkov too
(Brno-město), Louny one more, and Litoměřice is a MultiPolygon (an exclave). In the
source data Praha's okres is called "území Hlavního města Prahy".

`mvd stations` gives a station the okres whose polygon contains it, or the nearest
okres if the station is at most 2 km outside the national border, and takes the kraj
from the okres code, so both levels always agree. On 2026-10-12 every okres had
stations (2 to 25, median 9).

## Open-Meteo Previous Runs API (forecasts)

Checked on **2026-10-11** against the Open-Meteo documentation, its source code
(open-meteo-website at `1755598c7ac9`, open-meteo server at `f625df2c2b2d`) and live
requests. The free tier also has per-minute and per-hour limits: a burst of a few
hundred requests got `429 Too Many Requests`, so the client must batch and back off.

- Endpoint: `https://previous-runs-api.open-meteo.com/v1/forecast`, same parameters as
  the Forecast API (`latitude`, `longitude`, `elevation`, `hourly`, `models`,
  `start_date`/`end_date` or `past_days`).
- `<variable>_previous_dayN` is the value predicted 24·N hours before the valid time,
  N = 1…7; `_previous_day0` is the latest run. For models with a short forecast horizon
  only the offsets within the horizon are filled ("a model with a 3-day horizon will
  have at most `_previous_day3` populated"). Checked against the Single Runs API on
  2026-10-16 (see [Fresh D+N](#fresh-dn-from-the-single-runs)): exactly the newest run
  that started at least 24·N hours before; "run" includes runs Open-Meteo has between
  the 6-hourly ones (ICON-D2, GeoSphere and DMI every 3 hours, KNMI every hour), and
  the UK Met Office's 06 and 18 UTC runs do not count beyond D+1.
- Variables with offsets include `temperature_2m`, `precipitation` and
  `wind_speed_10m`, the three we verify.
- Archive: the docs say "most models are archived from January 2024"; measured per
  model below.
- Licence: CC BY 4.0 (UK Met Office data: CC BY-SA 4.0). Free tier: non-commercial
  only, 600 calls/min, 5,000/hour, 10,000/day, 300,000/month. A call is weighted:
  locations × max(1, variables × models / 10 × max(1, days / 14)), so a 14-day window
  costs the same as one day. Commercial use of this API needs the Professional
  subscription. See [licensing.md](licensing.md).

### Fetching (`mvd fetch-fc`)

- Several locations go in one request as comma-separated `latitude`, `longitude` and
  `elevation` lists; the answer is a JSON **list** in the same order (every item but
  the first carries `location_id`). We send the station elevation, which Open-Meteo
  echoes back and uses for its elevation correction; `elevation=nan` makes it use its
  own terrain height instead (checked: 286 m at Praha-Libuš).
- Errors come as HTTP 400 `{"error": true, "reason": "…"}`; the daily limit as HTTP
  429 with "Daily API request limit exceeded"; the minute and hour limits, HTTP 5xx,
  network errors and answers that are not JSON are retried. Days before a model's archive start
  return `null` values.
- `mvd fetch-fc` (and the backfill) asks for each model's measured lead days only, for
  up to 14 days and 100 stations, and stores one row per station × hour × model × lead
  day with `temperature_2m` (°C), `precipitation` (mm in the hour ending at `time`) and
  `wind_speed_10m` (m/s) in `data/fc/YYYY-MM.parquet`.
- **Several models per request** (`forecasts.groups`, since 2026-10-16): Open-Meteo
  bills at least 1 call per location, and a model with few lead days weighs less than
  that alone (3 variables × 1 lead day / 10 = 0.3). Models with the **same lead days**
  that each weigh less than 1 share a request (`models=a,b,…`): ICON-D2, GeoSphere,
  KNMI and DMI (D+1: 4 × 0.3 = 1.2 instead of 4), the two ALADINs (D+1-2: 1.2 instead
  of 2) and the two ARPEGEs (D+1-3: 1.8 instead of 2); the others weigh 1.2 or 1.5
  alone and keep their own requests (nothing to save). Per station and 14-day window
  that is 23.9 → **20.1 calls** for all 19 models (−16 %); for the rain gauges
  (precipitation only, 28 days) 19 → 13.8 (−27 %). Checked live on 2026-10-16: the
  answer has the columns `<variable>_previous_dayN_<model>` with exactly the values of
  one-model requests; a model without data at a location (ICON-D2 in the Beskydy) is
  **left out of that location's answer** (with one model left, the columns lose their
  suffix) instead of failing the request, so those locations are asked again one model
  at a time and the station is recorded in `uncovered` as before. Each model's rows
  start on its own first day, so the stored rows are the same as before.
- **Cost** (weighted calls, Open-Meteo's formula): about **6,900 calls for one day** of
  the first 11 models at the ~500 verified stations (~11,970 with all 19 one model per
  request, ~10,070 with the shared requests above), the same for
  any window up to 14 days, about 20,600 for a month and about 333,000 for 2024-01-01 to
  2026-10-10 (11 models). So the
  daily pipeline should fetch forecasts in 14-day windows (≈ 15,000 calls a month), and
  the full backfill needs more than one month of the free quota (300,000 a month,
  10,000 a day). `mvd fetch-fc --dry-run` prints the estimate; `--max-calls` stops a
  run before it uses more and keeps what was fetched.
- **Interpolated hours:** Open-Meteo returns a value for every hour even for AIFS
  (6-hourly output) and IFS 0.25° (3-hourly), and for models whose output becomes
  3-hourly at longer lead times (ICON-EU after 78 h, IFS HRES after 90 h, GFS after
  120 h, UK Met Office after 54 h; `coarser_after_h` in models.yaml). The in-between
  hours are interpolated: on 20 stations over 14 days (Sept 2026) the mean temperature
  curvature at 3-hourly hours is 1.5–1.7 times that at the other hours exactly from the
  lead day where the step changes (ICON-EU D+4, IFS D+4, GFS D+5, UKMO D+3), and about
  1.0–1.25 before. See "Pairing" below.

### Pairing (`meteoverdict.align`, roadmap 2.1)

Open-Meteo's docs: temperature and wind are "Instant" values, precipitation the
"Preceding hour sum". The observations follow the same conventions, so pairs join on
station, UTC hour and variable. For a model and lead day whose native step is 3 or 6
hours (`Model.native_step`: the run behind `_previous_dayN` is at least 24·N h old, plus
6 h for run spacing and delivery), temperature and wind are compared only at native
hours and precipitation as sums over native periods (`period_h`); incomplete periods
are dropped. Daily precipitation sums use the UTC day (hours ending 01:00–24:00) and
need all 24 hours. **Unverified:** whether Open-Meteo's hourly precipitation for
6-hourly models adds up exactly to the model's 6-hour totals.

### Models

The catalogue is [`src/meteoverdict/models.yaml`](../src/meteoverdict/models.yaml)
(`mvd models --all` prints it).

**Coverage of Czechia** was checked by testing five points (the westernmost, easternmost,
northernmost and southernmost points of Czechia, plus the centre) against each model's
grid as defined in the Open-Meteo server code (`Sources/App/*/…Domain.swift`); projected
grids (ALADIN Central Europe, DMI, KNMI) were transformed with pyproj. Global models
cover Czechia by definition.

| Model id | Grid extent from the server code | Czechia |
|---|---|---|
| `chmi_aladin_cz_1km` | lat 48.5–51.098, lon 12.0–18.995 | covered |
| `chmi_aladin_central_europe_2km` | Lambert conformal, 1053 × 837 × 2.325 km | covered |
| `dwd_icon_d2` | lat 43.18–58.08, lon −3.94–20.34 | **not the far east**: no data for 6 stations east of about 18.6° E (live check, see below) |
| `dwd_icon_eu` | lat 29.5–70.5, lon −23.5–62.5 | covered |
| `meteofrance_arpege_europe` | lat 20–72, lon −32–42 | covered |
| `geosphere_arome_austria` | lat 42.98–51.82, lon 5.50–22.10 | covered |
| `knmi_harmonie_arome_europe` | rotated grid, 676 × 564 × 0.05° | covered |
| `dmi_harmonie_arome_europe` | Lambert conformal, 1906 × 1606 × 2 km | covered |
| `meteofrance_arome_france` | lat 37.5–55.4, lon −12.0–16.0 | **partly** (not east of 16° E): excluded |
| `italia_meteo_arpae_icon_2i` | lat 33.7–48.9, lon 3–22 | **only the far south**: excluded |
| `gem_regional` (ECCC RDPS 10 km) | polar stereographic, 935 × 824, "North America, North Pole" | **only the north** (live check below): in models.yaml, disabled |
| `dwd_icon`, `gem_global`, `jma_gsm`, `cma_grapes_global`, `meteofrance_arpege_world`, `ncep_aigfs025` | global | covered |

**Live check (2026-10-12):** all ~500 verified stations were requested from each
regional model (ALADIN CZ 1 km and CE 2.3 km, ICON-D2, GeoSphere AROME, ARPEGE Europe).
Only ICON-D2 answered "No data is available for this location", for 6 stations in the
Beskydy (`0-203-0-11792`, `0-203-0-20303008001`, `0-203-0-20303018003`,
`0-203-0-20303019001`, `0-203-0-20303032003`, `0-203-0-42106052001`; lon 18.63–18.83).
The grid rectangle in Open-Meteo's code is wider than the area with data, so the
5-point grid check above was not enough. `mvd fetch-fc` splits a request that fails this
way until it finds such stations and skips them (`uncovered`, kept in the backfill
state); scoring compares models per station among the models covering it.

The UK Met Office UKV 2 km model covers only the UK and Ireland (excluded).
`ecmwf_ifs025` is enabled because IFS HRES (`ecmwf_ifs`) only joined Open-Meteo in
September 2025, so the open-data IFS is our only ECMWF history before that.

**All models (2026-10-15).** On the owner's decision ("I want all the models") every
model of Open-Meteo's Forecast API model list (`MultiDomains` in the server's
`ForecastapiController.swift`) that has data in Czechia and a Previous Runs archive is
enabled. Checked live at Praha-Libuš (Forecast API, Previous Runs API for 1–14 Sep 2026,
Single Runs API):

- **Added:** DWD ICON global (`dwd_icon`), ECCC GEM Global (`gem_global`), JMA GSM
  (`jma_gsm`), CMA GRAPES (`cma_grapes_global`), Météo-France ARPEGE World
  (`meteofrance_arpege_world`), NOAA AIGFS (`ncep_aigfs025`, machine learning), and
  KNMI and DMI HARMONIE-AROME (in models.yaml before, now enabled). KNMI and DMI have
  data at the four extreme points of Czechia and at three more in the south-east
  (Single Runs API, 2026-10-15).
- **Same data under another id:** `meteofrance_arpege_world025` (= ARPEGE World),
  `dwd_icon_global` (= `dwd_icon`), `ncep_gfs013`/`ncep_gfs025` (parts of
  `ncep_gfs_global`).
- **No data in Czechia** (null values or "No data is available"): KMA GDPS
  (`kma_gdps`), BOM ACCESS-G (`bom_access_global`), GraphCast (`ncep_gfs_graphcast025`),
  `ecmwf_ifs04`, `ecmwf_aifs025`, MET Nordic, MeteoSwiss ICON-CH1/CH2, ItaliaMeteo
  ICON-2I; regional models of other continents (HRRR, NAM, NBM, HRDPS, JMA MSM, KMA
  LDPS, UKV, AROME France HD, KNMI Netherlands, COSMO) by their domains.
- **ECCC GEM Regional (RDPS)** has data only north of a line from about 48.83° N at
  12.1° E to 49.63° N at 18.85° E (bisected live with single-point requests,
  2026-10-15): 115 of the 501 verified stations (South Bohemia, South Moravia, parts of
  Vysočina and Zlín) are outside. Like AROME France it is **not enabled**: the fair
  comparison would leave those stations out of the national and kraj rankings for every
  model. Its archive start is not measured (longer Previous Runs requests returned
  empty answers).
- **Not added: ensemble means** (`ncep_hgefs025_ensemble_mean`,
  `ncep_aigefs025_ensemble_mean`, `ecmwf_ifs_europe_ensemble_mean`,
  `ecmwf_aifs_europe_ensemble_mean`): they have Previous Runs data in Czechia, but they
  are means of ensembles, not single model runs (smoother, so they win MAE comparisons
  for that reason), and most of them return no data in the Forecast API, so they could
  not enter the outlook. To decide separately.

**Forecast length, grid and output step** come from the model tables in the Open-Meteo
docs (e.g. ICON-D2 2 days, ALADIN 3 days, ARPEGE Europe 4 days, GeoSphere AROME,
KNMI and DMI 2.5 days).

**Lead days** (`max_lead_day`) were measured: share of September 2026 hours with a
`temperature_2m_previous_dayN` value at Praha-Libuš. The archive fills one day less
than the forecast length for short-range models, because a run issued a full N×24 h
before every hour must still reach that hour:

| Model | D+1 | D+2 | D+3 | D+4 | D+5 |
|---|---|---|---|---|---|
| ALADIN CZ 1 km, ALADIN CE 2.3 km | 100 % | 100 % | 0 | 0 | 0 |
| ICON-D2, GeoSphere AROME, KNMI, DMI | 100 % | 0 | 0 | 0 | 0 |
| ICON-EU, CMA GRAPES | 100 % | 100 % | 100 % | 100 % | 0 |
| ARPEGE Europe, ARPEGE World | 100 % | 100 % | 100 % | 0 | 0 |
| IFS HRES, IFS 0.25°, AIFS, GFS, UKMO global, ICON global, GEM Global, JMA GSM, AIGFS | 100 % | 100 % | 100 % | 100 % | 100 % |
| GEM Regional (disabled) | 100 % | 100 % | 0 | 0 | 0 |

CMA GRAPES has a 10-day forecast but no `_previous_day5` in the archive (measured on
September 2026), so it is used up to D+4. Measured for the models added on 2026-10-15
and KNMI/DMI on the same month.

So the high-resolution models can only be compared at D+1, and ALADIN at D+1 and D+2.

**Archive start and gaps** were measured with `scripts/probe_archive.py` (one request
per model: D+1 forecasts of the three variables at Praha-Libuš, 2021-01-01 to
2026-10-09). `archive_from` is the first day all three variables have D+1 data;
`variable_from` records variables that start later. Re-run the script to refresh.

| Model | First day (D+1) | Hours filled since | Gaps and notes |
|---|---|---|---|
| ALADIN CZ 1 km / CE 2.3 km | 2026-06-24 | 100 % | |
| ICON-D2, ICON-EU | 2024-01-19 | 100 % | |
| ECMWF IFS HRES | 2025-10-01 | 96–100 % | T2m 69–81 % in 2026-03/04, wind 81–83 % in 2026-04/05; a few stray wind values in 2025-01 |
| ECMWF IFS 0.25° | 2024-02-04 | 100 % | |
| ECMWF AIFS | **2025-02-18** | 100 % | not 2024 as the docs suggest |
| NOAA GFS | 2024-01-19 | 100 % | 2 m temperature alone from 2021-03-24 |
| UK Met Office global | 2024-08-08 | **75–84 %** | many months between 14 % and 80 % |
| ARPEGE Europe | 2024-01-19 | 100 % | **10 m wind only from 2026-08-07** |
| GeoSphere AROME | 2026-03-26 | 84–100 % | T2m and precipitation 44–80 % in 2026-03 to 2026-05 |
| KNMI HARMONIE | 2024-06-29 | 99–100 % | precipitation only from 2024-10-10 |
| DMI HARMONIE | 2024-06-29 | 100 % | |
| ICON global | 2024-01-19 | 100 % | T2m and precipitation 89 % in 2026-04 |
| GEM Global | 2024-01-19 | 100 % | T2m 84 % in 2026-06 |
| JMA GSM | ≤ 2021-01-01 | 100 % | all three variables from the first day probed |
| CMA GRAPES | 2024-01-19 | 93 % | 69 % in 2025-08, 26–27 % in 2025-09, 23 % in 2025-10, 68 % in 2026-01 |
| ARPEGE World | 2024-01-19 | 100 % | **10 m wind only from 2026-08-07** (as ARPEGE Europe) |
| NOAA AIGFS | **2026-01-22** | 68–73 % | precipitation from 2026-01-06, wind 2026-01-07, T2m 2026-01-22; 0–84 % of hours until 2026-06, ≥ 90 % since 2026-07 |

Consequences:

- **ALADIN, the model this project most wants to evaluate, has Previous Runs history
  only from 2026-06-24**, not the ~2 years assumed in the roadmap. Long-window rankings
  must compare models over their common period (or label windows per model).
- Model code landing in Open-Meteo is not a reliable bound: UKMO, KNMI and DMI data
  start a few days before their integration commits, AIFS a year after.
- Gaps are real (UKMO especially), so scores must count only hours where both the
  observation and the forecast exist, and report the sample size.

The models added on 2026-10-15 were probed with `scripts/probe_archive.py --start
2023-07-01 --model …` (JMA GSM again from 2021-01-01).

Also note: AIFS, AIGFS and JMA GSM have 6-hourly output, IFS 0.25° and CMA GRAPES
3-hourly, so hourly scores for them use fewer hours; ARPEGE World, UKMO, ICON-EU, ICON
global, GEM Global and IFS HRES become 3-hourly later in the forecast (48 h, 54 h, 78 h,
78 h, 84 h and 90 h). Measured for the added models on 2026-10-15 from the Single Runs
API: a 3- or 6-hourly step shows as equal hourly precipitation within each 3- or 6-hour
block (Open-Meteo spreads a period's total evenly), checked at 8 points over 4 runs.
GEM Global is hourly up to 84 h although Open-Meteo's docs say 3-hourly.
