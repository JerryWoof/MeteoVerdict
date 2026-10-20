# Open data (roadmap 6.11)

Our combined forecast and the ranking of the models for every okres, as static JSON
and CSV files on GitHub Pages: free, no key, CORS allowed (GitHub Pages sends
`Access-Control-Allow-Origin: *`). Human-readable page with a picker and examples:
<https://jerrywoof.github.io/MeteoVerdict/data.html>.

| File | Contains |
|---|---|
| `api/v1/index.json` | all 77 okresy: `code`, `name`, `lat`, `lon` and the URLs of their files |
| `api/v1/okresy/{code}.json` | everything for one okres (below) |
| `api/v1/okresy/{code}.csv` | the hourly forecast: `time_utc,temperature_2m,precipitation,wind_speed_10m,cloud_cover,sunshine_duration,temperature_2m_lo,temperature_2m_hi` |

The CSV files are plain CSV: one header row, no comment line, so that Google Sheets'
`=IMPORTDATA`, Excel and `pandas.read_csv` read them as they are. They hold the hourly
series only and **no threshold flags** (`gust_over_threshold`, `frost`, `ground_frost`,
`heavy_rain` are in the JSON files only), so they need no "not a ČHMÚ warning" notice;
the notice is in `index.json` and in every JSON file (`notice`). A CSV that gets a flag
must carry the notice too; a test (`web/src/api.test.js`) fails when one does.

Base URL: `https://jerrywoof.github.io/MeteoVerdict/`. Codes are LAU 1 (`CZ0201`
Benešov, `CZ020A` Praha-západ, `CZ0100` Praha).

## An okres file

- `okres`: code, name, and the forecast point inside the okres (`combine.okres_points`).
- `forecast.generated`, `forecast.hourly`: `time` (UTC, `2026-10-12T00:00Z`) and the
  combined hourly series `temperature_2m` (°C), `precipitation` (mm in the hour ending at
  the time), `wind_speed_10m` (m/s), `cloud_cover` (%) and `sunshine_duration` (s of
  sunshine in the hour ending at the time; both the mean of the models corrected
  against ČHMÚ observations, the hourly sunshine scaled so that each UTC day adds up to
  the corrected daily total: [methodology](methodology.md#sunshine-cloud-and-gusts));
  6 days; `null` where fewer than two models cover an hour. `temperature_2m_lo` and
  `temperature_2m_hi` (°C) are the 80 % range around the temperature (the "±" of the chart; absent
  until computed; [methodology](methodology.md#the-range-around-the-temperature-mvd-blend-interval)).
- `forecast.parts`: per day and part of day in Prague time (`night`, `morning`,
  `afternoon`, `evening`, `day`): `tmin`, `tmax`, `precipitation`, `rain_probability`,
  `wind`, `cloud`, `sunshine` (hours), `symbol` (as on the forecast map;
  [data-sources.md](data-sources.md#outlook-mvd-outlook-roadmap-66)), and `sunrise`,
  `sunset` (Prague time, `"07:21"`, at the okres point, the same on every row of a day),
  `heavy_rain_probability` (calibrated chance of at least 5 mm in the period) and
  `heavy_rain` (true when it is high enough to flag); both `null` while there is no
  rain calibration ([methodology.md](methodology.md#probability-of-precipitation-and-heavy-rain-meteoverdictrain_calibration)).
  Frost, on the `night` and `day` rows of the date a night (18–06 UTC) ends and `null`
  elsewhere or when not available: `night_min` (corrected night minimum at 2 m, °C),
  `coldest_site` and `coldest_min` (the okres's most frost-prone ČHMÚ station and its
  corrected minimum), `frost_probability` (0–1, minimum ≤ 0 °C), `frost` (air-frost
  threshold flag, `night_min` ≤ 1 °C), `ground_min` (estimated minimum 5 cm above the ground)
  and `ground_frost` (`ground_min` ≤ 0 °C); [methodology.md](methodology.md#frost-night-minimum-frost-and-ground-frost).
  Gusts, on every row the newest single model run covers (about the next 4–5 days,
  `null` beyond it and in files from before 2026-10-16): `gust` (the strongest gust of
  the period, m/s: each model's largest hourly gust at the okres's lowland ČHMÚ
  stations, mean over the models, corrected against ČHMÚ gust observations) and
  `gust_over_threshold` (true when `gust` ≥ 13.5 m/s, the level that best caught
  observed gusts of 15 m/s and more); [methodology.md](methodology.md#gusts-in-the-outlook).
  `gust_warning` is a **deprecated alias** of `gust_over_threshold` (the same value)
  and will be removed in the next API version.
  `gust_over_threshold`, `frost`, `ground_frost` and `heavy_rain` are MeteoVerdict
  thresholds, **not official warnings**: only ČHMÚ issues those
  ([chmi.cz](https://www.chmi.cz/); [licensing.md](licensing.md#weather-warnings-act-2622024-sb)).
  Every file repeats this in its top-level `notice`.
- `models.variables.<variable>` for `temperature_2m`, `wind_speed_10m`,
  `precipitation_daily` and `precipitation_24h`: `stations`, `borrowed`, `days`, and
  `lead_days."1"…"5"`: the models in rank order with `rank`, `mae`, `bias`, `rmse`,
  `tied_with_best`, `p_best` (the probability of being the best model: the share of the block-bootstrap resamples in which it has the lowest MAE; below 0.6 for the leader, the map shows no clear winner; `null` in files written before October 2026), `small_sample` (the ranking rests on fewer than 30 days), `short_record` (a newly added model: scores on fewer than 80 % of the window's days, not ranked, no weight), `days`, `mos_weight` (its weight in the temperature and wind regression) and `weight`/`correction` as used in our forecast (`null` for the
  06–06 precipitation, which is ranked but not combined). Window: the last 90 days
  (`models.from`, `models.to`).
- `licence`, `attribution`, `docs`.

## Every model's own forecast (outside `api/v1`)

The forecast pages read `data/scores/forecast/models/{code}.json` (e.g.
`https://jerrywoof.github.io/MeteoVerdict/data/scores/forecast/models/CZ0201.json`),
written by `mvd outlook` with each of its four runs a day: every model's hourly
forecast at the okres point as Open-Meteo gave it (no correction, rounded), and our
combined series, in columns: `generated`, `okres`, `time` (UTC hours), `variables`
(units), `combined.<variable>` and `models.<model>.<variable>` (a model's series ends at
its last hour), `licence`, `attribution`
([data-sources.md](data-sources.md#outlook-mvd-outlook-roadmap-66)). Public, but not
part of the versioned `api/v1`: its layout may change with the pages. Our own monthly
archive of every run's full answer is in the releases `outlook-models-YYYY-MM`
(`outlook-models-YYYY-MM-DD.parquet`, one file per UTC day).

The forecast map's model switch reads `data/scores/forecast/models-parts/{model}.json`
(e.g. `https://jerrywoof.github.io/MeteoVerdict/data/scores/forecast/models-parts/ecmwf_ifs.json`)
and `data/scores/forecast/models-parts/index.json`, also written by `mvd outlook` with
each run: one model's parts of day and whole days for all 77 okresy by the outlook's
rules (tmin, tmax, precipitation in mm, wind, cloud, sunshine and a simplified symbol;
null beyond the model's horizon, `last_hour`; no probability of precipitation), and the
models in order of their mean rank over Czechia
([data-sources.md](data-sources.md#outlook-mvd-outlook-roadmap-66)). Raw model output,
without our correction. Public, but not part of `api/v1` either.

## Files for the AI forecast and the heatmap (outside `api/v1`)

Experimental, published daily with the release `ai-latest` (`ai.zip`, from about 08:30 Prague time)
and served under `data/scores/ai/`: `ai.json` (status, verification rule, scores and validation,
counted from the launch on 2026-10-19), `ai-forecast.json` (hourly forecast by okres), `fc/outlook.json`,
`fc/verify/{code}.json`, `fc/compare/`, and the inputs of the 100 m heatmap (`fc/heat/`, `fc/temp100m/`;
the browser composes the hour). They carry no `licence` or `attribution` field yet; their licence is not decided yet (treat as CC BY-SA derived data until it is)
([licensing.md](licensing.md)). The [Data page](https://jerrywoof.github.io/MeteoVerdict/data.html) lists
every file, release, schedule and licence.

## On an e-ink display

[MeteoVerdict for TRMNL](https://github.com/JerryWoof/MeteoVerdict-TRMNL) is built on
these files: today and tomorrow, the next 24 hours or five days for one okres on a TRMNL
e-ink display. It uses `forecast.hourly` and `forecast.parts`, including `sunrise`,
`sunset` and `sunshine`, so changes to those fields should keep it in mind.

## How they are made

`web/scripts/build-api.mjs` (part of `npm run build`, logic in `web/src/api.js`) writes
them from the data the pages use: `outlook.json` and `outlook-hourly.json` (`mvd
outlook`, four times a day), `forecast/<okres>.json` and `90d/okres/<variable>.json` (`mvd
aggregate`, daily). The Pages workflow runs after the Daily and the Outlook workflows,
so the files follow both. About 3.4 MB in total, 25 kB per okres.

## Terms

CC BY-SA 4.0: credit MeteoVerdict, Open-Meteo.com (model data, CC BY 4.0; UK Met Office
CC BY-SA 4.0) and ČHMÚ (observations, CC BY 4.0) — the `attribution` field has the text —
and share derived data alike. Not an official forecast; whether the combination beats
the best single model is tested daily on a still short history (`blend-test.json`,
roadmap 6.4). Please fetch at most once an
hour.
