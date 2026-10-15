# ČHMÚ fixtures

Small excerpts of real files from `https://opendata.chmi.cz/meteorology/climate/`,
read on 2026-10-11 (see `docs/data-sources.md`).

| File | Source |
|---|---|
| `meta1-20261011.json` | `now/metadata/meta1-20261011.json`: 4 of several hundred stations |
| `meta2-20261011.json` | `now/metadata/meta2-20261011.json`: 6 rows for Cheb |
| `1h-0-20000-0-11520-20261011.json` | `now/data/1h-0-20000-0-11520-20261011.json`: first 3 rows |
| `meta1-historical.json` | `historical/metadata/meta1.json` (created 2026-02-12): all periods of Cheb and Praha-Libuš, Reykjavik, and two closed stations (Marambio, Svatý Petr). Karlovy Vary is left out on purpose, to test a station that is only in the current list. |
| `dly-0-203-0-10101067001-202608.json` | `recent/data/daily/08/dly-0-203-0-10101067001-202608.json` (manual rain gauge, downloaded 2026-10-12): 5 days of `SRA` and `SNO` |
| `dly-0-203-0-10101067001-202609.json` | same station, September 2026: 5 `SRA` rows, all still missing (`QUALITY` 4), as served |
| `dly-0-203-0-10101067001-SRA.csv` | `historical_csv/data/daily/precipitation/dly-0-203-0-10101067001-SRA.csv`: header, 5 rows from March 2025 and the last 2 rows (December 2025) |

The envelope, header strings, field order and value types are as served. The rows
are a subset, and the `values` arrays are shortened. They were first transcribed
through a web reader; on 2026-10-11 every row, header and envelope field was checked
against the downloaded files and matched exactly. Keep them small.

## `radar/`

Real files from `https://opendata.chmi.cz/meteorology/weather/radar/composite/`,
downloaded unchanged on 2026-10-15 (see `docs/data-sources.md#radar-archive`):

| File | Source |
|---|---|
| `T_PABV23_C_OKPR_20261015103500.hdf` | `maxz/hdf5/`: max reflectivity, 10:35 UTC |
| `pacz2gmaps3.z_max3d.20261015.1035.0.png` | `maxz/png/`: the same time as PNG |
| `T_PASV23_C_OKPR_20261015101000.hdf` | `merge1h/hdf5/`: MERGE 1-hour precipitation ending 10:10 UTC |
| `pacz2gmaps3.fct_z_max.20261015.1035.ft60s10.tar` | `fct_maxz/png/`: nowcast from 10:35 UTC, 6 PNG frames |
| `listing-maxz-png_masked.html` | `maxz/png_masked/` directory listing: the first 8 files, then the closing tags |
