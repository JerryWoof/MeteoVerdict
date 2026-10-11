# ČHMÚ fixtures

Small excerpts of real files from `https://opendata.chmi.cz/meteorology/climate/now/`,
read on 2026-10-11 (see `docs/data-sources.md`).

| File | Source |
|---|---|
| `meta1-20261011.json` | `now/metadata/meta1-20261011.json`: 4 of several hundred stations |
| `meta2-20261011.json` | `now/metadata/meta2-20261011.json`: 6 rows for Cheb |
| `1h-0-20000-0-11520-20261011.json` | `now/data/1h-0-20000-0-11520-20261011.json`: first 3 rows |

The envelope, header strings, field order and value types are as served. The rows
are a subset, and the `values` arrays are shortened. opendata.chmi.cz is not reachable
from the development sandbox, so these were transcribed through a web reader rather
than downloaded byte for byte. Re-record them verbatim once a fetcher runs with network
access (roadmap 3.2), and keep them small.
