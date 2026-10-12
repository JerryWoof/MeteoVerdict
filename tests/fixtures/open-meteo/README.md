# Open-Meteo fixtures

Real responses of the Previous Runs API (`previous-runs-api.open-meteo.com/v1/forecast`),
downloaded on 2026-10-12, re-indented only.

| File | Request |
|---|---|
| `aladin-2-stations-20261009.json` | Praha-Libuš and Cheb (lat, lon, station elevation), `models=chmi_aladin_cz_1km`, temperature, precipitation and wind for `previous_day1` and `previous_day2`, `wind_speed_unit=ms`, 2026-10-09 |
| `error-invalid-model.json` | `models=nonexistent_model` (HTTP 400) |

The daily-limit answer used in the tests (HTTP 429,
`{"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}`)
was returned to the cloud development sandbox on 2026-10-11.
