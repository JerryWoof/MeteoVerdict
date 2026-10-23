# Open data (roadmap 6.11)

Our combined forecast and the ranking of the models for every okres, as static JSON
files on GitHub Pages: free, no key, CORS allowed (GitHub Pages sends
`Access-Control-Allow-Origin: *`). Human-readable page with a picker and examples:
<https://meteoverdict.cz/data.html>.

| File | Contains |
|---|---|
| `api/v1/index.json` | all 77 okresy: `code`, `name`, `lat`, `lon` and the URLs of their files |
| `api/v1/okresy/{code}.json` | everything for one okres (below) |
| `api/v1/ai/okresy/{code}.json` | the same file with the MeteoVerdict AI's values: everything by part of day and hourly (**experimental**, below) |
| `api/v1/obce/{okres}/{id}.json` | the forecast of one obec (village or town) (below) |
| `api/v1/ai/obce/{okres}/{id}.json` | the same with MeteoVerdict AI's obec forecast (`model: "ai"`), on the axis and parts of `ai/okresy/{okres}.json`; same ids and the same fields as the combined obec file |
| `api/v1/obce/index.json` | every obec as `[okres, id, name, lat, lon]` |

There are no CSV files (until 2026-10-21 each okres also had a `.csv` of its hourly
series; JSON carries everything the CSV did, plus the parts of the day, the sources and
the `notice`).

Base URL: `https://meteoverdict.cz/`. Codes are LAU 1 (`CZ0201`
Benešov, `CZ020A` Praha-západ, `CZ0100` Praha).

## An okres file

- `okres`: code, name, and the forecast point inside the okres (`regions.okres_points`).
- `forecast.generated`, `forecast.hourly`: `time` (UTC, `2026-10-12T00:00Z`) and the
  combined hourly series `temperature_2m` (°C), `precipitation` (mm in the hour ending at
  the time), `wind_speed_10m` (m/s), `cloud_cover` (%) and `sunshine_duration` (s of
  sunshine in the hour ending at the time; both corrected against ČHMÚ observations);
  6 days; `null` where fewer than two models cover an hour. `temperature_2m_lo` and
  `temperature_2m_hi` (°C) are the 80 % range around the temperature (the "±" of the chart; absent
  until computed).
- `forecast.parts`: per day and part of day in Prague time (`night`, `morning`,
  `afternoon`, `evening`, `day`): `tmin`, `tmax`, `precipitation`, `rain_probability`,
  `wind`, `cloud`, `sunshine` (hours), `symbol` (as on the forecast map;
  [data-sources.md](data-sources.md#outlook-outlookjson)), and `sunrise`,
  `sunset` (Prague time, `"07:21"`, at the okres point, the same on every row of a day),
  `heavy_rain_probability` (calibrated chance of at least 5 mm in the period) and
  `heavy_rain` (true when it is high enough to flag); both `null` while there is no
  rain calibration.
  Frost, on the `night` and `day` rows of the date a night (18–06 UTC) ends and `null`
  elsewhere or when not available: `night_min` (corrected night minimum at 2 m, °C),
  `coldest_site` and `coldest_min` (the okres's most frost-prone ČHMÚ station and its
  corrected minimum), `frost_probability` (0–1, minimum ≤ 0 °C), `frost` (air-frost
  threshold flag, `night_min` ≤ 1 °C), `ground_min` (estimated minimum 5 cm above the ground)
  and `ground_frost` (`ground_min` ≤ 0 °C).
  Gusts, on every row the newest single model run covers (about the next 4–5 days,
  `null` beyond it and in files from before 2026-10-16): `gust` (the strongest gust of
  the period, m/s) and `gust_over_threshold` (true when `gust` ≥ 13.5 m/s).
  `gust_warning` is a **deprecated alias** of `gust_over_threshold` (the same value)
  and will be removed in the next API version.
  `gust_over_threshold`, `frost`, `ground_frost` and `heavy_rain` are MeteoVerdict
  thresholds, **not official warnings**: only ČHMÚ issues those
  ([chmi.cz](https://www.chmi.cz/); [licensing.md](licensing.md#weather-warnings-act-2622024-sb)).
  Every file repeats this in its top-level `notice`.
- `models.variables.<variable>` for `temperature_2m`, `wind_speed_10m`,
  `precipitation_daily` and `precipitation_24h`: `stations`, `borrowed`, `days`, and
  `lead_days."1"…"5"`: the models in rank order with `rank`, `mae`, `bias`, `rmse`,
  `tied_with_best`, `p_best` (the probability of being the best model: the share of the block-bootstrap resamples in which it has the lowest MAE; below 0.6 for the leader, the map shows no clear winner; `null` in files written before October 2026), `small_sample` (the ranking rests on fewer than 30 days), `short_record` (a newly added model: scores on fewer than 80 % of the window's days, not ranked), `days`. Window: the last 90 days
  (`models.from`, `models.to`).
- `licence`, `attribution`, `docs`.

## The AI okres file (experimental)

`api/v1/ai/okresy/{code}.json` has the layout of the okres file (`okres`, `forecast`
with `generated`, `time_zone_of_parts`, `units`, `hourly`, `parts`, and `licence`,
`attribution`, `notice`), without `models` and without the deprecated `gust_warning`.
It is the same file with **the MeteoVerdict AI's values**
(experimental, still unverified): `forecast.model` is `"ai"`, `forecast.method` says so
in a sentence, `forecast.ai_issued` is when the AI issued its forecast and
`forecast.sources` says `ai`, `blend` or `astronomy` for every hourly series and part field.

- `parts`: the rows of the AI outlook (`ai/fc/outlook.json`): `tmin`, `tmax`, `wind`, `gust`
  and `gust_over_threshold`, `cloud`, `sunshine`, `symbol`, `precipitation`, `rain_probability`,
  `heavy_rain_probability`, `heavy_rain` and the frost fields (derived from the AI's temperature)
  are the AI's where it has a value. `sunrise` and `sunset` are astronomy, `coldest_site` and a part
  of day the AI has no row for are the combined forecast's.
- `hourly`: the axis and series of the okres file. `temperature_2m`, `wind_speed_10m`,
  `precipitation`, `cloud_cover`, `sunshine_duration`, `temperature_2m_lo` and
  `temperature_2m_hi` are the AI's on every hour it has a value for (hour-matched by time), the
  combined forecast's elsewhere. The AI's hourly precipitation, cloud and sunshine are its own
  hourly values, consistent with its value of each part of day (night, morning, afternoon,
  evening): the precipitation and sunshine of the hours add up to the AI's, the cloud has the AI's
  mean. Its 80 % range comes from its own past errors. Hours
  without an AI value of their own (and every hour when an older AI file lacks them) take the
  combined forecast's hour-to-hour shape fitted to the AI's part, and the range is then the
  combined forecast's width around the AI's temperature. A part the AI has no row for keeps the
  combined forecast's hours.

The files are only written when the AI files (`data/scores/ai/`) are in the build.
The thresholds (`gust_over_threshold`, `frost`, `ground_frost`, `heavy_rain`) are ours,
**not official warnings** (the `notice` in the file is unchanged).

## The obec files

`api/v1/obce/{okres}/{id}.json`: the combined forecast of one obec (`okres` is the code
as above, `id` a name in lowercase ASCII with dashes: `bila-tremesna`; two obce of the
same name in one okres get `-2`, `-3` … in order of falling population).
`api/v1/obce/index.json` lists all of them (`url` is the pattern; `obce` is
`[okres, id, name, lat, lon]`). They are a **test**: `test: true` in every file, the
layout may change.

- `obec`: `id`, `name`, `okres`, `lat`, `lon`, `elevation` (m); `generated`.
- `hourly`: on the **time axis of the okres file**, not repeated: `start` (its first time, UTC), `step_hours` (1) and `hours` (the length), so hour *i* is `start` + *i* h and the arrays are as long as the okres file's `forecast.hourly.time`; with `temperature_2m` (°C, one decimal),
  `precipitation` (mm in the hour ending at the time) and `wind_speed_10m` (m/s, one decimal).
  An hour the obec forecast has: its value. Between two of its hours at most 3 h apart:
  temperature and wind on a straight line. Otherwise (the first hours of the day, the
  end of the 6 days) the okres value plus the obec's mean difference from the okres over
  the hours both have (wind not below 0); precipitation then is the okres value.
  Where the okres has no value, neither has the obec.
- `sources.okres` lists the fields that are the okres's value (the rest is the obec's own); a copied field is missing on a row where the okres has none.
- `hourly` also has `cloud_cover` and `sunshine_duration` (the okres's, as in the okres file: nothing is
  forecast for an obec itself) and `parts` also `rain_probability`, `cloud`, `sunshine`, `symbol`,
  `sunrise`, `sunset`, `heavy_rain_probability`, `heavy_rain`, `gust`, `gust_over_threshold`,
  `frost_probability`, `coldest_site` and `coldest_min`, copied from the okres's row.
- `parts`: the rows of the okres file's `parts` (same `day`, `part`, order) with `tmin`,
  `tmax`, `precipitation`, `wind`, computed from the obec's hourly series by the rules of the
  okres parts (Prague time: night 0–6 … evening 18–24 and the whole day; `tmin`/`tmax` the lowest and
  highest hour, `precipitation` the sum of the hours ending inside the part, `wind` the highest
  hourly mean; a part needs 4 hours, a day 18). Applied to the okres's own series they give the
  okres file's values. On the rows where the okres file has them also `night_min`,
  `ground_min` (the okres value plus the obec's mean temperature difference over the night
  18–06 UTC) and `frost` (`night_min` ≤ 1 °C), `ground_frost` (`ground_min` ≤ 0 °C);
  the keys are missing on the other rows. These flags are our thresholds, **not official warnings**.

An obec file is about 13 kB (6 days hourly), so the whole set is large; fetch only the
obce you need, at most once an hour.

## Every model's own forecast (outside `api/v1`)

The forecast pages read `data/scores/forecast/models/{code}.json` (e.g.
`https://meteoverdict.cz/data/scores/forecast/models/CZ0201.json`),
written with each run of the forecast: every model's hourly
forecast at the okres point as Open-Meteo gave it (no correction, rounded), and our
combined series, in columns: `generated`, `okres`, `time` (UTC hours), `variables`
(units), `combined.<variable>` and `models.<model>.<variable>` (a model's series ends at
its last hour), `licence`, `attribution`
([data-sources.md](data-sources.md#outlook-outlookjson)). Public, but not
part of the versioned `api/v1`: its layout may change with the pages. Our own monthly
archive of every run's full answer is in the releases `outlook-models-YYYY-MM`
(`outlook-models-YYYY-MM-DD.parquet`, one file per UTC day).

The forecast map's model switch reads `data/scores/forecast/models-parts/{model}.json`
(e.g. `https://meteoverdict.cz/data/scores/forecast/models-parts/ecmwf_ifs.json`)
and `data/scores/forecast/models-parts/index.json`, also written with each run of the
forecast: one model's parts of day and whole days for all 77 okresy by the outlook's
rules (tmin, tmax, precipitation in mm, wind, cloud, sunshine and a simplified symbol;
null beyond the model's horizon, `last_hour`; no probability of precipitation), and the
models in order of their mean rank over Czechia
([data-sources.md](data-sources.md#outlook-outlookjson)). Raw model output,
without our correction. Public, but not part of `api/v1` either.

## Files for the AI forecast and the heatmap (outside `api/v1`)

Experimental, computed daily and published with the release `ai-latest` (`ai.zip`)
and served under `data/scores/ai/`. The AI's issue times are in the files (`ai_issued`, `sky_issued`,
`rain_issued`; now around 08:30 and 17:30 Prague time); the site shows them after its next build.

- `ai.json`: status (`unverified` for every variable until the AI beats the blend on 28 measured days), the verification rule, scores and validation, counted from the launch on 2026-10-19.
- `ai-forecast.json`: the AI's **hourly** forecast by okres, about 5 days from the issue hour: `temperature_2m` (°C) and `wind_speed_10m` (m/s) at the station points, `precipitation` (mm in the hour ending at the time), `cloud_cover` (%), `sunshine_duration` (s in the hour ending at the time) and the 80 % range `temperature_2m_lo`/`_hi`, each as `.ai` and `.combined` on `time`. The hourly rain, cloud and sunshine agree with the AI's parts of the day in `fc/outlook.json`; the `hourly` block gives the method, the units and the largest hour-vs-part difference (`check`). `parts` names the files below.
- `fc/outlook.json`: the complete AI forecast by part of day (`night`, `morning`, `afternoon`, `evening`, `day`; today and 5 more days), in the layout of `outlook.json`. `sources` says `ai` for `tmin`, `tmax` (°C), `wind` (m/s), `cloud` (%), `sunshine` (h), `gust` (m/s, with the `gust_over_threshold` flag at 13.5 m/s), `precipitation` (mm), `rain_probability` (P ≥ 0.2 mm), `heavy_rain_probability` (P ≥ 5 mm), `heavy_rain` and `symbol`, and `astronomy` for `sunrise` and `sunset`. Frost fields are our thresholds, not listed as AI.
- `fc/sky/ai-sky.json` (cloud, sunshine, gusts) and `fc/sky/ai-rain.json` (`rain_probability`, `p1` for P ≥ 1 mm, `heavy_rain_probability`, `precipitation`): the AI's values by okres, marked `shadow: true` (trial output).
- `fc/verify/{code}.json`, `fc/compare/`: comparison with observations and with the other models.
- `fc/stations/index.json`, `fc/stations/validation/{id}.json` and `fc/stations/fc/{id}.json` (from the daily run after 2026-10-21): the AI at the station points (temperature and wind on the validation sample; `tmax`, `tmin`, `wind` for D+1 and D+2 over the last 35 days next to the measurements).
- `fc/heat/`, `fc/temp100m/`: the inputs of the 100 m heatmap (the browser composes the hour).

They carry no `licence` or `attribution` field yet. The AI output is CC BY-SA 4.0 like our other outputs
([licensing.md](licensing.md)). The [Data page](https://meteoverdict.cz/data.html) lists
every file, release, schedule and licence.

## On an e-ink display

[MeteoVerdict for TRMNL](https://github.com/JerryWoof/MeteoVerdict-TRMNL) is built on
these files: today and tomorrow, the next 24 hours, five days or the weekend for one okres on a TRMNL
e-ink display, from the combined forecast (`okresy`) or the MeteoVerdict AI (`ai/okresy`, experimental), and optionally one obec (`ai/obce/{okres}/{id}.json` or `obce/{okres}/{id}.json`) as a second polling URL. It uses `forecast.hourly` and `forecast.parts`, including `sunrise`,
`sunset` and `sunshine`, so changes to those fields should keep it in mind.

## How they are made

`web/scripts/build-api.mjs` (part of `npm run build`, logic in `web/src/api.js`) writes
them from the data the pages use: `outlook.json` and `outlook-hourly.json` (published
with each run of the forecast), `forecast/<okres>.json` and `90d/okres/<variable>.json`
(`mvd aggregate`, daily). The Pages workflow runs after the Daily and the ČHMÚ archive
workflows and takes the newest published forecast. The okres files are about 3.4 MB in total, 25 kB per okres (the AI files add 21 kB per okres); the obce files about 13 kB per obec.

## Terms

CC BY-SA 4.0: credit MeteoVerdict, Open-Meteo.com (model data, CC BY 4.0; UK Met Office
CC BY-SA 4.0) and ČHMÚ (observations, CC BY 4.0) — the `attribution` field has the text —
and share derived data alike. Not an official forecast; whether the combination beats
the best single model is tested daily on a still short history (`blend-test.json`,
roadmap 6.4). Please fetch at most once an
hour.
