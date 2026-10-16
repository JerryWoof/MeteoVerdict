# ČHMÚ open data: inventory

Everything opendata.chmi.cz offers under `meteorology/`, with sizes, how far back it
goes and what we keep. Sizes are exact: they are the byte counts of the server's
directory listings, crawled on **2026-10-15** (no extrapolation, except the Parquet
column, see below). Licence of all of it: CC BY 4.0, ČHMÚ
([licensing](licensing.md)). How we archive the station data:
[data-sources.md#chmi-archive](data-sources.md#chmi-archive).

Top level of opendata.chmi.cz: `meteorology/`, `hydrology/` and `air_quality/`. Only
`meteorology/` was inventoried. Radar is handled separately; ČHMÚ's ALADIN GRIB files
(`weather/nwp_aladin`) have been archived by us since the 2026-10-09 runs (the server
keeps only three days; [ALADIN archive](data-sources.md#aladin-archive)). The longer
ALADIN history in our scores, from June 2026, comes from Open-Meteo, not from this
archive.

## Climatological station data (`meteorology/climate/`)

One JSON file per station and period, in long format (one row per station × element ×
time). The format of each kind is in [data-sources.md](data-sources.md#chmi-archive).

### What the folders hold

| Folder | Resolution | Files | JSON | Stations | Time covered | Kept on the server |
|---|---|---:|---:|---:|---|---|
| `now/data/` | 10 min (`10m-…`) and 1 h (`1h-…`) per station and day | 2,733 | 0.10 GB | 476 | the last 2–3 days, today included | ~3 days, overwritten hourly |
| `recent/data/10min/` | 10 min, per station and month (month folders `01`…`12`) and the current month per day | 12,366 | 14.3 GB | 486 | last 12 months | until the next year's month replaces it |
| `recent/data/1hour/` | 1 h, same layout | 11,340 | 1.3 GB | 442 | last 12 months | same |
| `recent/data/daily/` | daily, per station and month; the current month in the folder itself, updated every day | 9,861 | 0.36 GB | 774 | last 12 months | same |
| `recent/data/monthly/` | monthly statistics, per station and month | 9,059 | 0.03 GB | 759 | last 12 months | same |
| `recent/data/pentadic/` | 5-day statistics, per station and month | 8,951 | 0.03 GB | 750 | last 12 months | same |
| `recent/data/phenomena/` | days with weather phenomena, per station and month | 6,199 | 0.01 GB | 578 | last 12 months | same |
| `historical/data/10min/<YYYY>/` | 10 min, per station and month | 41,067 | 104.5 GB | 483 | 2018–2025 | permanent, a year added each February |
| `historical/data/1hour/<YYYY>/` | 1 h, per station and month | 40,675 | 9.7 GB | 440 | 2018–2025 | permanent |
| `historical/data/daily/` | daily, the whole history of a station in one file (up to ~100 MB) | 1,537 | 25.4 GB | 1,537 | 1775 (Praha-Klementinum) – 2025; most stations from 1961 | permanent |
| `historical/data/monthly/` | monthly statistics, whole history per station | 1,579 | 2.75 GB | 1,579 | as daily | permanent |
| `historical/data/pentadic/` | 5-day statistics, whole history per station | 748 | 1.96 GB | 748 | as daily | permanent |
| `historical/data/yearly/` | yearly statistics, whole history per station | 1,567 | 0.21 GB | 1,567 | as daily | permanent |
| `historical/data/phenomena/` | phenomena, whole history per station | 974 | 0.45 GB | 974 | 1961–2025 | permanent |
| `now/metadata/`, `recent/metadata/`, `historical/metadata/` | `meta1` stations, `meta2` elements per station (historical: per period, with dates), `meta3` flags, `meta4` quality codes | 68 | 0.03 GB | – | – | `now/`: 10 days |
| `historical_csv/data/…` | the same closed years as CSV, one file per station, element (and month) | 633,116 | 110 GB | – | as `historical/` | permanent |

Per year of data (closed years 2018–2025): 10 min 12.5–13.8 GB of JSON, 1 h 1.1–1.3 GB.
The 10-minute and hourly network is about 480 automatic stations; daily data also
come from about 280 manual rain gauges and climate stations, and the history from
about 1,550 stations (many closed long ago).

Not archived: `historical_csv/` (the same values as `historical/`, in a bigger format)
and `recent/metadata/` (monthly copies of the metadata; we keep a daily copy of
`now/metadata/` instead).

Something we found: the current month's 10-minute and hourly **day files are also in
`recent/data/10min/` and `1hour/`** (e.g. `10m-<WSI>-20261001.json` … yesterday, partly
checked: on 2026-10-14 half of a day's values had quality 0, the rest 5), until the
month is published as a whole after the 3rd of the next month. So a day that has left
`now/` can still be fetched during the same month; the archive uses this as a
fallback.

### Elements

`meta2` lists 103 element codes (the historical file, with the period of each element
at each station). By kind of observation:

| Kind | Elements |
|---|---|
| 10 min (`10M`) | `T` air temperature 2 m, `TMA`/`TMI` max/min, `TPM` ground temperature, `T05` `T10` `T20` `T50` `T100` soil temperatures, `H` relative humidity, `P` pressure, `F` `Fprum` wind speed, `Fmax` gust, `D` `Dprum` `Dmax` wind directions, `Casmax` time of the gust, `SRA10M` precipitation, `SSV10M` sunshine (s), `SCEa` snow depth, `SVHa` snow water equivalent, `RGLB10` `RDIF10` global and diffuse radiation, `REUV10` UV radiation |
| 1 h (`1H`) | `SRA1H` precipitation, `SSV1H` sunshine, `E` vapour pressure, `Td` dew point, `P_hm` sea-level pressure, `ppp` pressure tendency, `N` cloud cover, `VV` visibility, `ww` `W1` `W2` weather codes, `RGLB1H` `RDIF1H` `RDIR1H` `RLWD1H` `REUV1H` radiation, `Gph850` `Gph925` geopotential, 35 ceilometer elements `C-…` (cloud base, boundary-layer height and index; mean, min, max, count), `C-MLAv` `C-MLI` mixing layer |
| daily (`DLY`) | `T` (at 06, 13, 20 UTC and the mean), `TMA`, `TMI`, `TMInoc`, `TPM`, soil temperatures, `H`, `E`, `P`, `F`, `D10`, `Fmax`, `Dmax`, `Casmax`, `SRA` (06–06 UTC), `SNO` new snow, `SCE` snow depth, `SCEdif`, `SVH`, `SSV`, `VY` evaporation, `API30` antecedent precipitation index, `RGLB_D` `RDIF_D` `REUV_D` radiation sums, `O3` |
| monthly, pentadic, yearly | ČHMÚ's statistics of the daily elements: `TIMEFUNCTION` (AVG, 06:00, 13:00, 20:00, SUM) × `MDFUNCTION` (AVG, MAX, MIN, SUM, and day counts such as `GE(30)` "days with at least 30", `L(0)`); also `O` cloudiness and `SD` saturation deficit |
| phenomena (`PHENO`) | dates with `BO` thunderstorm, `DE` rain, `SN` snow, `KR` hail, `ML` fog, `MS` freezing rain, `LE` glaze, `NA` rime, `JI` hoarfrost, `RO` dew, `SV` strong wind |

Praha-Libuš, for scale: 21 elements every 10 minutes, 47 every hour, 27 daily (59
series counting the observation times), 24 monthly with ~190 statistics per month.

## Other meteorological data (`meteorology/`, not station climate data)

Inventoried for completeness; none of it is archived by this project yet.

| Folder | What | Files | Size | Kept |
|---|---|---:|---:|---|
| `weather/nwp_aladin/` | ALADIN forecasts (GRIB) | – | ~1.2 GB a day | 3 days; **archived** at the stations by `mvd archive-aladin` |
| `weather/radar/` | radar products | – | – | handled separately |
| `weather/satellite/` | satellite images | – | – | not inventoried |
| `weather/radiosounding/{Praha,Prostejov}/` | radiosonde ascents and descents: `recent/` CSV, PNG per sounding; `historical/` monthly ZIPs from 2023 | 3,910 | 1.1 GB | `recent/`: about 2.5 months, then monthly ZIPs in `historical/` |
| `weather/wind_profiles/recent/` | wind profiler CSV and PNG per day | 3,635 | 2.2 MB | about 10 days (**ephemeral**) |
| `weather/forecast/now/` | text forecasts (JSON) | 570 | 73 MB | about 3 days (**ephemeral**) |
| `weather/alerts/cap/` | warnings in CAP XML | 759 | 1.2 GB | rolling |
| `weather/forecast_maps_bio/`, `forecast_monthly/` | biometeorological maps, monthly outlook | 5 | 1 MB | current only |
| `floods/` | precipitation forecast maps (PNG) of flood situations | 27,144 | 0.84 GB | since September 2024 |
| `phenology/{herbs,wood_species}/` | phenological observations (CSV per species) | 76 | 5 MB | permanent |
| `products/climate_normal_stations/` | station normals 1991–2020 (T, SRA) | 1,056 | 0.5 MB | permanent |
| `products/grids_CZ/climate_normals/` | gridded normals 1991–2020 (T, SRA, sunshine; GeoTIFF) | 156 | 70 MB | permanent |
| `products/regional_averages/` | areal temperature and precipitation per region | 9 | 0.1 MB | permanent |
| `products/yearbooks/` | climatological yearbooks 2020–2023 (PDF) | 4 | 234 MB | permanent |

The ephemeral ones beside radar and ALADIN are `wind_profiles/recent`, `forecast/now`
and the CSV soundings in `radiosounding/*/recent` (the monthly ZIPs keep them later).
They are candidates for their own small archives.

## What the archive costs

ČHMÚ's JSON compresses 25–90 times as sorted Parquet (zstd). Measured on real files
(2026-10-15):

| Data | JSON | Parquet | Ratio | Time |
|---|---:|---:|---:|---:|
| 10 min, **all 482 stations**, December 2025 (19.1 million rows) | 1,180 MB | 20.8 MB | 57 | 143 s, 1.3 GB RAM |
| 1 h, **all 439 stations**, December 2025 (1.7 million rows) | 108 MB | 1.2 MB | 90 | 44 s, 0.6 GB RAM |
| one UTC day, 10 min + 1 h, all 476 stations (911 files, 0.67 million rows) | ~37 MB | 0.76 MB | ~50 | ~60 s |
| History (daily, monthly, pentadic, yearly, phenomena), Praha-Libuš 1971–2025 | 89 MB | 2.6 MB | 35 | |
| same, Brno-Tuřany 1958–2025 | 87 MB | 2.9 MB | 31 | |
| same, Lysá hora 1897–2025 | 106 MB | 4.2 MB | 26 | |

Extrapolated to everything (ratio 57 for 10 min, 90 for 1 h, 30 for the histories):

| Part of the archive | JSON to download | Parquet stored | Per year from now on |
|---|---:|---:|---:|
| 10 min, 2018–2025 (`historical/`) | 104.5 GB | 1.8 GB | 0.24 GB |
| 10 min, 2026 so far (`recent/`) | ~10 GB | 0.2 GB | (included above) |
| 1 h, 2018–2026 | 11 GB | 0.12 GB | 0.015 GB |
| Station histories: daily, monthly, pentadic, yearly, phenomena (1775–2025) | 30.7 GB | ~1.0 GB | ~0.03 GB (recent months, then the yearly update) |
| Captured days from `now/` (10 min + 1 h as first published, unchecked) | ~37 MB a day | – | 0.28 GB |
| Metadata snapshots (`meta1`–`meta4` zipped, daily) | – | – | 0.02 GB |
| **Total** | **~157 GB** | **~3.1 GB** | **~0.6 GB** |

The largest single file is a month of 10-minute data of all stations, about 21 MB.
Everything fits GitHub Releases comfortably (no limit on a release's total size, 2 GB
per file, 1,000 files per release), so the archive does not need a local disk;
`mvd chmi-mirror <dir>` copies it there 1:1 if wanted (about 3 GB, plus 0.6 GB a year).
Even the full 10-minute history is under 2 GB.

**Download time.** Measured: 8 MB/s for a 10-minute month with 4 parallel downloads,
2.4 MB/s for an hourly month (smaller files); a single 63 MB history file took 60 s
(1 MB/s). The full backfill (~157 GB) is therefore about 6–9 hours of downloading,
two or three daily runs of 5 hours. The daily capture is about 37 MB a day.
