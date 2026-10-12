# Open-Meteo fixtures

Real responses of the Previous Runs API (`previous-runs-api.open-meteo.com/v1/forecast`),
downloaded on 2026-10-12, re-indented only.

| File | Request |
|---|---|
| `aladin-2-stations-20261009.json` | Praha-Libuš and Cheb (lat, lon, station elevation), `models=chmi_aladin_cz_1km`, temperature, precipitation and wind for `previous_day1` and `previous_day2`, `wind_speed_unit=ms`, 2026-10-09 |
| `aladin-precipitation-2-stations-20261009.json` | the same two stations and day, `hourly=precipitation_previous_day1,precipitation_previous_day2` only (as asked for the rain gauges) |
| `error-invalid-model.json` | `models=nonexistent_model` (HTTP 400) |
| `forecast-2-okresy.json` | **Forecast API** (`api.open-meteo.com/v1/forecast`), not re-indented: the forecast points of okres Praha (50.0668, 14.466) and Benešov (49.717, 14.7767), the 11 enabled models, `hourly=temperature_2m,precipitation,wind_speed_10m,cloud_cover`, `wind_speed_unit=ms`, `timezone=GMT`, `forecast_days=6`, fetched 2026-10-12 08:25 UTC |

The daily-limit answer used in the tests (HTTP 429,
`{"error":true,"reason":"Daily API request limit exceeded. Please try again tomorrow."}`)
was returned to the cloud development sandbox on 2026-10-11.
