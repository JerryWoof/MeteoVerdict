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
  (1059 m) and Kubova Huť (997 m) stay in. Our forecast's temperature and wind regression
  still trains on all pool stations including the high sites (`mos.pools`), as it was
  tested; its model weights follow the okres scores and so no longer include them.
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
  can be re-run on a longer record. Our forecast's regression is not affected
  (`high_sites_in_okres` keeps all stations for training).
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

A model that is always 1 m/s too windy at a station is easy to fix, and our combined
forecast fixes it (its regression removes each model's bias per okres and hour). So the
ranking table shows next to the raw MAE the **MAE once each model's usual bias is
removed** (`mae_bc`), for temperature and wind:

- For every pair (station, synoptic hour 00/06/12/18 UTC, day d, model, lead day N) the
  bias is the model's mean error at that station and hour over the **30 days ending on
  d − N − 1**: the last day whose observations were all known when the D+N forecast for
  d was made (Open-Meteo's D+1 comes from a run of day d − 1). It is never estimated on
  the day it corrects, so this is out of sample, as our forecast would have been.
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
- The blend test, the lead-band ranking (`mvd leads`), `mvd station-check` and the
  monthly report use the same block bootstrap and, where they declare ties, the same
  rule.

## Baseline: the mean of all models

The plain average of all models (at least 3 per hour) is scored like a model, but not
ranked. It is compared with the best single model instead: if the average often wins,
picking any single model is worse than averaging them.

## Our own forecast (roadmap 6.2, 6.3, 6.4)

The forecast page combines, for one okres, the current forecasts of all models at a
point inside the okres (from Open-Meteo's open-data bucket since 2026-10-20, read the
way the Open-Meteo Forecast API answers, before from that API). Each model is weighted
by how well it did there over the last 90 days (inverse of its error variance), and temperature and
wind are corrected by its mean error there; precipitation is weighted but not
corrected. The weights are shrunk towards a plain mean while there are few scored days
(half-way after 30 days), the bias correction much less (half-way after 5 days: a
model's mean error is stable, and leaving half of it in cost 7–10 % of wind MAE). Only
the models compared in the 90-day window get a weight: a model added recently gets
none until it has scores on 80 % of the window's days, and it does not shorten the
training of the others (on 16 October 2026 that kept 38–40 days of training instead of
10). Hours in the next 24 h use the D+1 weights, later hours those
of their lead day (up to D+5), and models that do not reach an hour are left out with
the other weights rescaled; a model that ends early fades out over its last 3 hours, so
the curve does not jump. The page draws, next to the combination, the model ranked
best in the okres for each day of the forecast (it can be a different model on D+1 and
D+3), and lists the largest weights of every lead day. Precipitation weights come from daily totals but are
applied to hourly values. Details: [data-sources.md](data-sources.md#combination-weights-roadmap-62).

### Temperature and wind: regression blend

For temperature and wind the inverse-error weights and the all-hours bias are replaced
by a small model output statistics step (`meteoverdict.mos`), refitted every day on
the forecast–observation pairs of the last 90 days at 00, 06, 12 and 18 UTC (the hours
every model has natively), per variable and lead day:

1. **Rows**: station × slot × day, only the models with a value in at least 80 % of
   the rows, and only rows where all of those have one. An okres uses the stations of
   its pool (its own, plus borrowed ones where it has fewer than three). *D* = days
   with rows.
2. **Hour-of-day bias** per okres, slot and model, shrunk towards the okres's
   all-hours bias: `B = (D·b_slot + 10·b_all) / (D + 10)`.
3. **Elevation term**: `dz` = (station elevation − mean elevation of the okres's
   stations) / 100 m; the error left after step 2 is regressed on `dz` through the
   origin, nationally per slot and model (β). The models are too slow at stations
   above their okres's average and too fast below it (wind about −0.35 m/s per
   100 m at night, −0.16 at noon); higher stations are warmer at night than the
   models say (inversions) and slightly cooler around midday. The correction is
   `C = B + β·dz`.
4. **Weights**: ridge regression of the observations on the corrected forecasts
   `f − C`, constrained to sum to 1: first for Czechia (towards equal weights,
   penalty 0.1 per row), then per okres towards the Czech weights (penalty 1 per row).
   Weights can be negative (a model that errs like a better one is subtracted).
5. **Forecast**: `Σ w · (f − D/(D+5)·C)`, wind not below 0. Between the four slots
   the correction is interpolated linearly. At the okres's forecast point `dz` is the
   point's elevation (Open-Meteo's, committed in `okres-elevations.csv`) minus the
   station mean, limited to the range of the okres's stations, and the elevation term
   counts **half** (see below).
6. **Guard (wind only)**: the regression is also fitted without the last 7 days of its
   window and scored on them against the method before (inverse-error weights,
   all-hours bias), per okres; an okres where it did worse keeps the method before.

Fallbacks: an hour where one of the regression's models has no value (or fades out)
uses the inverse-error weights with the corrections of steps 2–3, rescaled over the
models present; with fewer than 14 days of pairs, no pairs in an okres, or a guarded
okres (wind) everything is as before. The weights without a sum-to-one constraint did
better for wind at stations (−13.8 % instead of −10.9 %) but pull the forecast towards
0 without an intercept, so they are not used. The pairs include the recent days that
`mvd daily` rebuilds from the single runs (`meteoverdict.fresh`), so the regression is
as recent as the scores.

Out of sample (rolling origin, training only on days up to *d − N*, 11–30 September
2026, against the previous method on the same rows) this cut the MAE by 6.9 % for
temperature (D+1 −13.5 % … D+5 −3.7 %) and 10.9 % for wind (−9 … −12 % at every lead
day), in line with the research run it was chosen from (−7.0 %, −10.9 %; 95 %
block-bootstrap intervals −9.7…−3.3 and −12.0…−9.7; the last week, held out when
choosing it, gained as much). The gains are largest where the old all-hours bias did
worst: by night for wind, by day for temperature. Tried and not used: a bias per
station (larger gains at stations, but the forecast is for one point per okres), the
previous run as extra members, exponentially decaying training weights, a
multiplicative wind correction, only the best 3 or 5 models, and an elevation slope
per okres (it mostly learns the okres's few stations). The data cover late summer and
autumn only, so the slopes are refitted daily rather than fixed (the winter inversions
will change them).

**Stations at very different heights.** Where an okres's pool mixes lowland and
mountain stations (Chomutov: Tušimice 322 m and the borrowed Klínovec 1236 m) the
national linear elevation term over-corrects the lowland station, and wind in
Chomutov, Liberec and Nový Jičín got 10–34 % worse at stations. Tested out of sample at
the stations (11–30 Sep, the last week held out), against the method before:

| Wind, change of MAE | all days | held out | okres × lead day groups > 5 % worse |
|---|---|---|---|
| regression as specified | −12.7 % | −14.0 % | 26 of 385 |
| pools without stations > 400 m from the point's height | −6.6 % | −6.4 % | 7 |
| … > 300 m / > 500 m / no mountain stations | −5.7 / −7.0 / −7.1 % | | 4 / 13 / 7 |
| elevation slope fitted only on \|dz\| ≤ 3 | −12.4 % | −13.6 % | 20 |
| **guard (7 days, worse at all → method before)** | **−13.0 %** | **−14.4 %** | **10** |
| guard with 14 days / with a 3 % or 5 % margin | −12.9 / −13.1 / −13.1 % | | 22 / 12 / 14 |

Dropping the distant stations loses half the national gain (the mountain stations
gain most from the elevation term); the guard keeps it and removes most of the
losses (Chomutov +32 % → +9 %, Liberec +13 % → +2 %, Nový Jičín +13 % → +3 %). For
temperature the guard cost 0.8 points of the gain and only 4 groups were worse than
5 % without it, so it is used for wind only.

**The elevation term at the forecast point.** The test above scores each station with
its own elevation; the published forecast has one point per okres, often well below
the stations' mean (Trutnov −540 m, Zlín −640 m, both with mountain stations in the
pool). Checked with the station nearest each point as the truth (its forecasts and
observations, the okres's coefficients, 11–30 Sep, held out 24–30 Sep), MAE change
against no elevation term at the point (dz = 0):

| | full term, all / held out | half term, all / held out | okresy > 5 % worse (wind): full / half |
|---|---|---|---|
| Temperature | −0.6 % / **−1.5 %** [−2.2, −0.7] | −0.4 % / **−0.9 %** [−1.2, −0.5] | |
| Wind | −4.6 % / **−4.4 %** [−5.4, −3.5] | −3.5 % / **−3.3 %** [−4.1, −2.7] | 15 / 4 (of 77) |

(Only okresy whose nearest station is within 150 m of the point's height: wind −6.7 %
full, −4.1 % half, held out.) Both are clearly better than no term, so the data support
an elevation correction at the point, including Trutnov (nearest station: wind MAE
1.20 m/s without, 0.73 full, 0.70 half). The full term is a little better on average
but makes wind clearly worse in 15 okresy (Chomutov +13 %), the
half term in 4; against the okres's mean over its stations, which a single number for
the whole okres is also read as, no term is best (half +5.5 %, full +14.5 % for wind).
Half strength is the compromise used.

How this compares with operational practice (Bureau of Meteorology OCF, NOAA's
National Blend of Models, MeteoSwiss) and what still has to be tested:
[forecast-research.md](forecast-research.md).

The forecast map (`forecast.html`) shows the same combination for every okres, made twice a
day by `mvd outlook`: by part of day, with the combined precipitation amount in mm (the
weighted blend, comparable to every single model; the map, tables and panel show it) and
beside it, in the okres panel, the probability of precipitation (calibrated, below), and a symbol; cloud cover and sunshine there are the mean of the models
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
- **Fallbacks:** fewer than 30 days of cases, a calibration older than 35 days (forecasts lag ~20 days in normal operation), or a
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

### Does it beat one model used everywhere? (roadmap 6.4)

`mvd blend-test` (run daily, shown at the top of the comparison page) replays the
combination on past days **out of sample**:

- For day *d* at lead day *N*, the weights, bias corrections, the okres's best model
  and the best model for the whole of Czechia come only from the scores of the 90 days
  ending on *d − N*: what the daily run had published when that D+N forecast was made.
  Same code and shrinkage as the live forecast; the temperature and wind regression is
  fitted on the station pairs of the same window, and its corrections are taken at each
  station's own elevation. Only models with scores on at least 80 % of the window's
  scored days are trained on: the backfill fetches a newly added model newest window
  first, and a model with one 14-day block would otherwise cut every model's fair
  station-days (and with them the training) down to that block.
- The combination is applied to the models' stored D+N forecasts at the okres's
  stations (borrowed ones included; for the latest days the D+N rebuilt from the single
  runs, as the daily scores) and scored like the mean of all models: temperature and
  wind at 00, 06, 12 and 18 UTC, precipitation as UTC-day totals. The station-days are
  fair **day by day**: on each day the models compared are those with scores that day,
  so a model with part of the test period only (a newly added one, or the fresh days
  with fewer models) does not drop the other days.
- It is compared with:
  - **the best model for the whole of Czechia at the time** (`best_cz_oos`: the model
    with the lowest Czechia-wide MAE in that training window, chosen anew every day and
    used at every station). This is the headline: most people use one model everywhere.
  - **the best model in each okres at the time** (`best_oos`: each okres's rank-1 model in
    that window, a different model in every okres if need be). Harder to beat than any
    one model.
  - the **best model in hindsight** (each okres's model with the lowest MAE over the
    whole test: an upper bound nobody could pick in advance), the mean of all models,
    and **every single model used everywhere** (Czechia, each on the days it has data;
    ČHMÚ ALADIN CZ 1 km first on the page).
- Czechia sums the 77 okresy; a series counts on a day only if it is compared in every
  okres tested that day. 95 % intervals of the MAE differences (ours minus the
  competitor) come from the same block bootstrap as the ranking
  (`ranking.bootstrap_group`, blocks of 4 consecutive days). **Warm-up:** an okres is tested only after 14 scored
  training days.

On 16 October 2026 the published test briefly covered only 5 days (21–25 September):
the backfill had just delivered the eight models added on 15 October for their newest
window (21 September – 4 October), and the fair comparison over the whole period then
kept only station-days from 21 September on, both in the training windows (too few days
left for the warm-up) and in the test. The coverage rule and the day-by-day fairness
above fixed it.

**Result so far** (26 test days, 7–30 September and 14–15 October 2026, after 14
warm-up days; Czechia; negative = our forecast has the smaller MAE; 95 % interval in
brackets; bold = significant).

Against **the best model for all of Czechia at the time**, used everywhere (most often
ECMWF AIFS, DWD ICON-EU for wind):

| | D+1 | D+2 | D+3 | D+4 | D+5 |
|---|---|---|---|---|---|
| Temperature (°C) | **−0.22** (−0.26…−0.18) | **−0.26** (−0.33…−0.20) | **−0.21** (−0.32…−0.12) | **−0.12** (−0.19…−0.04) | **−0.20** (−0.27…−0.13) |
| Wind (m/s) | **−0.22** (−0.24…−0.20) | **−0.20** (−0.23…−0.17) | **−0.21** (−0.24…−0.18) | **−0.21** (−0.25…−0.17) | **−0.35** (−0.41…−0.30) |
| Precipitation (mm/day) | **−0.27** (−0.64…−0.01) | **−0.25** (−0.68…−0.01) | −0.04 (−0.38…+0.27) | −0.02 (−0.27…+0.26) | −0.32 (−0.77…+0.03) |

Against **ČHMÚ ALADIN CZ 1 km** used everywhere (it reaches D+2): temperature −0.27 °C
(−20 %) at D+1 and −0.19 °C (−13 %) at D+2, wind −0.54 and −0.52 m/s (−40 %, −37 %),
precipitation −0.20 and −0.30 mm (−17 %, −21 %); all significant. Of all 196 model ×
variable × lead day comparisons ours is significantly better in 168 and not
significantly different in 28 (all precipitation), worse in none.

Against **the best model in each okres at the time**:

| | D+1 | D+2 | D+3 | D+4 | D+5 |
|---|---|---|---|---|---|
| Temperature (°C) | **−0.17** (−0.20…−0.15) | **−0.17** (−0.20…−0.13) | **−0.19** (−0.23…−0.16) | **−0.13** (−0.18…−0.07) | **−0.19** (−0.26…−0.14) |
| Wind (m/s) | **−0.17** (−0.20…−0.16) | **−0.18** (−0.20…−0.15) | **−0.21** (−0.23…−0.18) | **−0.21** (−0.25…−0.17) | **−0.34** (−0.38…−0.31) |
| Precipitation (mm/day) | **−0.26** (−0.51…−0.07) | **−0.21** (−0.42…−0.07) | **−0.28** (−0.55…−0.08) | **−0.18** (−0.31…−0.06) | **−0.28** (−0.63…−0.02) |

For precipitation one well-chosen model for the whole country does about as well as the
per-okres choice or better (its choice is steadier), so at D+3–D+5 our advantage over it is not
significant.

MAE of the combination with the regression blend against the method before it (same
test): temperature 1.221 → 1.066 °C at D+1 (−12.7 %), −8.5 %, −6.5 %, −4.4 % and
−3.9 % at D+2…D+5; wind 0.949 → 0.818 m/s at D+1 (−13.8 %), −12.7 %, −12.7 %,
−11.8 % and −13.1 %. Of the 385 okres × lead day groups 4 got more than 5 % worse for
temperature and 9 for wind (Chomutov up to +12 %, Semily, Nový Jičín, Prostějov,
Hodonín; 26, up to +34 %, without the wind guard).

Our forecast is clearly better than the per-okres pick for every variable and lead day (before the regression blend it was worse for
wind at D+1, by 0.03 m/s against DWD's ICON models, and not significantly different at
several other lead days). For precipitation it is about as good as the plain mean of all
models, and both beat the per-okres "best" model, partly because that choice jumps
between models on a short, noisy history (probably). The best model in hindsight is still better
for precipitation: a fixed, well-chosen model can do better, but nobody knows it in
advance. For temperature and wind the test scores the combination at the stations, with
each station's own elevation in the correction; the published forecast gets the
elevation term only for its one point per okres, so part of the gain (the elevation
term) shows up there only as far as the point differs from the okres's stations. **This rests on 26 autumn days and is not yet a verdict**:
intervals ignore that consecutive days are alike (so they are too narrow), and the
weights themselves had at most 40 days of scores behind them. The test is repeated
every day as history grows. Not yet done: training windows of 30 and 45 days and a
decaying average (roadmap 6.4); with under 45 days of history they would be almost
the same as 90 days.

### The range around the temperature (`mvd blend-interval`)

The combined temperature comes with an 80 % range (`temperature_2m_lo`, `temperature_2m_hi`
in `outlook-hourly.json`, the open-data files and `forecast/models/<okres>.json`; a grey
band and a "±" line in the tooltip of the hourly chart of `forecast-detail.html`). It is
**the forecast's own recent errors, not the spread of the models**: an 80 % interval of the
models' spread (AI experiment E5, October 2026) held the measurement in 56 % of cases.

`mvd blend-interval` (daily, after `mvd hindcast`) rebuilds the combined temperature out of
sample for past days at the okres's stations, as the hindcast does (weights, corrections and
regression trained on the scores up to the day before the forecast was made), and keeps the
error `observed - combined` at 00, 06, 12 and 18 UTC (`blend-errors.parquet` in the release
`outlook-archive`, 100 days). For every okres, lead day (1-5) and hour the range is the 7th and
93rd percentile of the errors of the last 30 target days; the okres's value is shrunk towards the
one for the whole of Czechia by `n / (n + 200)` (`n` = its errors), the whole of Czechia is
used where an okres has fewer than 20. Between the four hours the offsets are interpolated
linearly in the hour of the day; the outlook adds them to the combined temperature of each
hour (lead day as for the weights). The file `blend-interval.json` (release `data-latest`) is
ignored by the outlook when older than a week.

**Check, out of sample** (25 668-33 492 station-hours per lead; for each target day only
errors of days up to the day before the forecast was made, at least 14 days of them; 26 target days,
23 September - 18 October 2026, errors from 8 September):

| lead | held (target 80 %) | mean width |
|---|---|---|
| D+1 | 81.6 % | 4.0 °C |
| D+2 | 79.1 % | 4.5 °C |
| D+3 | 76.8 % | 5.0 °C |
| D+4 | 77.5 % | 5.6 °C |
| D+5 | 78.9 % | 6.0 °C |

Day (06, 12 UTC) 83 / 81 / 79 %, night (00, 18 UTC) 80 / 77 / 74 % at D+1-3; lowland 83 / 81 / 79 %,
mountain (stations from 600 m) 79 / 75 / 72 %. The plain 10th-90th percentile held only
70-75 %: the last 30 days' errors are smaller than those of the days ahead (the weather turned
more changeable from late September). The 7th-93rd percentile is the one parameter chosen on
this same sample (a window of 14, 30 or 60 days and the pooling made no difference), so the
figures above are slightly flattering; the first half of the test (short, calm history) held
70-80 %, the second 80-84 %. The range is the error of the combination at a station: the okres's
point and a place between stations can be a little worse. A winter with inversions and a longer
history will show whether the width needs adjusting.

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
elevation). Stations more than 300 m above the okres point (summits such as Milešovka)
are left out of both: they are cold by height and say nothing about frost in the fields.
From the okres minimum: `frost_probability` = Φ(−min / σ) with σ the error
left in training (1.4–1.6 °C), `frost` (air-frost threshold flag) when the minimum is ≤ 1 °C
(the best CSI in every test; ≤ 0 °C catches too few, ≤ 2 °C has a FAR of 0.5–0.7), and
`ground_min`, the 5 cm minimum, = minimum − 5.0 + 1.5 · cloud + 0.35 · wind
(`ground_frost` when ≤ 0 °C; ČHMÚ's `TPM` is on average 2.9 °C below `TMInoc`, 4.1 °C
on clear calm nights, 0.5 °C overcast and windy). `mvd frost-fit` runs in the daily
workflow and writes `frost.json` to `data-latest`; without it the fields stay empty.

**Validation** (with `meteoverdict.frost`; event = observed minimum ≤ 0 °C; POD / FAR
/ CSI; MAE in °C). D+N forecasts of 11 models at 238 stations, D+1–D+3:

| Test | Forecast | MAE | bias | flag ≤ 0 °C | flag ≤ 1 °C |
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

### The obec forecast away from the stations (`mvd obce-loso`)

The [forecast for every obec](data-sources.md#forecast-for-every-obec-mvd-obce-forecast)
reads every model at the obec's own place and height and combines the models with the
weights and corrections of its okres; since 20 October 2026 the corrections' elevation
term is taken at the obec's own height (before: at the okres's forecast point, see
below). Most of the 6,258 obce have no station, so the only honest check is to make a
station's place look like one: **leave one station out**. For every ČHMÚ station the obec
forecast is rebuilt at the station as if it did not exist and scored against what it
measured.

- **Held out** from everything it would feed: the okres scores the weights and bias
  corrections come from, the okres pools (its okres borrows another station instead
  where it gets too few), the regression blend's pairs (hour-of-day bias, national
  elevation term, ridge weights) and the nearest-station baseline. Stations whose okres
  neighbourhoods (the okres plus the 30 km it may borrow from) do not overlap are held
  out together, so each okres is trained exactly as without its own held-out station;
  the national regression terms then also miss the other stations of the batch (stricter,
  never leaking). A test checks that a held-out station's observations cannot change
  its own forecast.
- **Stricter variant (`buffer`)**: the station and every station within 20 km held out
  (about 12 stations each), so no close neighbour helps either.
- **Out of sample** as the hindcast: the D+N forecast for day *d* is trained on the 90-day
  window of scores up to *d − N − 1*, at least 14 scored days. Forecasts: the stored D+N
  at the stations (`fc-YYYY-MM`; 5–18 October rebuilt from the single runs as the daily
  scores). Scored like the blend test: temperature and wind at 00/06/12/18 UTC,
  precipitation as UTC-day totals, on the station-days every series has.
- **Compared with** (a) `okres`: the okres's forecast without the downscaling (the same
  weights applied at the okres's other stations and averaged, as the hindcast rebuilds
  the okres forecast; the okres point itself has no stored D+N), (b) `nearest`: the
  models at the place weighted and bias-corrected by their scores at the nearest
  remaining station alone, (c) `median`: the plain median of the models at the place,
  uncorrected; and `obec_point`, the obec forecast with the corrections at the okres
  point's height (what the site did until 20 October 2026).
- **Intervals**: 95 %, circular moving-block bootstrap of whole days in 4-day blocks
  (`obce_loso.block_bootstrap`, so that runs of similar weather stay together; 2,000
  resamples). With 1-, 3- or 5-day blocks the intervals change by at most 0.03 °C and no
  conclusion changes.

**Period and stations:** 41 test days, 8 September – 18 October 2026 (scores exist from
24 August; the first two weeks are the training warm-up), 291 stations for temperature,
208 for wind and 433 for daily precipitation (472 stations in all, 44 batches; buffer
variant 59 batches). Run of 20 October 2026 on the current code; the first run of 19 October gave the same
MAEs to within 0.001 (its `obec_dz` is today's `obec`, its `obec` today's `obec_point`).
Results: `obce-loso.json` in the release `data-latest` (groups by variant, variable,
lead day and stratum; MAE per station); the methodology page shows the key numbers.

MAE of the obec forecast (as the site now: corrections at the obec's height) and the
difference to each alternative (obec minus it, negative = obec better, bold = interval
excludes 0), station held out:

| | lead | stations | MAE obec | − okres | − nearest | − median | obec − obec_point |
|---|---|---|---|---|---|---|---|
| Temperature (°C) | D+1 | 291 | 1.26 | **-0.49 (-0.56…-0.42)** | **-0.18 (-0.24…-0.12)** | **-0.11 (-0.19…-0.04)** | **-0.018 (-0.023…-0.013)** |
| Temperature (°C) | D+2 | 291 | 1.41 | **-0.36 (-0.46…-0.27)** | **-0.14 (-0.18…-0.10)** | **-0.08 (-0.13…-0.03)** | **-0.024 (-0.030…-0.019)** |
| Temperature (°C) | D+3 | 291 | 1.57 | **-0.28 (-0.39…-0.18)** | **-0.11 (-0.16…-0.06)** | **-0.06 (-0.12…-0.01)** | **-0.027 (-0.033…-0.021)** |
| Temperature (°C) | D+4 | 291 | 1.74 | **-0.24 (-0.33…-0.14)** | **-0.09 (-0.14…-0.02)** | -0.04 (-0.10…+0.03) | **-0.025 (-0.031…-0.019)** |
| Temperature (°C) | D+5 | 291 | 1.86 | **-0.19 (-0.29…-0.08)** | **-0.07 (-0.12…-0.01)** | -0.00 (-0.07…+0.07) | **-0.031 (-0.038…-0.023)** |
| Temperature (°C) | D+1–5 | 291 | 1.56 | **-0.32 (-0.41…-0.22)** | **-0.12 (-0.17…-0.07)** | **-0.06 (-0.12…-0.01)** | **-0.025 (-0.031…-0.019)** |
| Wind (m/s) | D+1 | 208 | 0.97 | **-0.13 (-0.15…-0.11)** | **-0.17 (-0.18…-0.15)** | **-0.18 (-0.22…-0.14)** | **-0.006 (-0.009…-0.003)** |
| Wind (m/s) | D+2 | 208 | 1.03 | **-0.07 (-0.09…-0.06)** | **-0.15 (-0.16…-0.14)** | **-0.18 (-0.22…-0.14)** | **-0.013 (-0.017…-0.009)** |
| Wind (m/s) | D+3 | 208 | 1.06 | **-0.04 (-0.05…-0.03)** | **-0.14 (-0.15…-0.13)** | **-0.11 (-0.14…-0.08)** | **-0.015 (-0.020…-0.010)** |
| Wind (m/s) | D+4 | 208 | 1.10 | **-0.03 (-0.04…-0.02)** | **-0.14 (-0.15…-0.13)** | **-0.08 (-0.10…-0.06)** | **-0.014 (-0.019…-0.008)** |
| Wind (m/s) | D+5 | 208 | 1.14 | **-0.02 (-0.03…-0.01)** | **-0.14 (-0.15…-0.13)** | **-0.10 (-0.14…-0.07)** | **-0.017 (-0.023…-0.011)** |
| Wind (m/s) | D+1–5 | 208 | 1.06 | **-0.06 (-0.07…-0.05)** | **-0.15 (-0.16…-0.14)** | **-0.13 (-0.16…-0.10)** | **-0.013 (-0.017…-0.008)** |
| Precipitation (mm/day) | D+1 | 433 | 0.76 | **-0.05 (-0.08…-0.02)** | -0.00 (-0.00…+0.00) | -0.01 (-0.09…+0.06) | +0.000 (-0.000…+0.000) |
| Precipitation (mm/day) | D+2 | 432 | 0.93 | **-0.03 (-0.04…-0.01)** | **-0.00 (-0.00…-0.00)** | -0.01 (-0.10…+0.08) | -0.000 (-0.000…+0.000) |
| Precipitation (mm/day) | D+3 | 432 | 1.02 | **-0.01 (-0.02…-0.01)** | +0.00 (-0.00…+0.00) | -0.02 (-0.17…+0.12) | +0.000 (-0.000…+0.000) |
| Precipitation (mm/day) | D+4 | 432 | 1.09 | **-0.01 (-0.02…-0.01)** | -0.00 (-0.00…-0.00) | +0.03 (-0.09…+0.14) | +0.000 (+0.000…+0.000) |
| Precipitation (mm/day) | D+5 | 432 | 1.17 | **-0.01 (-0.02…-0.01)** | -0.00 (-0.01…-0.00) | +0.12 (-0.05…+0.30) | +0.000 (-0.000…+0.000) |
| Precipitation (mm/day) | D+1–5 | 433 | 0.99 | **-0.02 (-0.04…-0.01)** | -0.00 (-0.00…-0.00) | +0.02 (-0.09…+0.12) | +0.000 (+0.000…+0.000) |

Stations within 20 km also held out (`buffer`), D+1–5: temperature 1.60 °C, obec − okres
**−0.53** (−0.66…−0.40), − nearest **−0.09** (−0.13…−0.05), − median −0.03 (−0.08…+0.03);
wind 1.08 m/s, **−0.08** (−0.09…−0.07), −0.01 (−0.02…+0.00), **−0.11** (−0.14…−0.08);
precipitation 0.99 mm, **−0.04** (−0.07…−0.02), −0.00, +0.02 (−0.09…+0.13). The obec
forecast itself hardly gets worse without its neighbours (+0.04 °C, +0.02 m/s, ±0 mm);
the okres forecast does (+0.25 °C).

By station class (held out, D+1–5; "150-400 m" etc. = height of the station above or
below its okres's forecast point), so that the few mountain stations do not hide the
rest:

| | stratum | stations | MAE obec | okres | nearest | median | obec − okres | obec − median |
|---|---|---|---|---|---|---|---|---|
| Temperature (°C) | lowland | 121 | 1.43 | 1.74 | 1.57 | 1.56 | **-0.31 (-0.38…-0.24)** | **-0.12 (-0.20…-0.04)** |
| Temperature (°C) | mountain | 48 | 1.79 | 2.37 | 1.89 | 1.71 | **-0.58 (-0.87…-0.29)** | **+0.09 (+0.04…+0.13)** |
| Temperature (°C) | upland | 122 | 1.60 | 1.82 | 1.70 | 1.65 | **-0.22 (-0.28…-0.16)** | -0.06 (-0.11…+0.00) |
| Temperature (°C) | 150-400 m | 74 | 1.65 | 1.97 | 1.79 | 1.64 | **-0.32 (-0.43…-0.21)** | +0.01 (-0.03…+0.05) |
| Temperature (°C) | over 400 m | 35 | 1.68 | 2.52 | 1.75 | 1.64 | **-0.84 (-1.22…-0.49)** | **+0.04 (+0.01…+0.08)** |
| Temperature (°C) | within 150 m | 182 | 1.50 | 1.72 | 1.62 | 1.61 | **-0.21 (-0.27…-0.16)** | **-0.11 (-0.18…-0.04)** |
| Wind (m/s) | lowland | 100 | 0.92 | 0.97 | 1.07 | 1.09 | **-0.06 (-0.07…-0.05)** | **-0.18 (-0.21…-0.15)** |
| Wind (m/s) | mountain | 16 | 2.27 | 2.39 | 2.63 | 2.16 | **-0.12 (-0.19…-0.06)** | **+0.11 (+0.05…+0.17)** |
| Wind (m/s) | upland | 92 | 1.00 | 1.06 | 1.10 | 1.12 | **-0.05 (-0.06…-0.04)** | **-0.12 (-0.15…-0.09)** |
| Wind (m/s) | 150-400 m | 42 | 1.06 | 1.15 | 1.17 | 1.09 | **-0.09 (-0.10…-0.08)** | -0.03 (-0.07…+0.00) |
| Wind (m/s) | over 400 m | 14 | 2.57 | 2.73 | 2.92 | 2.35 | **-0.16 (-0.23…-0.09)** | **+0.21 (+0.15…+0.28)** |
| Wind (m/s) | within 150 m | 152 | 0.92 | 0.96 | 1.06 | 1.11 | **-0.04 (-0.05…-0.04)** | **-0.19 (-0.22…-0.16)** |
| Precipitation (mm/day) | lowland | 183 | 0.93 | 0.96 | 0.93 | 0.92 | **-0.02 (-0.03…-0.01)** | +0.01 (-0.11…+0.11) |
| Precipitation (mm/day) | mountain | 35 | 1.36 | 1.38 | 1.36 | 1.37 | -0.02 (-0.09…+0.04) | -0.01 (-0.15…+0.13) |
| Precipitation (mm/day) | upland | 215 | 0.98 | 1.00 | 0.98 | 0.94 | **-0.02 (-0.04…-0.01)** | +0.04 (-0.08…+0.14) |
| Precipitation (mm/day) | 150-400 m | 98 | 1.16 | 1.19 | 1.16 | 1.13 | **-0.03 (-0.05…-0.00)** | +0.03 (-0.10…+0.15) |
| Precipitation (mm/day) | over 400 m | 23 | 1.48 | 1.52 | 1.48 | 1.52 | -0.05 (-0.14…+0.03) | -0.04 (-0.22…+0.11) |
| Precipitation (mm/day) | within 150 m | 312 | 0.90 | 0.92 | 0.90 | 0.88 | **-0.02 (-0.03…-0.01)** | +0.02 (-0.08…+0.12) |

#### The corrections at the obec's height (switched on 20 October 2026)

The regression blend's slot corrections have an elevation term (`lapse_* × Δz`, from the
mean height of the okres's stations, clipped to their height range, at half strength,
`combine.POINT_LAPSE_FACTOR`). Until 20 October the obec forecast took it at the okres
point's height for every obec; now at the obec's own height (`obce_forecast.at_obec_height`;
the same half strength and clipping). Same run, same station-days, before (`obec_point`)
and after (`obec`), D+1–5, station held out (precipitation has no elevation term and is
unchanged):

| | stratum | stations | MAE before (okres point) | MAE now (obec height) | now − before | now − median |
|---|---|---|---|---|---|---|
| Temperature (°C) | all | 291 | 1.585 | 1.560 | **-0.025 (-0.031…-0.019)** | **-0.06 (-0.12…-0.01)** |
| Temperature (°C) | lowland | 121 | 1.437 | 1.432 | **-0.005 (-0.008…-0.001)** | **-0.12 (-0.20…-0.04)** |
| Temperature (°C) | mountain | 48 | 1.904 | 1.793 | **-0.111 (-0.141…-0.082)** | **+0.09 (+0.04…+0.13)** |
| Temperature (°C) | upland | 122 | 1.609 | 1.597 | **-0.012 (-0.015…-0.009)** | -0.06 (-0.11…+0.00) |
| Temperature (°C) | 150-400 m | 74 | 1.691 | 1.651 | **-0.040 (-0.049…-0.031)** | +0.01 (-0.03…+0.05) |
| Temperature (°C) | over 400 m | 35 | 1.806 | 1.682 | **-0.124 (-0.159…-0.091)** | **+0.04 (+0.01…+0.08)** |
| Temperature (°C) | within 150 m | 182 | 1.500 | 1.500 | -0.000 (-0.000…+0.000) | **-0.11 (-0.18…-0.04)** |
| Wind (m/s) | all | 208 | 1.070 | 1.057 | **-0.013 (-0.017…-0.008)** | **-0.13 (-0.16…-0.10)** |
| Wind (m/s) | lowland | 100 | 0.932 | 0.915 | **-0.017 (-0.019…-0.015)** | **-0.18 (-0.21…-0.15)** |
| Wind (m/s) | mountain | 16 | 2.346 | 2.270 | **-0.076 (-0.122…-0.029)** | **+0.11 (+0.05…+0.17)** |
| Wind (m/s) | upland | 92 | 1.002 | 1.004 | +0.002 (-0.002…+0.006) | **-0.12 (-0.15…-0.09)** |
| Wind (m/s) | 150-400 m | 42 | 1.086 | 1.060 | **-0.026 (-0.033…-0.020)** | -0.03 (-0.07…+0.00) |
| Wind (m/s) | over 400 m | 14 | 2.668 | 2.568 | **-0.100 (-0.147…-0.052)** | **+0.21 (+0.15…+0.28)** |
| Wind (m/s) | within 150 m | 152 | 0.919 | 0.917 | -0.001 (-0.002…-0.000) | **-0.19 (-0.22…-0.16)** |

The rule set beforehand was to switch it on only if it is not worse overall and better on
the mountain stations, with intervals: **better overall** (−0.025 °C, −0.013 m/s, both
intervals below 0, at every lead day), **better on the mountain stations** (−0.11 °C,
−0.08 m/s) and at the stations far above or below their okres point, and nowhere
significantly worse (upland wind +0.002, interval −0.002…+0.006). In the buffer variant
too: −0.010 °C (−0.012…−0.007), −0.011 m/s (−0.013…−0.009), mountains −0.029 °C
(−0.039…−0.020) and −0.031 m/s (−0.043…−0.017). It is small, and the mountain stations
remain behind the plain median (+0.09 °C, +0.11 m/s), but less so than before
(+0.20 °C, +0.18 m/s).

**Conclusions.**

- At a place without a station the obec forecast's typical error is about **1.26 °C at
  D+1 and 1.56 °C over D+1–5**, wind **1.0–1.15 m/s**, daily precipitation **0.8–1.2 mm**
  (autumn 2026, 41 days; winter inversions are not in it).
- **Reading the models at the place pays off clearly against the okres forecast**
  (−0.32 °C, −17 %; wind −5 %; precipitation −2 %), most where the place lies far above
  or below the okres point (−0.84 °C over 400 m); without close neighbours the gain
  grows (−0.53 °C). Showing the okres's single number for every obec would be worse
  everywhere.
- **Against the plain median of the models at the place the gain is smaller**: wind
  −0.13 m/s (−11 %, every lead day), temperature −0.11 °C at D+1 to −0.06 at D+3 but
  no significant difference at D+4–5, and none for precipitation (the median is even
  slightly better at D+4–5, not significant). The okres corrections carry over to a
  place without a station for lowland and upland places, **not fully for mountains**:
  at the 48 mountain stations the obec forecast is still **worse** than the raw median
  (+0.09 °C, wind +0.11 m/s; for temperature also at stations more than 400 m above or
  below their okres point, +0.04 °C), because its corrections are learnt mostly at lower
  stations.
- **The corrections at the obec's height** (on since 20 October) are better everywhere
  they matter, most in the mountains (−0.11 °C, −0.08 m/s); see above.
- The nearest-station correction is a poor substitute for the okres weights:
  −0.12 °C and −0.15 m/s worse than the obec forecast; a wind bias learnt at one
  station does not carry over to the next (sheltered and open sites differ). In the
  buffer variant it is about as good as the obec forecast for wind, because nearby
  stations in similar terrain are no longer available to mislead it.
- Not covered: the obec forecast's own inputs are the bucket's grid cell moved to the
  obec's height (0.65 K per 100 m), here Open-Meteo's D+N at the station's coordinates
  and height (its own elevation correction) for most days; the elevation of an obec
  comes from a 50 m terrain model, a station's from ČHMÚ. Lead days follow the stored
  D+N, not hours from the run, and missing lead days are not filled from shorter ones as
  the live forecast does.

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
  so summits (Milešovka, Lysá hora) never set an okres's correction. Fitted and
  published, but the outlook uses the part-of-day fit below (`gust_part`): applied to
  the largest gust of a part of day, the daily coefficients make it worse. Neither is
  applied to the farmers' event skill: that verifies each model as published, and a
  correction fitted on the same observations would blur it.
- **Gusts per part of day** (`gust_part`, the outlook's `gust`): the same form fitted on
  the largest gust of each part of day; see [Gusts in the outlook](#gusts-in-the-outlook).

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

### Gusts in the outlook

The outlook's request has no gusts (adding them would cost a fifth more Open-Meteo
calls), but the single runs (`mvd fetch-runs`) already hold every model's hourly gusts
(maximum of the preceding hour) at the ~100 run stations, four runs a day. So the
outlook (`meteoverdict.gusts`, no Open-Meteo calls) takes the newest stored run
(fetched once 10 h old, so 10–16 h old; at most 36 h) and, per lowland run station of
the okres (≤ 750 m and at most 300 m above the okres point, as for frost; 76 of 77
okresy have one, Jablonec nad Nisou takes the nearest within 30 km), each model's
largest gust in the part of day (Prague time; an hourly gust belongs to the part of the
hour it ends), the mean over the models (at least 3, each reaching the part's end, the
part wholly after the run's start), corrected by `gust = a + b·mean + station term`,
then the mean over the okres's stations. A whole day is the largest of its four parts.
Beyond the run's end (5 days) or without a run: `null`.

**Which correction.** Checked out of sample on the research sample (above: previous
day's run of 10 models, D+1, the 8 stations up to 750 m), against the largest ČHMÚ
10-minute `Fmax` of each part (at least 30 of 36 values); each test day forecast with
coefficients fitted on the days up to two days before (at least 21), 39 test days
6 September – 14 October 2026, 1,248 station-parts; 95 % interval of the change from a
bootstrap over days:

| Forecast of the part's largest gust | MAE, m/s | Bias |
|---|---:|---:|
| Plain mean of the models | 1.05 | −0.17 |
| Daily-maximum coefficients (`gust`) | 1.15 | +0.50 |
| **Part-of-day fit (`gust_part`)** | **0.99** | +0.03 |

The part-of-day fit beats the plain mean by 0.06 m/s [0.02, 0.10], mostly in the
afternoon (1.19 → 0.99; night, morning and evening about equal). The daily
coefficients are 0.11 m/s worse [0.04, 0.17]: a part's largest gust is weaker than the
day's, so their intercept over-forecasts every part but the windiest. The bootstrap of
`gust_part` (`src/meteoverdict/data/sun-cloud-gust.json`) is fitted on all 61 days
(`a = 0.62`, `b = 0.93`).

**Threshold.** Of the 15 parts with an observed gust of at least 15 m/s, a forecast of
at least 15 m/s caught 1 (plain mean: 1 hit, 1 false alarm; corrected: 1 hit, none),
since a mean over models smooths the peaks. `gust_over_threshold` therefore uses a lower
threshold, **13.5 m/s** on the corrected gust: the best ETS among 12–15 m/s in steps of
0.5 (POD 0.47, FAR 0.50, CSI 0.32, ETS 0.31, frequency bias 0.93). The plain mean
reaches the same CSI at 14 m/s, so the correction improves the size of the gusts, not
the flagged parts; with 15 events this is a small sample.

**On the single runs themselves** the check was thin at first: the API's runs had gusts
only since the runs of 2026-10-15; since 2026-10-17 the runs from Open-Meteo's bucket
have them from 2026-07-15 on (all models but AIFS, JMA GSM and AIGFS). On 15 October (calm, no gust of 10 m/s), runs of 00, 06 and
12 UTC, 81 lowland stations, coefficients from the research sample: the plain mean
had MAE 0.79 / 0.74 / 0.64 m/s (bias +0.38 / +0.25 / +0.21) and the corrected one
0.96 / 0.88 / 0.81 (bias +0.75 / +0.62 / +0.65) — on a calm day the intercept
over-forecasts. One day says little, so the correction is guarded: the nightly
`mvd sun-cloud-gust` refits `gust_part` on the single runs (all four runs a day, lead
days by the hours from the run's start to the part's end) against the hourly ČHMÚ
gusts at the same stations (`obs`, the largest of six `Fmax`; at least 5 hours of the
part) once there are 21 days, and stores in `check` the plain and corrected MAE on the
last 10 days, fitted on the days before (from 31 days, about mid-November 2026).
`apply` is false when the correction does not beat the plain mean there, and the
outlook then shows the plain mean. It starts switched off (`apply: false` in the bootstrap), so
the outlook shows the plain mean until that check on the runs turns it on.

## The same-sample comparison with MeteoVerdict AI (Compare page)

The top of the comparison page ranks, on one sample, the plain models, the mean of all
models (`blend`), our combined forecast (the Outlook blend, `combined`) and, when its
run supplies them, experimental candidates such as MeteoVerdict AI.
`mvd blend-test --compare-zip` writes one small JSON file per region (Czechia, each kraj,
each okres): for every variable and lead day the ranking and the daily MAE of every
series. The series come from `blendtest.series`, which scores the candidates like the
combination and puts them through `aggregate.common_days` together with the models:
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
is "better" or "worse" than our blend only when both agree, otherwise "≈".

Two samples exist and are never mixed. The **validation sample** is the AI's out-of-sample
hindcast: it was trained on what was known at each issue day, but the model was chosen on
the same days (about 9 experiments), so its numbers are optimistic and the page says so.
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
