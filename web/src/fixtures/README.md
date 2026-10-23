# Web test fixtures

Real data, downloaded, not typed:

| File | What |
|---|---|
| `open-meteo-forecast-CZ0201.json` | Open-Meteo Forecast API at Benešov's forecast point, 11 models, 12 Oct 2026 |
| `weights-CZ0201.json` | `forecast/CZ0201.json` written by `mvd aggregate` (roadmap 6.2), 12 Oct 2026 |
| `outlook.json` | `outlook.json` of the first Outlook workflow run, 12 Oct 2026 08:31 UTC |
| `scores-90d-okres-precipitation_24h.json` | the published `90d/okres/precipitation_24h.json` of 12 Oct 2026, only the rows of okres Litoměřice (CZ0423) and Benešov (CZ0201) |
| `scores-90d-okres-temperature_2m.json` | the published `90d/okres/temperature_2m.json` of 12 Oct 2026, only Litoměřice and Benešov |
| `meta.json` | the published `meta.json` of 12 Oct 2026 |
| `outlook-hourly.json` | the published `outlook-hourly.json` of 12 Oct 2026 10:49 UTC, only Benešov and Litoměřice |
| `scores-90d-okres-temperature_2m_{00,06,12,18}utc.json` | the published synoptic-hour temperature scores (`90d/okres`) of 12 Oct 2026, only Litoměřice and Benešov |
| `radar-index.json` | the `index.json` of the `radar-live` folder written by `mvd radar-live` on 15 Oct 2026 21:10 UTC (the data contract with echo tops, motion, cells, satellite and scales), only the last 4 radar frames, 2 MERGE sums, 3 nowcast frames and 2 satellite frames per product |
| `radar-motion.json` | `motion/202610152110.json` of the same folder |
| `radar-cells.json` | **synthetic** `cells/<stamp>.json` in the same format (the real folder had no storm cells that night): four cells moving north-east, one with hail |
| `models-CZ0201.json` | `forecast/models/CZ0201.json` as written from the Open-Meteo answer of 12 Oct 2026 08:25 UTC (11 models, no sunshine asked then) with our combination (without the sunshine/cloud correction) |
| `models-parts-dwd_icon_d2.json`, `models-parts-ecmwf_ifs025.json`, `models-parts-index.json` | `forecast/models-parts/<model>.json` and `index.json` as written from the same Open-Meteo answer (12 Oct 2026 08:25 UTC, Praha CZ0100 and Benešov CZ0201 only; ICON-D2 ends on 14 Oct) and the test weights |
| `ai-forecast-extra.json` | **synthetic** `ai-forecast.json` with the `extra` block (further variables, ai and reference series, AI null beyond D+4, no snow) for one okres, Benešov (CZ0201), 12 Oct 2026 |
