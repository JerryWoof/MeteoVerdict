# ČHMÚ fixtures

Small excerpts of real files from `https://opendata.chmi.cz/meteorology/climate/`,
read on 2026-10-11 (see `docs/data-sources.md`).

| File | Source |
|---|---|
| `meta1-20261011.json` | `now/metadata/meta1-20261011.json`: 4 of several hundred stations |
| `meta2-20261011.json` | `now/metadata/meta2-20261011.json`: 6 rows for Cheb |
| `1h-0-20000-0-11520-20261011.json` | `now/data/1h-0-20000-0-11520-20261011.json`: first 3 rows |
| `meta1-historical.json` | `historical/metadata/meta1.json` (created 2026-02-12): all periods of Cheb and Praha-Libuš, Reykjavik, and two closed stations (Marambio, Svatý Petr). Karlovy Vary is left out on purpose, to test a station that is only in the current list. |

The envelope, header strings, field order and value types are as served. The rows
are a subset, and the `values` arrays are shortened. They were first transcribed
through a web reader; on 2026-10-11 every row, header and envelope field was checked
against the downloaded files and matched exactly. Keep them small.
