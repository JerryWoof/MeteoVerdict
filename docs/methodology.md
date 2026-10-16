# Methodology

How MeteoVerdict decides which weather model forecasts Czechia best, and what the
results can and cannot tell you. The technical details and the evidence behind each
data claim are in [data-sources.md](data-sources.md); this page explains the method
and its limitations.

## The question

For each place in Czechia (a station, an okres, a kraj, an elevation class, the whole
country) and each weather element: which model's forecast for the next days was
closest to what ČHMÚ measured?

## Observations

- **ČHMÚ climatological open data** (CC BY 4.0), about 470 automatic stations with
  10-minute data: 2 m temperature and 10 m wind at the full hour, hourly precipitation
  as the sum of the six 10-minute values (it equals ČHMÚ's own hourly total).
- **About 280 manual rain gauges** with one daily total each, stamped 06:00 UTC by ČHMÚ
  (the 24 hours after that time).
- Values ČHMÚ marks as suspect, poor or missing are dropped, as are physically
  implausible ones. Estimated values are kept (a scoring option can exclude them).
- The last few days come from ČHMÚ's unchecked `now/` files; once ČHMÚ publishes the
  checked month, it replaces them and the scores are recomputed.

## Forecasts

- From the **Open-Meteo Previous Runs API** (CC BY 4.0): for each model the value it
  predicted for a given hour 1, 2, … 5 days earlier (`_previous_dayN`, "D+N").
- 19 models, every one Open-Meteo has for all of Czechia with an archive: ČHMÚ ALADIN
  (1 km and 2.3 km), DWD ICON-D2, ICON-EU and ICON global, ECMWF IFS HRES, IFS 0.25° and
  AIFS, NOAA GFS and AIGFS, UK Met Office global, Météo-France ARPEGE Europe and World,
  GeoSphere Austria AROME, KNMI and DMI HARMONIE-AROME, ECCC GEM Global, JMA GSM and CMA
  GRAPES (the last eight added in October 2026). Each is used for the lead days its
  archive fills, measured live (the high-resolution models only reach D+1 or D+2).
- Requested at each station's coordinates **and elevation**: Open-Meteo picks the grid
  point and corrects temperature for the height difference.
- The D+N archive is fetched in complete 14-day windows (the cost of a request does not
  grow up to 14 days), so on its own it is 14-20 days behind. The **most recent days**
  are scored from the same forecasts rebuilt from the single runs (below), at the ~100
  stations of the run-by-run verification, until the backfill delivers their window.

### Fresh scores from the single runs

`_previous_dayN` at an hour is the value of the newest run that started at least 24·N
hours before it. We store every 00, 06, 12 and 18 UTC run of every model at ~100
stations anyway (for the lead-hour scores), so the daily run rebuilds D+1 … D+5 for
the last 30 days from them (`meteoverdict.fresh`) and scores the days the backfill has
not reached; the scores say which source they come from (`source`: `previous_runs` or
`single_runs`). When the backfill window arrives, its forecasts (at all ~500 stations)
replace the rebuilt ones. The ranking and the weights and bias corrections of our
own forecast (90-day okres scores) thereby reach yesterday instead of two to three
weeks ago, which matters most for the bias correction when the weather pattern
changes; the scores of `meta.json` are dated accordingly.

Checked on 2026-10-16 against the Previous Runs API (11 stations on 14-15 October for
the 11 models then in the single runs at D+1 and D+2, with observations; 5 stations on
16-18 October for all 19 models, D+1 to D+5 as far as the runs since 13 October
reach): at every hour we score temperature and wind on (each model's native hours) the
two sources are **identical**, and so were the D+1/D+2 temperature and wind scores
(MAE difference 0.000 °C and m/s). Three details of Open-Meteo's archive had to be
matched, all found in this comparison:

- ICON-D2, GeoSphere AROME and DMI HARMONIE also have runs at 03, 09, 15 and 21 UTC in
  the archive, and KNMI HARMONIE hourly runs, which the 6-hourly single runs lack: for
  them only the hours where a 00/06/12/18 UTC run is the newest are rebuilt (all four
  synoptic hours among them), so their daily precipitation and maximum on fresh days
  come only with the backfill.
- The archive takes UK Met Office D+2 from the 00 and 12 UTC runs only (the 06 and 18
  UTC runs are not used beyond D+1 there).
- Hours between a 3- or 6-hourly model's outputs are interpolated over the stitched
  runs in the archive and within the run in the single runs; they differ (up to 3.3 °C),
  but they are not scored. Daily precipitation of those models is summed from the
  interpolated hours and can differ a little (AIFS: 0.09 mm in MAE over 11
  station-days; IFS 0.25°: 0.02 mm; all others 0).

A run we have not fetched (yet) leaves its hours out rather than falling back to an
older run, and D+5 has only the synoptic hours (single runs end at 120 hours). The daily
run logs how both sources agree wherever they overlap (the last days of every backfill
window), so the check repeats itself.

## Pairing forecasts and observations

- **Temperature and wind:** ranked at 00, 06, 12 and 18 UTC, the hours at which every
  model has its own output. Some models write output only every 3 or 6 hours (all
  hours for AIFS and IFS 0.25°, longer lead times for ICON-EU, IFS HRES, GFS and UKMO)
  and Open-Meteo interpolates the hours in between; scoring an interpolated hour would
  judge the interpolation, not the model, and comparing models over different hours of
  the day would favour some of them. Errors at every native hour are kept too, for
  information.
- **Precipitation:** hourly for hourly models, 3- or 6-hour sums otherwise, and two
  daily totals for every model: the **UTC day** (automatic stations) and ČHMÚ's
  **climatological day from 06 to 06 UTC** (automatic stations and the manual gauges).
- **Extremes:** the daily maximum of the hourly temperature (only models with hourly
  output at that lead day) with **heat days** of at least 30 °C, and **heavy
  precipitation** days of at least 20 mm.
- **Time of day:** the temperature at 00, 06, 12 and 18 UTC on its own, where every
  model has native output.

## Run-based verification by lead hour

The D+N scores answer "how good is the forecast made about N days earlier", using
Open-Meteo's `_previous_dayN` (for each hour, the run at least 24·N hours older). That
is fair across all models but blurs the first hours of a forecast: D+1 for a
temperature at 12 UTC is a run from 24 to 30 hours earlier, never a run from this
morning. Meteorologists verify run by run instead, and so do we:

- **Every model**, from Open-Meteo's **Single Runs API** (free, non-commercial tier):
  each 00, 06, 12 and 18 UTC run since 2026-06-23 (the first run with ALADIN), up to
  120 hours ahead, at about **100 stations** (at least one in every okres, plus the
  mountain stations; [the rule](data-sources.md#the-station-subset)), at the station's
  elevation like the D+N scores. Collected four times a day; older runs are filled in
  as the call budget allows ([budget](data-sources.md#open-meteo-budget)).
- Each lead hour is compared with the ČHMÚ observation at its valid time (run start +
  lead): H+6 of the 06 UTC run is the forecast for 12 UTC. Temperature and wind are
  instant values; precipitation is the hourly amount (mm in the hour ending at the
  valid time).
- Only a model's **own output hours** count: AIFS every 6 hours, IFS 0.25° every 3, and
  ICON-EU, IFS HRES and UK Met Office every 3 hours late in their runs (hourly
  precipitation only where the output is hourly), for the same reason as at the D+N
  scores: the hours in between are Open-Meteo's interpolation.
- **Fair set:** at each lead hour, only the models that reach it are compared, and only
  on the runs and stations that every one of them has. The set of models therefore
  **shrinks with the lead hour**: ICON-D2 ends at 48 h, AROME at 60 h, ALADIN at 72 h,
  ARPEGE at 102 h, UK Met Office's 06 and 18 UTC runs at 60 h. Pooled over the four run
  hours a model must reach the lead in each of them; per run hour (00 or 12 UTC) the
  longer runs show. Models whose single-run archive starts later (ALADIN) or that miss a
  run limit the common sample for everyone at the leads they reach.
- MAE, bias and RMSE (and hits, misses and false alarms for ≥ 0.1 mm in an hour) by
  lead hour H+1 … H+120, for Czechia (all runs and each run hour). The page draws all
  models, the three best over the hours bold (by their mean rank among the models
  compared at each hour, which is fair to the short models), ALADIN dashed.

**ALADIN from our own archive** is still verified the same way (H+1 … H+72, both
domains on the same runs and stations, ~290 stations, values at the nearest grid point
**without** elevation correction) and published as `leads-aladin.json`, but no longer
drawn: the all-model chart takes ALADIN from Open-Meteo, so all models are processed
alike. The archive remains our check of Open-Meteo's ALADIN and records when ČHMÚ
published each run.

What it is not:

- **H+1 is not what anyone gets.** ČHMÚ publishes an ALADIN run only about 3 to 4.5 hours
  after its start (measured: 00 UTC → ~03:30, 06 UTC → ~10:25, 12 UTC → ~15:15, 18 UTC →
  ~22:25). By then H+1 to H+3 (or H+4) are in the past. With a run every 6 hours, the
  freshest ALADIN forecast a user can actually hold is between about 3 and 10.5 hours
  old, so "the next hour" really means H+4 to H+11 of some run. The chart shades the
  unpublished hours (measured for ALADIN only; the other models have similar delays,
  which we do not measure). A score of what a user could actually see (always the
  newest run published before the time of use) needs the publication time, which our
  ALADIN archive records from 2026-10-13 on; it is not computed yet.
- **Short history.** The ongoing collection starts in October 2026, and older runs fill
  in at about one a day until the backfill has finished and its budget moves here. For
  weeks the numbers rest on few runs and few weather regimes; long leads rest on fewer
  runs than short ones (a run's H+120 is verified five days later), and pooled run
  hours mix the time of day into the lead hour (H+6 is 06, 12, 18 or 00 UTC).
- **100 stations**, not all ~500: enough for Czechia as a whole, too few for kraje.
- The newest days use ČHMÚ's unchecked `now/` observations, like the D+N scores.

## Event skill for farmers

Farmers decide on yes/no questions: cover the crops tonight, postpone spraying, secure
the polytunnel. So the same single runs are also verified as **events** (`mvd farm`,
`farm.json`, the section "For farmers" on the comparison page):

- **Frost**, per station and **night** (18:00 to 09:00 Prague time, 16 hourly values; 15
  or 17 when the clocks change): the night's lowest hourly 2 m temperature ≤ 0 °C and
  ≤ −2 °C. The model's minimum is taken over its own output hours in the night (3- and
  6-hourly models see fewer hours, as their users do). A night belongs to the lead bin of
  its end (09:00): the 12 UTC run's coming night ends at H+19, so H+13–24 is "tonight,
  from today's midday run". This is air frost at 2 m; ground frost is often colder.
- **Gusts**, per station and **3-hour block** (00–03, 03–06, … UTC): the strongest gust
  ≥ 10, 15 and 20 m/s. Observed: ČHMÚ's `Fmax` (maximum gust in each 10 minutes), the
  largest of the 18 values; forecast: Open-Meteo's hourly gust (maximum of the preceding
  hour) at the model's own output hours in the block. Blocks rather than single hours,
  so a gust ten minutes early does not count as both a miss and a false alarm.
- **3-hour rain**, the same blocks: ≥ 0.5, 2 and 5 mm.
- **Lead bins** H+1–6, 7–12, 13–24, 25–48, 49–72 and 73–120 (by the end of the night or
  block). **Fair set** as above: in each bin only the models whose runs cover the whole
  bin (and, for blocks, have at most 3-hourly output there) are compared, on the nights
  and blocks that all of them have. AIFS has no gusts; 6-hourly output is not scored in
  3-hour blocks.
- Hits, misses, false alarms and correct negatives give the **POD** ("caught 8 of 10
  frosts"), the **FAR** ("3 of 10 warnings were false"), the CSI, the **ETS** (the CSI
  corrected for chance hits; the page colours it) and the frequency bias (warnings per
  event). With fewer than **20 observed events** in a bin the page warns that the numbers
  are mostly chance, which for −2 °C, 15 and 20 m/s and 5 mm will be the case for months.

Limits: one season of runs at most, about 100 stations, observed gusts only from
15 October 2026 (when `Fmax` was added) and forecast gusts only in runs fetched since
then; events cluster in a few weather situations, so neighbouring stations and blocks
are not independent.

## Metrics

- **MAE** (mean absolute error) ranks the models. **Bias** (forecast minus observed)
  and **RMSE** are reported too.
- Precipitation and heat events (at least 0.1, 5 and 20 mm a day; at least 30 °C) get
  the **probability of detection**, the **false alarm ratio** and the **equitable
  threat score**.
- Scores are kept as daily sums per station and model, so any region and period is
  summed first and the metric computed once.

## Fair comparison

- Within each time window, variable, lead day and region, only the station-days that
  **every model present in that region** has forecasts for are used, so all models of a
  region are compared on the same stations and days. Models whose archive starts later
  (ALADIN: June 2026) or has gaps get the same days as the rest. The price: the "all
  time" window at D+1 and D+2 only starts when ALADIN's does.
- Where a model never reaches some stations (ICON-D2 at six stations in the Beskydy),
  those stations are left out of their regions' comparison for every model; on their own
  they are still compared among the other models.
- **Models added later** (eight in October 2026) are fetched for the newest days first.
  Until their history is filled in, the windows that reach further back (all time,
  seasons) are limited to the days they have, like ALADIN's late start, and gaps of
  one model (AIGFS before July 2026, CMA GRAPES in autumn 2025, UKMO) drop those days
  for every model of the region. The single-run comparison likewise uses only runs that
  every model reaching a lead hour has.
- A region is ranked only with at least **3 stations**. An okres with fewer of its own
  borrows the nearest stations of its neighbours (at most 30 km beyond its border) up to
  3, and the map says how many. So every okres has a ranking, but for a third of them it
  partly describes the surrounding area.
- Windows: the last 90 days, the current season, all time, and each season over all
  years (all winters, springs, summers, autumns). "All time" starts with the oldest day
  scored so far and grows as the backfill fills in history back to January 2024 (ALADIN
  only from June 2026); until then it can cover the same days as the last 90 days. The
  web pages show every window's real dates and number of days, and mark windows that
  are still the same as the 90-day one.

## Ranking and uncertainty

- Models are ordered by MAE. To tell real differences from luck, whole **days** are
  resampled 1,000 times (all stations of a day together, because errors on one day are
  correlated across the country) and the MAE difference to the best model gets a 95 %
  interval.
- A model whose interval includes zero is **tied with the best** ("≈" on the comparison page);
  the best model is a **clear winner** only if nobody is tied.

## Baseline: the mean of all models

The plain average of all models (at least 3 per hour) is scored like a model, but not
ranked. It is compared with the best single model instead: if the average often wins,
picking any single model is worse than averaging them.

## Our own forecast (roadmap 6.2, 6.3, 6.4)

The forecast page combines, for one okres, the current forecasts of all models from the
Open-Meteo Forecast API at a point inside the okres. Each model is weighted by how well
it did there over the last 90 days (inverse of its error variance), and temperature and
wind are corrected by its mean error there; precipitation is weighted but not
corrected. The weights are shrunk towards a plain mean while there are few scored days
(half-way after 30 days), the bias correction much less (half-way after 5 days: a
model's mean error is stable, and leaving half of it in cost 7–10 % of wind MAE). Hours in the next 24 h use the D+1 weights, later hours those
of their lead day (up to D+5), and models that do not reach an hour are left out with
the other weights rescaled; a model that ends early fades out over its last 3 hours, so
the curve does not jump. The page draws, next to the combination, the model ranked
best in the okres for each day of the forecast (it can be a different model on D+1 and
D+3), and lists the largest weights of every lead day. Precipitation weights come from daily totals but are
applied to hourly values. Details: [data-sources.md](data-sources.md#combination-weights-roadmap-62).

How this compares with operational practice (Bureau of Meteorology OCF, NOAA's
National Blend of Models, MeteoSwiss) and what still has to be tested:
[forecast-research.md](forecast-research.md).

The forecast map (`tv.html`) shows the same combination for every okres, made twice a
day by `mvd outlook`: by part of day, with the probability of precipitation (calibrated,
below) and a symbol; cloud cover and sunshine there are the mean of the models
corrected against ČHMÚ observations ([below](#sunshine-cloud-and-gusts)).

### Probability of precipitation and heavy rain (`meteoverdict.rain_calibration`)

The raw probability, the share of models with at least 0.2 mm in a 6-hour part of
day (each model counting the same), rates rain too likely at every level. Every night
`mvd daily` refits a calibration on the verified 6-hour cases of the last 90 days and
publishes it as `rain-calibration.json` (release `data-latest` and the site data); `mvd
outlook` uses it for every part of day:

- **Cases:** okres × part of day × lead day 1–5, from the stored D+N forecasts at the
  stations (`fc/`) and the hourly station precipitation (`obs/`). A model's value is
  the mean of its 6-hour totals at the okres's stations, the observation the mean of
  the stations with all 6 hours. Only cases with at least 3 models.
- **p_L2:** one pooled logistic regression (L2 penalty as scikit-learn's
  `LogisticRegression(C=1)`, fitted by Newton steps in numpy) of "≥ 0.2 mm observed"
  on: the Brier-weighted share of wet models (each model weighted by 1 / its Brier
  score for rain or no rain at that lead day, normalised to a mean of 1 and shrunk
  towards equal weights by days / (days + 30)); the share with ≥ 1 mm; √mean and √max
  of the model totals; the share of wet values over all models in the okresy whose
  forecast points are within 40 km (the okres included, about 4.5 okresy) and √ of
  the mean over the models of each one's largest total there; indicators for part of
  day and lead day. Not per lead day: separate fits were worse.
- **Published:** `rain_probability = 0.5 · p_L2 + 0.5 · share`. The fitted part alone
  follows the training period's climate and was pulled too dry when the test period
  turned wetter; the half with the raw share hedges against that.
- **Symbols:** `rain` (sleet, snow) unchanged, by the raw share ≥ 50 % and ≥ 0.3 mm;
  `showers` at a calibrated probability ≥ 40 % (30 % on the raw share before).
- **Heavy rain:** an extended logistic regression (Wilks 2009: thresholds 0.2, 1 and
  5 mm stacked with √threshold as a predictor, plus the share of models with ≥ 5 mm
  and √ of their 90th percentile) gives `heavy_rain_probability`, P(≥ 5 mm in the
  part of day); `heavy_rain` flags it at the probability with the best ETS on the
  training cases (0.2–0.3 so far). For a whole day: the highest of its parts.
- **Fallbacks:** fewer than 30 days of cases, a calibration older than 14 days, or a
  case with fewer than 3 models: the raw share and the old showers rule, and the
  heavy-rain fields are null. Whole days keep the raw share. A model without a Brier
  score yet weighs 1.

**Out of sample** (forecasts of 10 Aug – 30 Sep 2026, 11 models, 77 okresy; test
13–30 Sep, refitted on 13, 19 and 25 Sep on the days up to 5 days before; 95 %
intervals from a bootstrap over days):

| Okres level, 26,334 test cases | Raw share (before) | Calibrated blend |
|---|---|---|
| Brier score, P(≥ 0.2 mm) | 0.0763 | **0.0683** (10.5 % lower [0.8, 21.0]) |
| Brier skill vs. test climatology | 0.458 | 0.515 |
| Mean probability (observed frequency 0.170) | 0.214 | 0.178 |
| Brier score by lead day D+1 … D+5 | | 12, 14, 6.5, 6, 14 % lower |
| ETS, any precipitation symbol (rain or showers) | 0.431 (bias 1.62) | **0.504** (bias 1.17), +0.075 [+0.036, +0.119] |
| P(≥ 5 mm): ROC area (raw share of models ≥ 5 mm) | 0.772 | 0.952 (Brier +1 % [−8, +7]) |
| Heavy-rain flag, ETS (frequency bias) | "any model ≥ 5 mm": 0.208 (2.14) | 0.190 (1.08) |

The same holds with single-point model values (as the outlook asks Open-Meteo for one
point per okres; −10.1 %) and with the okres forecast points rather than station
centroids for the 40 km neighbourhood (−10.4 %). Weighting cases by age (half-life
14 days) did not help, so all days of the window count the same. The heavy-rain flag
ranks events far better than the raw share but its Brier score is no better; it fires
about as often as heavy rain falls, while "any model ≥ 5 mm" fires twice as often for
a slightly higher ETS. Risks: only August–September data so far (winter rain and snow
will change the coefficients; the nightly refit follows with a 90-day lag), and the
showers threshold of 0.40 was the best of 0.30/0.35/0.40 on the same test period.

### Does it beat the best single model? (roadmap 6.4)

`mvd blend-test` (run daily, shown at the top of the comparison page) replays the
combination on past days **out of sample**:

- For day *d* at lead day *N*, the weights, bias corrections and the okres's best
  model come only from the okres scores of the 90 days ending on *d − N*: what the
  daily run had published when that D+N forecast was made. Same code and shrinkage
  as the live forecast.
- The combination is applied to the models' stored D+N forecasts at the okres's
  stations (borrowed ones included) and scored like the mean of all models:
  temperature and wind at 00, 06, 12 and 18 UTC, precipitation as UTC-day totals, on
  the station-days every model has.
- It is compared with **the best model at the time** (the okres's rank-1 model in that
  training window, chosen anew every day: what a user following our ranking would have
  used), the **best model in hindsight** (each okres's model with the lowest MAE over
  the whole test: an upper bound nobody could pick in advance), the mean of all models
  and every single model. Czechia sums the 77 okresy.
- 95 % intervals of the MAE difference to the best model at the time come from the
  same day bootstrap as the ranking. **Warm-up:** an okres is tested only after 14
  scored training days.

**Result so far** (24 test days, 7–30 September 2026, after 14 warm-up days; Czechia;
negative = our forecast has the smaller MAE; 95 % interval in brackets):

| | D+1 | D+2 | D+3 | D+4 | D+5 |
|---|---|---|---|---|---|
| Temperature (°C) | −0.02 (−0.06…+0.02) | **−0.05** (−0.09…−0.01) | **−0.09** (−0.13…−0.04) | −0.04 (−0.10…+0.03) | **−0.12** (−0.26…−0.01) |
| Wind (m/s) | **+0.03** (+0.00…+0.06) | +0.03 (−0.01…+0.07) | −0.01 (−0.03…+0.02) | −0.03 (−0.06…+0.00) | **−0.13** (−0.16…−0.10) |
| Precipitation (mm/day) | **−0.25** (−0.49…−0.08) | **−0.20** (−0.41…−0.07) | **−0.28** (−0.54…−0.08) | **−0.18** (−0.31…−0.06) | **−0.26** (−0.60…−0.02) |

So far our forecast is never clearly worse than the model a user of the ranking would
have picked, except wind at D+1 (by 0.03 m/s against DWD's ICON models),
and clearly better for daily precipitation at every lead day and for temperature at
D+2, D+3 and D+5. For precipitation it is about as good as the plain mean of all
models, and both beat the per-okres "best" model, partly because that choice jumps
between models on a short, noisy history (probably). The best model in hindsight is still better
for precipitation and wind at D+1–D+2: a fixed, well-chosen model can do better, but
nobody knows it in advance. **This rests on 24 autumn days and is not yet a verdict**:
intervals ignore that consecutive days are alike (so they are too narrow), and the
weights themselves had at most 37 days of scores behind them. The test is repeated
every day as history grows. Not yet done: training windows of 30 and 45 days and a
decaying average (roadmap 6.4); with under 45 days of history they would be almost
the same as 90 days.

### Frost: night minimum, frost and ground frost

The models' night minima are too warm (by 1.4–2.3 °C at the stations in September
2026, most on clear, calm nights), so they almost never forecast frost (POD ≈ 0, see
the event skill above). The forecast map's data (`outlook.json`, `mvd outlook`) therefore
carries a separately corrected **night minimum** for the night 18–06 UTC, on the
`night` and `day` rows of the date the night ends (`meteoverdict.frost`):

1. **Per model and lead day:** `fmin − b[model, lead]`, the model's mean error of the
   night minimum over the last 60 nights at all stations (D+N forecasts `fc-YYYY-MM`
   against ČHMÚ's `TMInoc`, the 2 m minimum 18–06 UTC), then the plain mean of the
   models (leads beyond D+3 use the D+3 bias).
2. **Per station:** `− b_station`, the station's mean error left after 1., over the same
   nights, shrunk by `n / (n + 10)` and applied in full (half strength was clearly
   worse). Station biases are stable (correlation 0.93 between two halves of the
   season) and differ more within an okres (0.95 °C) than between okresy (0.59 °C).
   A split by forecast wind (< 2 m/s or not) did not help in our validation and is off.
3. **Clear, calm nights:** `− (1.33 − 1.12 · cloud − 0.36 · min(wind, 5))` with the
   night means of the models' own cloud fraction (not the corrected cover of the map) and wind (m/s): about
   −1.0 °C for a clear, calm night, +1.4 °C for an overcast, windy one. These are the
   values of the research sample (Open-Meteo Previous Runs, 16 stations, 1–13 April and
   1–14 October 2026; bootstrap 95 % ranges 1.02–1.68, −1.98…−0.45, −0.53…−0.18);
   `frost.json` records where they come from. The outlook archives its models' nights
   at the okres points (`outlook-nights-YYYY-MM.parquet` in `data-YYYY-MM`, no extra
   calls); once 30 nights of the last 45 days have observations, `mvd frost-fit` refits
   the three numbers there on what is left after 1. and 2.

The **okres minimum** (`night_min`) applies 1., the mean station bias of the okres and
3. at the okres point. The **coldest site** (`coldest_site`, `coldest_min`) is the
okres's station with the lowest corrected minimum: its own bias, the forecast moved from
the point's to the station's elevation by 0.65 °C/100 m (as Open-Meteo corrects for
elevation). From the okres minimum: `frost_probability` = Φ(−min / σ) with σ the error
left in training (1.4–1.6 °C), `frost` (air-frost warning) when the minimum is ≤ 1 °C
(the best CSI in every test; ≤ 0 °C catches too few, ≤ 2 °C has a FAR of 0.5–0.7), and
`ground_min`, the 5 cm minimum, = minimum − 5.0 + 1.5 · cloud + 0.35 · wind
(`ground_frost` when ≤ 0 °C; ČHMÚ's `TPM` is on average 2.9 °C below `TMInoc`, 4.1 °C
on clear calm nights, 0.5 °C overcast and windy). `mvd frost-fit` runs in the daily
workflow and writes `frost.json` to `data-latest`; without it the fields stay empty.

**Validation** (with `meteoverdict.frost`; event = observed minimum ≤ 0 °C; POD / FAR
/ CSI; MAE in °C). D+N forecasts of 11 models at 238 stations, D+1–D+3:

| Test | Forecast | MAE | bias | warn ≤ 0 °C | warn ≤ 1 °C |
|---|---|---|---|---|---|
| Train 1–20 Sep, test 21 Sep–4 Oct (9,966 station-nights × lead, 81 frost) | mean of the models | 2.42 | +1.76 | 0.00 / – / 0.00 | 0.00 / 1.00 / 0.00 |
| | + per model (1.) | 2.03 | +0.26 | 0.00 / 1.00 / 0.00 | 0.00 / 1.00 / 0.00 |
| | + per station (2.) | **1.68** | +0.26 | 0.05 / 0.33 / 0.05 | 0.17 / 0.50 / 0.15 |
| | + per station, split by wind | 1.72 | +0.28 | 0.05 / 0.43 / 0.05 | 0.16 / 0.63 / 0.13 |
| Single runs for the night 13→14 Oct (192, 10 frost), trained 1 Sep–4 Oct | mean of the models | 1.46 | +0.72 | 0.00 / 1.00 / 0.00 | 0.10 / 0.86 / 0.06 |
| | + per model | 1.57 | −0.79 | 0.20 / 0.82 / 0.11 | 0.40 / 0.75 / 0.18 |
| | + per station | **1.19** | −0.63 | 0.30 / 0.57 / 0.21 | 0.80 / 0.53 / 0.42 |

With cloud (the research sample, 16 stations, ECMWF IFS, ICON-EU, ICON-D2, ALADIN 1 km,
D+1–D+2). The default clear-calm numbers were fitted on April and October together, so
the "refit on train" rows are the honest out-of-sample ones:

| Test | per model | + station | + station + clear-calm (default) | + station + clear-calm (refit on train) |
|---|---|---|---|---|
| Train Apr → test Oct (448, 20 frost): MAE; ≤ 1 °C | 1.33; 0.45 / 0.40 / 0.35 | 1.28; 0.30 / 0.50 / 0.23 | 1.18; 0.65 / 0.43 / 0.43 | 1.28; 0.75 / 0.50 / 0.43 |
| Train Oct → test Apr (352, 145 frost) | 1.50; 0.83 / 0.25 / 0.65 | 1.46; 0.85 / 0.24 / 0.67 | 1.24; 0.90 / 0.24 / 0.70 | 1.26; 0.88 / 0.25 / 0.68 |
| Train Apr + 1–11 Oct → test 12–14 Oct (96, 20 frost) | 1.43; 0.60 / 0.40 / 0.43 | 1.39; 0.60 / 0.40 / 0.43 | 1.24; 0.80 / 0.45 / 0.48 | 1.23; 0.85 / 0.47 / 0.49 |

Ground frost (5 cm ≤ 0 °C) from the corrected minimum: CSI 0.66 Apr → Oct (POD 0.80,
FAR 0.20; a fixed −3.4 °C offset 0.55), 0.88 Oct → Apr (0.85), 0.77 on 12–14 Oct (0.79).
Frost probability, Brier score against climatology: 0.007 vs 0.008 (September test),
0.026 vs 0.043 (Apr → Oct), 0.093 vs 0.242 (Oct → Apr).

Limits: one autumn and 13 April nights; few frost nights in the tests (POD and FAR
are uncertain by about ±0.15–0.2); the corrections are learnt at the stations and
applied at the okres point (model biases there may differ); seasons differ (April-trained
corrections ran 0.5–0.85 °C too cold on the October frost nights), hence the rolling
windows. A dew-point floor did not help (observed minima fell below the forecast
18 UTC dew point on 53 % of nights), and Open-Meteo's archived runs have no
`soil_temperature_0cm`.

## Sunshine, cloud and gusts

The forecast map shows sunshine and cloud prominently (also on the TRMNL e-ink
display). The plain mean of the models was checked against ČHMÚ in a research sample:
the previous day's run (Open-Meteo Previous Runs API) of 10 models at 10 stations that
measure sunshine, cloud and gusts (Prostějov, Pardubice, Brno-Tuřany, Mošnov,
Praha-Ruzyně, Temelín, Karlovy Vary, Polom and the summits Milešovka and Lysá hora),
15 August – 14 October 2026, 610 station-days. Observations: daily sunshine `SSV`
(h) and maximum gust `Fmax` (m/s), hourly cloud cover `N` (octas × 12.5 %; 8 and 9,
sky obscured, count as 100 %). Every model over-forecasts sunshine (+2.0 to +3.9 h a
day; mean +2.8 h, worst on dull days: +4.0 h when under 2 h were measured), although
cloud cover is only about 4 % too low: Open-Meteo derives sunshine from direct
radiation above 120 W/m², which the models overdo. Gusts are too weak, mostly on the
summits (Milešovka −6.1, Lysá hora −3.2 m/s).

`meteoverdict.sun_cloud_gust` corrects the outlook's plain means:

- **Sunshine**, per okres and UTC day: `L` the astronomical day length at the okres
  point, `rel` the mean sunshine as a share of it, `c` the mean cloud cover 06–16 UTC
  (0–1); `sunshine = clip((a + b·rel + d·(1 − c))·L, 0, L)`. In shares of the day, not
  hours: an additive correction (about −3.7 h) would go negative in December. The
  hourly values are then scaled proportionally to add up to the corrected day (no hour
  above 3,600 s; an hour without sunshine stays without), so hours, parts of day,
  days and the open-data files agree.
- **Cloud cover**, every hour: `clip(a + b·mean, 0, 100)` (fitted on 06–16 UTC). The
  correction narrows the spread (about `18 + 0.76·mean`), so with the old symbol
  thresholds (25 / 70 %) "clear" would drop from 18 % to 6 % of days against 12 %
  observed. The symbols now use **30 / 65 %** on the corrected cover, which matches
  the observed shares and scores better (below).
- **Gusts**, daily maximum: `a + b·mean` plus the mean remaining error of the okres's
  representative station: the single-runs station of the okres if at most 750 m high,
  so summits (Milešovka, Lysá hora) never set an okres's correction. Neither the
  outlook nor the API shows gusts, and adding them to the outlook request would cost
  a fifth more Open-Meteo calls (~170–290 a day) with the free budget nearly used, so
  the gust correction is fitted and published in the coefficients but not yet
  applied. It is not applied to the farmers' event skill either: that verifies each
  model as published, and a correction fitted on the same observations would blur
  it.

**Fitting.** Least squares on the pairs of the last 60 days, refitted every night
(`mvd sun-cloud-gust`, workflow `sun-cloud-gust.yml`, no Open-Meteo calls): the
outlook archives the plain means it fetches anyway (release `outlook-archive`) and
they are paired, by lead day 1–5, with the nearest station at most 750 m high that
measures sunshine (within 40 km of the okres point) or cloud (within 60 km); gusts
from the 00 UTC single runs (each model's largest hourly gust of the UTC day, then the
mean) at the okres's representative station against `Fmax`. A variable is refitted
once it has 21 days of pairs (lead days with 21 days of their own get their own
coefficients); until then it keeps the **bootstrap** coefficients fitted on the
research sample (8 stations up to 750 m, all 61 days; `src/meteoverdict/data/
sun-cloud-gust.json`, with its provenance). The outlook uses a different set of
models from the research sample, which the refit absorbs. Rolling refits matter: the
research expects the bias to grow in the winter inversion season (models dissolve
low stratus too early), which an August–October sample cannot show.

**Out of sample** (the research sample, reproduced with this module: each test day
forecast with coefficients fitted on all earlier days, at least 21; 40 test days,
5 September – 14 October; 95 % intervals from a 3-day block bootstrap over days):

| Variable | Station-days (hours) | MAE plain mean | Bias | MAE corrected | Bias | ΔMAE [95 % CI] |
|---|---:|---:|---:|---:|---:|---|
| Sunshine, h/day (10 stations) | 400 | 2.78 | +2.68 | **1.58** | +0.07 | −1.20 [−1.86, −0.51] |
| Sunshine, h/day (8 stations ≤ 750 m) | 320 | 2.80 | +2.72 | **1.50** | +0.08 | −1.30 [−1.97, −0.56] |
| Sunshine via the hourly scaling (10 stations) | 400 | 2.78 | +2.68 | **1.58** | +0.07 | −1.20 [−1.81, −0.50] |
| Daily max gust, m/s (10 stations) | 400 | 1.85 | −1.25 | **1.16** | −0.06 | −0.68 [−0.84, −0.50] |
| Daily max gust, m/s (8 stations ≤ 750 m) | 320 | 1.20 | −0.47 | **1.00** | +0.01 | −0.21 [−0.31, −0.10] |
| Cloud, %, hourly 06–16 UTC | (4,399) | 14.47 | −4.71 | **13.42** | −0.73 | −1.05 [−1.59, −0.46] |
| Cloud, %, daytime mean | 400 | 10.45 | −4.71 | **8.86** | −0.73 | −1.59 [−2.25, −0.88] |

Gust events (10 stations): ≥ 15 m/s caught 25 % → 75 % of 48 events, false alarms
20 % → 18 %, CSI 0.24 → 0.64; ≥ 20 m/s 0 → 8 of 9 (nearly all on the summits). Symbols
from the daytime mean cloud (observed: 12 % clear, 43 % partly, 45 % cloudy): plain
mean with 25/70 % 18/42/40 %, hit rate 0.78, Heidke skill 0.65; corrected with 25/70 %
6/53/41 %, 0.80, 0.65; corrected with **30/65 %** 12/42/47 %, 0.81, **0.69** (hourly:
Heidke 0.51 → 0.54). The thresholds were picked on this sample, so the gain is
somewhat optimistic; the frequencies are the reason for them.

What did not help in the research: the median instead of the mean, weighting models
by past error (≤ 0.1), the best single model or top three for cloud (worse), stacking,
a 30-day instead of an expanding window, a plain ratio for sunshine (not
significant).

## Limitations

- **Which stations.** All stations are ČHMÚ's official network (40 main WMO stations,
  about 220 automatic climate, 40 mountain snow and 180 automatic precipitation
  stations, 280 manual rain gauges; no amateur stations). Ranking with only the
  automatic climate stations gives practically the same results (39 of 40 national
  rankings agree within the intervals); with only the 40 main stations, night
  temperatures are about 0.1-0.3 °C easier and the winners for night temperature and
  wind change, because the main network is better exposed and includes summits where
  every model forecasts far too little wind. Stations whose
  errors stand out (summits, frost hollows) are explained by their siting and stay in.
  Manual gauges in a month ČHMÚ has not completed can report a total after missing
  days (probably several days' rain), which makes the models look too dry there.
  Details: [station-check.md](station-check.md) (August-September 2026, 52 days).

- **Borrowed stations.** Where an okres borrows, nearness is the only criterion; a
  borrowed station may sit higher or lower than the okres itself (a hill-top station
  next to a lowland okres), which matters most for temperature.

- **Point versus grid cell.** A station measures one point; a model forecasts a grid
  cell average (1 km to about 25 km). Thunderstorm rain, valley inversions and wind in
  complex terrain differ within a cell, which penalises coarse models most. That is
  what users of point forecasts experience, but it is not a pure measure of model
  quality.
- **Open-Meteo's processing.** Grid-point choice, elevation correction and
  interpolation are Open-Meteo's, not the models' own; mountain stations are most
  affected. Our own ALADIN archive (nearest grid point, no correction) can later serve
  as a check.
- **Which run is "D+N".** `_previous_dayN` takes, for each hour, the run at least
  N days older. A 24-hour total therefore mixes runs (the hours after midnight come
  from a run one day later), and the native output step is inferred from the lead time
  plus a 6-hour margin, not read from the run.
- **Fresh days.** The days scored from the single runs (until the backfill reaches
  them, usually the last two to three weeks) rest on the ~100 run stations instead of
  ~500 (one per okres plus mountains), without the rain gauges, and without the daily
  precipitation of ICON-D2, GeoSphere, KNMI and DMI (see above), so on those days the
  fair comparison leaves D+1 daily precipitation out. D+4 and D+5 of the 8 models
  added on 2026-10-15 could not be compared with the archive yet (their single runs
  start then); the daily log shows the comparison once both exist.
- **Interpolated hours.** Where a model is 3- or 6-hourly we score only native hours,
  but whether Open-Meteo's hourly precipitation adds up exactly to the model's own
  period totals is **unverified**.
- **Manual gauges.** ČHMÚ stamps each total at 06:00 UTC; the actual reading time of a
  gauge is **unverified**. Manual readings arrive about a month late, so the newest
  scores cover automatic stations only. Like all gauges they catch less than falls in
  wind and snow, so models may look too wet in winter.
- **Hourly values, not extremes.** The observed daily maximum is the highest reading
  at the full hour, slightly below ČHMÚ's own daily maximum; both sides use the same
  convention.
- **Lead hours.** The run-based scores rest on a short history at 100 stations, ignore
  the hours until a run is published (3–4.5 h for ALADIN), and compare fewer models at
  longer leads (see above).
- **Model changes.** Models are upgraded over time, and long windows mix versions.
- **The mean of all models** has different members by lead day (only the global models
  reach D+5) and over time (archive starts).
- **Statistics.** The bootstrap ignores correlation between consecutive days, so
  intervals are slightly too narrow; and with many regions, variables and lead days
  some "clear winners" will be chance. Small regions and short windows are noisy, and
  the 20 mm and 30 °C scores rest on few events.
- **Wind.** We use ČHMÚ's element `F` at the full hour; how ČHMÚ averages it is not
  documented. Sensor heights are not corrected.
