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
  (1 km and 2.3 km: one 2.3 km run, also post-processed onto a 1 km grid, so the two
  are near-duplicates, see [data-sources](data-sources.md#aladin-archive)), DWD ICON-D2, ICON-EU and ICON global, ECMWF IFS HRES, IFS 0.25° and
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
replace the rebuilt ones. The ranking and the weights of our
own forecast (90-day okres scores) thereby reach yesterday instead of two to three
weeks ago; the scores of `meta.json` are dated accordingly.

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
older run (checked per hour: an older run stands in only beyond the end of the run
Open-Meteo would use), and D+5 has only the synoptic hours (single runs end at 120
hours). Since 2026-10-17 the single runs come from Open-Meteo's open-data bucket at the
models' native steps, with no interpolated hours at all: temperature and wind are
rebuilt at the native hours (the ones scored), and a 3- or 6-hour precipitation total is
spread evenly over its hours as Open-Meteo does, so daily totals are the same. The daily
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

- **Every model**, Open-Meteo's single runs: each 00, 06, 12 and 18 UTC run (scored
  from 2026-06-23, the first run with ALADIN; stored back to each model's start in
  Open-Meteo's archive), up to 120 hours ahead, at about **100
  stations** (at least one in every okres, plus the mountain stations;
  [the rule](data-sources.md#the-station-subset)), at the station's elevation like the
  D+N scores. Read from **Open-Meteo's open-data bucket on AWS** (the files the
  Single Runs API serves, kept there for three months; no API calls) at every model's
  own output steps, at each grid cell nearest to the station and with Open-Meteo's
  elevation correction, so the values equal the API's to rounding (except IFS HRES,
  where the API sometimes takes a neighbouring cell: 0.23 °C apart on average;
  [details](data-sources.md#single-runs-from-the-bucket)). The **Single Runs API**
  (free, non-commercial tier) fills what the bucket lacks and the runs older than its
  three months, as the call budget allows
  ([budget](data-sources.md#open-meteo-budget)); each run comes from one source
  (`source` in the files).
- Each lead hour is compared with the ČHMÚ observation at its valid time (run start +
  lead): H+6 of the 06 UTC run is the forecast for 12 UTC. Temperature and wind are
  instant values; precipitation is the hourly amount (mm in the hour ending at the
  valid time).
- Only a model's **own output hours** count: AIFS every 6 hours, IFS 0.25° every 3, and
  ICON-EU, IFS HRES and UK Met Office every 3 hours late in their runs (hourly
  precipitation only where the output is hourly), for the same reason as at the D+N
  scores: the hours in between would be Open-Meteo's interpolation (the runs from the
  bucket do not have them at all).
- **Fair set:** at each lead hour, only the models that reach it are compared, and only
  on the runs and stations that every one of them has. The set of models therefore
  **shrinks with the lead hour**: ICON-D2 ends at 48 h, AROME at 60 h, ALADIN at 72 h,
  ARPEGE at 102 h, UK Met Office's 06 and 18 UTC runs at 60 h. Pooled over the four run
  hours a model must reach the lead in each of them; per run hour (00 or 12 UTC) the
  longer runs show. Models that miss a run limit the common sample for everyone at the
  leads they reach; a model with fewer than 80 % of the period's runs (single runs
  fetched only since it was added) is left out until it has them (`short_record` in
  `leads.json`), so that it does not cut everyone's runs to its few days.
- MAE, bias and RMSE (and hits, misses and false alarms for ≥ 0.1 mm in an hour) by
  lead hour H+1 … H+120, for Czechia (all runs and each run hour). The page draws all
  models, the three best over the hours bold (by their mean rank among the models
  compared at each hour, which is fair to the short models), ALADIN dashed.

**ALADIN from our own archive** is still verified the same way (H+1 … H+72, both
domains on the same runs and stations, ~290 stations, values at the nearest grid point
**without** elevation correction) and published as `leads-aladin.json` (release data-latest only, not on the site), but no longer
drawn: the all-model chart takes ALADIN from Open-Meteo, so all models are processed
alike. The archive remains our check of Open-Meteo's ALADIN and records when ČHMÚ
published each run.

### Ranking by lead band (hours ahead)

The comparison page can rank the models by **hours ahead** as well as by D+1 … D+5
(the "Lead time" choice: *Hours ahead (from every run)* H+1–6, H+7–12, H+13–24,
H+25–48, H+49–72, and *Days ahead* D+1 … D+5). `mvd leads` writes
`leads-bands-<window>.json` (Czechia and the station kinds) and
`leads-bands-<window>-kraj.json` (kraje) for the windows `90d` (the last 90 days of
runs) and `all` (every run), from the same single runs and observations as `leads.json`
(`leads.band_rankings`):

- **Bands.** Every lead hour of the band, of every 00/06/12/18 UTC run, against the
  observation at its valid time, pooled. A day of the ranking is the day the runs started.
- **Who enters a band.** A model enters a band only if its runs reach the band's last
  hour in every run hour it has (its usual run length, from the data): ICON-D2
  (48 h) is in H+25–48 but not in H+49–72; UK Met Office (60 h at 06/18 UTC) neither.
  Models with fewer than 80 % of the runs are left out (`short_record`), as everywhere.
- **Two fair sets per band.** *Every hour* (`hourly`): the models with hourly output over
  the whole band, every lead hour of it; temperature, wind, hourly precipitation and
  gusts (the models that have gusts: not AIFS, AIGFS, JMA). *Every 6th hour, all models*
  (`6h`): every model reaching the band, only at the lead hours that are multiples of 6
  (where the 3- and 6-hourly models have their own output); temperature and wind. In
  both, only the (run, station, lead hour, variable) that every model of the set has
  are scored, so all models share the same pairs; the page has a switch between the two.
- **Metrics.** MAE, bias, RMSE; bias-corrected MAE for temperature and wind (below);
  for hourly precipitation POD, FAR and ETS at ≥ 0.1 and ≥ 1 mm in the hour (the page
  can sort by either ETS); gusts by MAE (the gust at the valid time against the observed
  hourly maximum gust).
- **Bias-corrected MAE, leakage-free** (as for D+N, [below](#bias-corrected-mae)): each
  model's mean error at the same station, band and valid hour of day over the 30 valid
  dates before the run's day (every one observed before the run started; at least 10),
  is subtracted; only where every model of the set has such a bias (`n_bc`).
- **Intervals.** As for D+N ([ranking](#ranking-and-uncertainty)): blocks of 4
  consecutive days of runs are resampled 1000 times; `tied` (the page's "≈") unless the
  95 % interval of a model's MAE minus the best one's excludes 0 and the Diebold–Mariano
  test agrees (p < 0.05).
- **Levels.** Czechia, the station kinds (main WMO stations, 23 of the ~100, vs the
  other 77) and kraje with at least 3 of the ~100 stations (all but Praha, which has 1).
  **No okres level:** with ~100 stations for 76 okresy most okresy have one station or
  none. On the page the map then colours kraje, the okres choices are disabled and say
  so, and a chosen okres becomes its kraj.
- **What each result rests on** (runs, stations, days) is shown with it; under 30 days
  it is marked *preliminary*.
- **Default.** The page opens at D+1 unless the files say otherwise: `mvd leads` sets
  `default_band` to H+13–24 once that band's 90-day ranking for Czechia rests on at least
  60 days (decided from the data each time the files are written), and the page then
  opens there (a link that names a lead keeps it). With the July–October 2026 history
  of the single runs (~375 runs, from 15 July) this is the case.

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
- **History.** Runs from 2026-07-15 on come from Open-Meteo's open-data bucket (its
  three months were harvested once on 2026-10-16); older ones from the API, together
  with the D+N history of the same days, from today into the past: back to 2026-07-01
  around early November 2026, back to 2026-04-02 (the archive's start for most models)
  around late December 2026 ([budget](data-sources.md#open-meteo-budget)). Long leads
  rest on fewer runs than short ones (a run's H+120 is verified five days later), and
  pooled run hours mix the time of day into the lead hour (H+6 is 06, 12, 18 or 00
  UTC). GEM Global's runs before 2026-08-18 are not in the bucket and come from the API
  too; until then it has fewer runs than the others in a 90-day window.
- **100 stations**, not all ~500: enough for Czechia as a whole and, for the band
  ranking, for kraje (4 to 13 stations each, Praha 1: left out); too few for okresy.
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
  frosts"), the **FAR** ("3 of 10 event forecasts were false"), the CSI, the **ETS** (the CSI
  corrected for chance hits; the page colours it) and the frequency bias (event forecasts per
  event). With fewer than **20 observed events** in a bin the page warns that the numbers
  are mostly chance, which for −2 °C, 15 and 20 m/s and 5 mm will be the case for months.

Limits: one season of runs at most, about 100 stations, observed gusts only from
15 October 2026 (when `Fmax` was added) and forecast gusts only in runs fetched since
then; events cluster in a few weather situations, so neighbouring stations and blocks
are not independent.

## Metrics

- **MAE** (mean absolute error) ranks the models. **Bias** (forecast minus observed)
  and **RMSE** are reported too.
- Precipitation and heat events (at least 0.1, 1, 5, 10 and 20 mm a day; at least
  30 °C) get the **probability of detection**, the **false alarm ratio** and the
  **equitable threat score** (1 and 10 mm since October 2026; score rows written before
  lack them and are left out of their sums until they are re-scored, which the daily
  run does for its last 100 days).
- **Bias-corrected MAE** (temperature and wind, `mae_bc`), see below.
- Scores are kept as daily sums per station and model, so any region and period is
  summed first and the metric computed once.

## Fair comparison

- Within each time window, variable, lead day and region, only the station-days that
  **every compared model present in that region** has forecasts for are used, so all
  compared models of a region are rated on the same stations and days. Gaps of one model
  (UKMO, AIGFS before July 2026, CMA GRAPES in autumn 2025) drop those days for every
  model of the region.
- **Compared** are the models with scores on at least **80 % of the window's scored
  days** (per variable and lead day). A model with a shorter record, typically one
  **added later** whose backfill has so far reached only its newest weeks, would otherwise
  cut every other model's days down to its few: on 15 October 2026 eight models were
  added with scores from 21 September only, and the 90-day comparison of the others
  (and with it the weights of our forecast) shrank from 40 days to 10. Such a model is
  listed separately ("short record so far, not ranked", `short_record` and `coverage` in
  the data files, `short_record` in `meta.json`), with its MAE over its own station-days
  among the compared ones; it is not ranked and gets no weight in our forecast. It joins
  as soon as it has 80 % of the window's days (about 3 weeks after it was added for
  the 90-day window, if its history is not filled in earlier). Where no model reaches
  80 %, all are compared as before. The same holds for every window: in the windows
  that reach further back (all time, seasons over all years) a model whose archive
  starts much later than the others' (ALADIN: June 2026, against January 2024 once the
  backfill has filled in history) is listed separately there too, while the 90-day
  window and the current season compare it with the rest.
- Where a model never reaches some stations (ICON-D2 at six stations in the Beskydy),
  those stations are left out of their regions' comparison for every compared model; on
  their own they are still compared among the other models.
- The single-run comparisons (by lead hour, farmers' events) likewise use only the runs
  that every model compared there has, and compare only the models with at least 80 % of
  the period's runs (counted over the run hours a model has: GEM Global has no 06 and
  18 UTC runs); the others are listed under `short_record` in `leads.json` and
  `farm.json` until they have them.
- A region is ranked only with at least **3 stations**. An okres with fewer of its own
  borrows the nearest stations of its neighbours (at most 30 km beyond its border) up to
  3, and the map says how many. So every okres has a ranking, but for a third of them it
  partly describes the surrounding area.
- **High sites are not in any okres.** A station more than **300 m above the median
  elevation of its okres's stations** (all stations of the station table in that okres)
  is a *high site* (`high_site` in `stations.json`): 47 of 782 stations in October 2026,
  the summits (Milešovka, Lysá hora, Praděd, Sněžka, Klínovec, Kleť, …) and a few
  ridge and plateau stations (Protivanov, Potštát). It is left out of its own okres, and
  out of an okres that would borrow it only where it also stands more than 300 m above
  *that* okres's median (since 2026-10-20; before, never borrowed): Protivanov (675 m)
  is 450 m above Prostějov's median and out of Prostějov, but 245 m above Blansko's
  (430 m) and in Blansko's pool, which has no temperature station of its own; Věšín
  (720 m) is no longer borrowed by Rokycany. In October 2026 that is 39 station-okres
  pairs in 23 okresy, 257 of the 293 temperature stations in some okres. Why: an okres ranking is read as "which model to use where
  people live", and a summit is another climate. 300 m is about 2 °C of temperature at
  the usual lapse rate, more than the models differ by, and the same margin the frost
  and gust corrections use for "not representative of the okres". Before, Milešovka
  (830 m, 620 m above Litoměřice's median) had 35 % of Litoměřice's D+1 pairs but 40 % of
  its temperature error and 70 % of its wind error (August–October 2026), so it decided
  the okres's wind ranking; leaving the high sites out changed the D+1/D+2 winner in 80
  of 770 okres rankings of the 90-day window, most in Litoměřice, Jeseník, Šumperk and
  Frýdek-Místek. The high sites stay visible: each is ranked on its own (station level;
  the okres panel lists it as "high above the okres, scored on its own"), all of them
  together in the level `high_sites` (region `high_sites`), and they remain in the kraj,
  elevation, network and Czechia levels, which describe whole areas including their
  mountains. The median rather than the okres's lowest point or a fixed elevation keeps
  mountain okresy (Prachatice, Trutnov, Klatovy) ranked on their own typical stations:
  Churáňov (1118 m) is 326 m above Prachatice's median (792 m) and out, while Kvilda
  (1059 m) and Kubova Huť (997 m) stay in. The model weights of our forecast follow the okres scores and so do not include them.
- **Wind-atypical stations are not in the okres wind rankings.** The 10 % of the other
  wind stations (19 of 194 in October 2026, e.g. Přimda, Dyleň, Brno-Tuřany, Temelín
  exposed; Teplice, Pec pod Sněžkou, Ústí n. L.-Vaňov, Králíky sheltered) whose hourly
  wind deviates most from their neighbours' (mean absolute deviation of
  `log((v + 0.3) / IDW mean of up to 8 stations within 45 km)`, 0.73 or more, from the
  hourly observations of 2026-08-01 to 10-17) are left out of every okres's *wind*
  ranking, own and borrowed (an okres still short of 3 stations borrows the next
  nearest, as above; all 77 keep a ranking). Temperature and the other variables, and the
  station, kraj, elevation, network and Czechia levels, are unchanged. Why: the okres
  ranking says which model to use where people live, and a sheltered or exposed gauge
  measures a wind the models cannot be asked to reproduce at 10 km. In a 60-day test the
  exclusion changed the winner in 58 of 385 okres wind rankings (33 clearly, outside the
  confidence interval), against 12 (6) when 19 random stations were left out. It is a
  versioned list, `src/meteoverdict/data/wind-atypical.csv`, not recomputed daily, so
  rankings do not jump with the window; the observations-only rule is documented here and
  can be re-run on a longer record.
- Windows: the last 90 days, the current season, all time, and each season over all
  years (all winters, springs, summers, autumns). "All time" starts with the oldest day
  scored so far and grows as the backfill fills in history back to January 2024 (ALADIN
  only from June 2026, see above); until then it can cover the same days as the last 90
  days. The
  web pages show every window's real dates and number of days, and mark windows that
  are still the same as the 90-day one.

## Station kinds

Most wind stations (about 170 of 210) are automatic **climate stations**, often more
sheltered than an open 10 m mast; the about 40 **main (synoptic) stations** with a WMO
number are open sites. All models over-forecast wind at the climate stations, the ones
that keep more wind near the ground (ALADIN, AROME) most, so the station mix decides
part of the wind ranking. The level `network` aggregates and ranks every variable
separately for `main` (WIGOS id `0-20000-0-<WMO>`) and `other` (all other stations),
Czechia only, with the same fair station-days and block bootstrap as the other levels; the
comparison page offers "Stations: all / main (WMO) only / other (climate)" for the
ranking table and the two charts below it. (`mvd station-check` compares these subsets in
more detail, [station-check.md](station-check.md).)

90 days to 15 October 2026, D+1 wind (MAE, m/s): at the main stations ICON-D2 1.20,
AROME 1.21, ALADIN Central Europe 1.23 (tied with the best) and CZ 1.24 (ALADIN's bias
there is 0.00, ICON-D2's −0.65); at the other stations ALADIN is 7th and
9th (1.44, bias +1.18) behind ICON-EU 0.99 and ICON-D2 1.01. At D+2 the two ALADINs are
first and second at the main stations (1.26, 1.27; ICON-D2 does not reach D+2).

## Bias-corrected MAE

A model that is always 1 m/s too windy at a station is easy to fix, and our forecast
corrects the usual errors of the models. So the
ranking table shows next to the raw MAE the **MAE once each model's usual bias is
removed** (`mae_bc`), for temperature and wind:

- For every pair (station, synoptic hour 00/06/12/18 UTC, day d, model, lead day N) the
  bias is the model's mean error at that station and hour over the **30 days ending on
  d − N − 1**: the last day whose observations were all known when the D+N forecast for
  d was made (Open-Meteo's D+1 comes from a run of day d − 1). It is never estimated on
  the day it corrects, so this is out of sample, as a real forecast would have been.
- At least 10 such days are needed; a station-hour-day counts only where **every**
  compared model of the region has a bias, so all models are compared on the same pairs.
  These are fewer than the raw MAE's (the first weeks of the history have no bias yet),
  so compare `mae_bc` between models, not exactly with `mae`.
- It comes from the per-hour score rows (`temperature_2m_HHutc`, and since October 2026
  `wind_speed_10m_HHutc`, which are not published on their own); all levels except the
  single stations (file size). It is shown, not ranked.

90 days to 15 October 2026, D+1, Czechia: wind ICON-EU 0.78, ICON-D2 0.79, the mean of
all models 0.76, ALADIN CZ 0.90 and CE 0.91 (raw 1.40); so about two thirds of ALADIN's
gap to ICON-D2 (0.35 m/s raw) is its bias, and 0.11 m/s remains. Temperature: AROME 1.09,
ICON-D2 1.11, ALADIN 1.15 (raw 1.32, 1.26, 1.34).

## Precipitation: MAE favours smooth models

Daily precipitation MAE rewards a model that spreads a little rain everywhere (a coarse
or smooth model is never far off) over one that puts a shower in the right valley but
slightly displaced (the "double penalty"). So for precipitation the ranking table can
also be **sorted by ETS at ≥ 1 mm and ≥ 10 mm a day**, with POD and FAR at the threshold
sorted by. That order is a plain sort without bootstrap intervals; days with ≥ 10 mm are
few, so those scores are noisy. In autumn 2026 ALADIN is no better by ETS at 1 mm (D+1:
0.52 against ICON-EU 0.59) and mid-pack at 10 mm.

## Ranking and uncertainty

- Models are ordered by MAE. To tell real differences from luck the days are resampled
  1,000 times with all stations of a day together (errors on one day are correlated
  across the country) and the MAE difference to the best model gets a 95 % interval.
- **Blocks of 4 days** (a circular moving-block bootstrap, `ranking.BLOCK_DAYS`): the
  resampling draws runs of 4 consecutive scored days, not single days, because the
  difference between two models persists from one day to the next (a weather regime
  favours one model for a few days). Measured on the 90 days to 18 October 2026, D+1
  and D+3, between each okres's best model and the next three: the median lag-1
  correlation of the daily MAE difference is 0.11 (okres) to 0.21 (Czechia) for
  temperature and 0.16 to 0.28 for wind, 0.07 to 0.14 at lag 2 for wind, and about 0
  from lag 3 on; for precipitation about 0 at every lag. Resampling single days ignored
  this, so the intervals were too narrow. 4 days covers the dependence with a day to
  spare; longer blocks would leave too few of them in a short window (a 30-day sample
  has 7–8). With the blocks, the intervals for temperature and wind are 14–17 % wider
  in the median (up to about 45 % for the 10 % most persistent okres comparisons);
  precipitation's are about the same. Circular means a block may run from the last day
  back to the first, so the first and last days are drawn as often as the others; in
  the seasons over all years a block can cross from one year's season to the next.
- **Diebold–Mariano test** (`dm_p`): for every model against the best one, the daily
  loss differential (scaled so its mean is the pooled MAE difference) is tested for a
  mean of 0 with a Newey–West (HAC) variance over 3 lags (Bartlett weights, the same
  dependence the 4-day blocks cover), the Harvey–Leybourne–Newbold small-sample factor
  and a normal p-value. Its HAC variance and the block bootstrap answer the same
  question in two ways; a model counts as worse only if both agree.
- A model is **tied with the best** ("≈" on the comparison page and in the README
  table) unless its interval excludes zero **and** `dm_p` < 0.05; the best model is a
  **clear winner** only if nobody is tied. On the 90 days to 18 October 2026 the new
  rule turned 85 clear okres winners (D+1, D+2) into 65, and the Diebold–Mariano test
  kept 500 of 10,164 okres comparisons tied whose interval alone excluded zero.
- **Probability of being best** (`p_best`): the share of the 1,000 resamples in which a
  model has the lowest MAE of the ranked models (a resample where models share the
  lowest MAE counts for each in part). One winner per okres hides how sure that is;
  `p_best` says it. The **map** always colours an okres with the model of lowest
  error; where that model's `p_best` is under **0.6** (`ranking.P_BEST_MIN`, `p_best_min`
  in `meta.json`) the colour is unchanged, but the tooltip and okres panel say "close call" and name the other
  close models. An okres with no ranking of its own takes its kraj's best model. 0.6 means the
  leader is best more often than all the others together, with a margin: with 1,000
  resamples the share itself is uncertain by about ±3 percentage points, and with 77
  okresy, five variables and five lead days some leads of 0.5 or 0.55 are chance. With
  the 90 days to 18 October 2026 (D+1), 58 of 77 okresy have a clear winner for
  temperature and 62 for wind, but only 10 for daily precipitation, 22 for the 06–06
  total and 31 for the daily maximum: for rain the data does not yet single out a
  model in most okresy, and the tooltip and panel say so. The two ALADINs are near-duplicates
  and split the resamples between them, so where ALADIN leads the map is often a close call;
  the okres panel names the closest model and its `p_best`.
- **Small sample** (`small_sample`): fewer than **30 scored days** in the comparison
  (`ranking.SMALL_SAMPLE_DAYS`, the same limit at which the okres panel and the
  lead-band ranking call a result *preliminary*), i.e. fewer than 8 blocks. The map
  outlines such okresy dashed. The 80 % coverage rule (above) already keeps models with
  short records out; this flag is about the whole comparison resting on a short window
  (the current season in its first weeks, a season over all years with little history).
- Only the compared models (at least 80 % of the window's days, see above) are ranked;
  a model with a shorter record is shown after the mean of all models without a rank.
- The out-of-sample check of our forecast, the lead-band ranking (`mvd leads`), `mvd station-check` and the
  monthly report use the same block bootstrap and, where they declare ties, the same
  rule.

## Baseline: the mean of all models

The plain average of all models (at least 3 per hour) is scored like a model, but not
ranked. It is compared with the best single model instead: if the average often wins,
picking any single model is worse than averaging them.

## Our own forecast

The forecast page combines the forecasts of all models for one point in each okres into
one forecast. The models are weighed by their recent scores in that okres (the public
scores described in this document) and their usual errors are corrected. The method
itself is not published. What is published:

- **The forecast files** `outlook.json` and `outlook-hourly.json`, the weights per okres
  and lead day (`forecast/<okres>.json`), the forecast for the obce (`obce.zip`), and
  the archives of past forecasts (`outlook-parts-*`, `outlook-archive-*`,
  `outlook-hindcast.parquet`).
- In those files: **a probability of precipitation** and of heavy rain, **a temperature
  range**, **frost, sky and gust** fields ([open data](open-data.md)).
- **An out-of-sample check** (`blend-test.json`, shown on the Compare page). It compares
  our forecast with the best single model and with the plain mean of all models
  ([baseline](#baseline-the-mean-of-all-models)) on past days, using for every day only
  what was known before it. The check is repeated daily as the days pass.

The scores that the forecast leans on (okres ranking, lead days, 80 % coverage rule) are
those described above; the files themselves are described in
[data-sources.md](data-sources.md).

## The same-sample comparison with MeteoVerdict AI (Compare page)

The top of the comparison page ranks, on one sample, the plain models, the mean of all
models (`blend`), our combined forecast (`combined`) and, when its
run supplies them, experimental candidates such as MeteoVerdict AI.
The Compare page's same-sample files (`compare.zip`) are published with the forecast:
one small JSON file per region (Czechia, each kraj, each okres) with, for every variable
and lead day, the ranking and the daily MAE of every series. The series are put through
`aggregate.common_days` together with the models:
within one region, variable and lead day every series has the same stations and the same
hours (temperature and wind at 00, 06, 12 and 18 UTC, precipitation as UTC-day sums),
and only a series that has a value on every day of the group is ranked. A kraj sums its
okresy and Czechia sums all of them, a series counting only on days it is compared in
every okres.

The ranking uses the rules of the honest-scoring review: block bootstrap of
`ranking.BLOCK_DAYS` days, Diebold-Mariano test, `p_best`, "tied with the best" unless the
interval and the test both show a model is worse, and "no clear winner" unless the best
series has `p_best` of at least `ranking.P_BEST_MIN` and no tie. Every series also carries
its difference to our combination (`vs_outlook`) with the same interval and test: the AI
is "better" or "worse" than our forecast only when both agree, otherwise "≈".

Two samples exist and are never mixed. The **validation sample** is the AI's out-of-sample
hindcast: it was trained on what was known at each issue day, but the model was chosen on
the same days, so its numbers are optimistic and the page says so.
The **live sample** (since the launch on 2026-10-19) is the AI's real forecasts at the okres
point against the okres mean of the stations, hourly, D+1 to D+3, with every series on the
same okres-hours; it counts as verified only from 28 measured days. Until then the AI is
marked provisional, with the number of verified hours shown.

## Limitations

- **Which stations.** All stations are ČHMÚ's official network (40 main WMO stations,
  about 220 automatic climate, 40 mountain snow and 180 automatic precipitation
  stations, 280 manual rain gauges; no amateur stations). Ranking with only the
  automatic climate stations gives practically the same results (39 of 40 national
  rankings agree within the intervals); with only the 40 main stations, night
  temperatures are about 0.1-0.3 °C easier and the winners for night temperature and
  wind change, because the main network is better exposed and includes summits where
  every model forecasts far too little wind. Stations whose
  errors stand out are explained by their siting and stay in the data; the summits and
  other high sites are scored on their own and not in the okresy (see
  [fair comparison](#fair-comparison)), frost hollows stay in their okres.
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
- **Statistics.** The block bootstrap and the Diebold–Mariano test allow for
  correlation over a few days, not for slower changes (a whole season that suits one
  model), and the Diebold–Mariano p-value uses the normal distribution, which is a
  little too confident under 30 days (flagged as a small sample). With many regions,
  variables and lead days and no correction for multiple comparisons, some "clear
  winners" and some `p_best` ≥ 0.6 will still be chance. Small regions and short windows are noisy, and
  the 20 mm and 30 °C scores rest on few events.
- **Wind.** We use ČHMÚ's element `F` at the full hour; how ČHMÚ averages it is not
  documented. Sensor heights are not corrected.
