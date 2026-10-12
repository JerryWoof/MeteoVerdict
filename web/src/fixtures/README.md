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
| `outlook-hourly.json` | `outlook-hourly.json` written by `mvd outlook` on 12 Oct 2026 10:49 UTC, only Benešov and Litoměřice |
| `scores-90d-okres-temperature_2m_{00,06,12,18}utc.json` | the published synoptic-hour temperature scores (`90d/okres`) of 12 Oct 2026, only Litoměřice and Benešov |
