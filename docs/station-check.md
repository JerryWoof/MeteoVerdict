# Does it matter which stations score the models?

*Checked on 2026-10-16 with the scores of 10 August to 30 September 2026 (52 days, all
that `scores-2026-08` and `scores-2026-09` hold). Reproduce with
`uv run mvd station-check --out check.md` (module `meteoverdict.station_check`).*

## In short

- **All stations are ČHMÚ's official network.** There are no amateur stations in the
  data. 40 of them are main (synoptic, WMO) stations; the others are ČHMÚ's automatic
  climate, snow and precipitation stations and its manual rain gauges
  ([kinds of station](data-sources.md#kinds-of-station)).
- **Using only the automatic climate stations changes nothing that matters.** The
  model rankings agree almost perfectly with those of all stations (Spearman 0.79-1.0,
  mostly 0.95 or more), the best model is the same in 35 of 40 cases nationally and
  every change but one is within the bootstrap intervals; MAEs differ by less than
  0.1 °C, 0.1 m/s or 0.1 mm.
- **Using only the 40 main stations changes two things.** Night temperatures (00, 06,
  18 UTC) are forecast about 0.1-0.3 °C better there, and the best model changes at
  short lead days, partly beyond the intervals (at 06 UTC on day 1, for example,
  ICON-D2 wins at the main stations and AROME Austria with all stations; on day 2 IFS
  instead of ALADIN). Wind ranks very differently (Spearman about 0 at lead days 2-4):
  the main network includes exposed summits (Sněžka, Šerák, Lysá hora, Churáňov,
  Milešovka), where the models forecast much too little wind (by 6 m/s at Sněžka,
  5 m/s at Milešovka). Without the main stations above 700 m the correlation rises to
  0.4-0.9, but the best model still differs at lead days 2-4. Precipitation and midday
  temperature rank the same within the intervals.
- **Neither subset is "more correct".** The main stations are well exposed, open sites;
  the climate stations are where people live, in valleys and towns. All stations give
  seven times as many temperature stations (the main stations leave 1-5 per kraj, too
  few for a kraj ranking in six of 14 kraje), so we keep scoring with all of them and
  say so.
- **No station looks broken.** The stations whose errors stand out are explained by
  where they stand: summits with much stronger wind than any model forecasts, and
  valleys and frost hollows (Horská Kvilda, Rokytská slať, Orlické Záhoří) 2.5-3 °C
  colder than forecast in the early morning. They are real places and stay in.
- **One data problem: manual gauges after a gap.** In ČHMÚ's still incomplete September
  data some manual gauges report a value after several days without one, and those
  values are almost always wet. At Chýnov (Tábor) 43.7 mm on 15/16 September follows six
  missing days, while five automatic stations within 16 km had 0.0-0.1 mm that day and
  16-24 mm over the whole week: probably a multi-day total. We propose to skip such
  values (below); we have not changed the scoring.

## Data and method

**Stations by kind** (see [data-sources.md](data-sources.md#kinds-of-station)) and what
they score in this window:

| Kind | Active | Temperature | Wind | Precipitation (UTC day, hourly sums) | Precipitation 06-06 UTC (`precipitation_24h`) |
|---|---|---|---|---|---|
| main (WMO) | 40 | 40 | 39 | 39 | 39 |
| automatic climate | 218 | 217 | 168 | 214 | 214 |
| automatic snow (mountains) | 38 | 34 | – | – | – |
| automatic precipitation | 179 | – | – | 178 | 178 |
| manual precipitation (daily) | 279 | – | – | – | 272 |

So the temperature scores already include 34 mountain snow stations; leaving them out
keeps every national ranking within the intervals (Spearman 0.89 or more) and changes
MAEs by at most 0.05 °C.

**Subsets.** (a) all stations, as the site ranks; (b) only the main WMO stations
(`0-20000-…`); (c) only the automatic climate stations; and for `precipitation_24h`
(d) only the manual rain gauges. Variables: `temperature_2m` (00, 06, 12 and 18 UTC
together) and each synoptic hour separately, `wind_speed_10m` (the same four hours),
`precipitation_daily` (UTC day) and `precipitation_24h` (06-06 UTC, the only one with
manual gauges); lead days 1-5; all days of the window.

**Ranking.** Exactly as on the site (`meteoverdict.ranking`): per region, variable and
lead day only the station-days that every model of the region has, MAE per model, and
1,000 bootstrap resamples of whole days. A model is *tied with the best* when the 95 %
interval of its MAE minus the best model's contains 0. Regions with fewer than three
stations are left out. We compare each subset with (a) by:

- **Spearman** rank correlation of the models' MAEs (1: same order);
- **same best model**;
- **within the intervals**: the best model of each ranking is the best or tied with the
  best in the other, i.e. the change of winner is not beyond what chance explains;
- **MAE**: the MAE of (a)'s best model in (a) and in the subset, and the mean over all
  models of MAE(subset) - MAE(a).

**Stations that stand out.** For each station and variable (lead days 1 and 2, where
the station's own share of the error is largest; at least 3 models and 20 days): the
median over the models of the daily MAE and bias (forecast - observed). It is compared
with the median of the other stations of its okres **on the same days** (with the kraj
when the okres has fewer than three stations): the comparison over the same days
matters for the manual gauges, most of whose September values are not published yet, so
their window is mostly the wetter August. A station is flagged when its MAE is at least
twice its okres's, or when its bias differs from its okres's by at least 1.5 °C or
1.5 m/s and **all** models err the same way.

## Results: Czechia

| Subset | Variable | Stations | Spearman, lead day 1 / 2 / 3 / 4 / 5 | Same best model | Change within intervals | MAE of the best model (all → subset) | Mean MAE difference |
|---|---|---|---|---|---|---|---|
| climate | `precipitation_24h` | 214 | 0.97 / 0.98 / 1.00 / 1.00 / 1.00 | 5 of 5 | 5 of 5 | 1.40 → 1.44 | +0.03 |
| climate | `precipitation_daily` | 214 | 1.00 / 0.98 / 1.00 / 1.00 / 1.00 | 5 of 5 | 5 of 5 | 1.41 → 1.47 | +0.07 |
| climate | `temperature_2m` | 217 | 0.97 / 0.95 / 1.00 / 1.00 / 1.00 | 4 of 5 | 5 of 5 | 1.56 → 1.58 | +0.03 |
| climate | `temperature_2m_00utc` | 217 | 0.99 / 0.97 / 0.96 / 1.00 / 0.90 | 4 of 5 | 5 of 5 | 1.78 → 1.83 | +0.06 |
| climate | `temperature_2m_06utc` | 217 | 0.97 / 0.95 / 0.96 / 0.94 / 0.90 | 4 of 5 | 5 of 5 | 1.51 → 1.54 | +0.06 |
| climate | `temperature_2m_12utc` | 217 | 0.86 / 0.80 / 0.79 / 0.94 / 1.00 | 4 of 5 | 5 of 5 | 1.39 → 1.35 | -0.03 |
| climate | `temperature_2m_18utc` | 217 | 0.92 / 0.98 / 0.96 / 1.00 / 0.90 | 5 of 5 | 5 of 5 | 1.46 → 1.48 | +0.03 |
| climate | `wind_speed_10m` | 168 | 0.95 / 0.98 / 1.00 / 0.94 / 0.90 | 4 of 5 | 4 of 5 | 1.14 → 1.08 | -0.01 |
| main | `precipitation_24h` | 39 | 0.92 / 0.88 / 0.96 / 0.94 / 1.00 | 2 of 5 | 5 of 5 | 1.40 → 1.35 | -0.07 |
| main | `precipitation_daily` | 39 | 0.96 / 0.78 / 1.00 / 1.00 / 1.00 | 5 of 5 | 5 of 5 | 1.41 → 1.36 | -0.06 |
| main | `temperature_2m` | 40 | 0.88 / 0.90 / 0.86 / 1.00 / 1.00 | 4 of 5 | 5 of 5 | 1.56 → 1.37 | -0.18 |
| main | `temperature_2m_00utc` | 40 | 0.87 / 0.88 / 0.79 / 0.77 / 0.80 | 2 of 5 | 4 of 5 | 1.78 → 1.50 | -0.32 |
| main | `temperature_2m_06utc` | 40 | 0.84 / 0.72 / 0.79 / 0.77 / 1.00 | 2 of 5 | 2 of 5 | 1.51 → 1.32 | -0.28 |
| main | `temperature_2m_12utc` | 40 | 0.29 / 0.55 / 0.86 / 1.00 / 1.00 | 5 of 5 | 5 of 5 | 1.39 → 1.37 | -0.00 |
| main | `temperature_2m_18utc` | 40 | 0.49 / 0.28 / 0.57 / 0.49 / 0.90 | 2 of 5 | 3 of 5 | 1.46 → 1.35 | -0.11 |
| main | `wind_speed_10m` | 39 | 0.57 / -0.05 / -0.11 / -0.03 / 0.80 | 2 of 5 | 2 of 5 | 1.14 → 1.41 | +0.06 |
| manual_precipitation | `precipitation_24h` | 68 | 0.47 / 0.17 / 0.96 / 0.94 / 0.90 | 4 of 5 | 5 of 5 | 1.40 → 1.56 | +0.31 |

The ten cases where the best model changes beyond the intervals: main stations,
temperature at 00 UTC (lead day 1), 06 UTC (lead days 1-3) and 18 UTC (lead days 1-2),
wind (lead days 2-4); climate stations, wind at lead day 1 (ICON-EU instead of
ICON-D2). For the manual gauges the ranking at lead days 1 and 2 differs
(Spearman 0.47 and 0.17) but within the intervals, and their larger MAE (+0.3 mm) comes
from their days: in August alone, when their data are complete, the difference at lead
day 1 is +0.01 mm.

## Results: kraje

Over all kraje with at least three stations of the subset and lead days 1-5 (main
stations: 8 kraje for temperature, 7 for wind):

| Subset | Variable | Kraj × lead day groups | Median stations per kraj | Spearman median (min) | Same best model | Change within intervals | Mean MAE difference |
|---|---|---|---|---|---|---|---|
| climate | `precipitation_24h` | 70 | 16 | 0.96 (0.78) | 81 % | 100 % | -0.01 |
| climate | `precipitation_daily` | 70 | 16 | 0.96 (0.77) | 87 % | 100 % | +0.02 |
| climate | `temperature_2m` | 70 | 16 | 0.96 (0.66) | 77 % | 97 % | +0.04 |
| climate | `temperature_2m_00utc` | 70 | 16 | 0.95 (0.35) | 79 % | 100 % | +0.07 |
| climate | `temperature_2m_06utc` | 70 | 16 | 0.96 (0.40) | 86 % | 100 % | +0.07 |
| climate | `temperature_2m_12utc` | 70 | 16 | 0.94 (0.43) | 94 % | 100 % | -0.02 |
| climate | `temperature_2m_18utc` | 70 | 16 | 0.94 (0.37) | 80 % | 99 % | +0.03 |
| climate | `wind_speed_10m` | 65 | 12 | 0.99 (0.50) | 94 % | 98 % | -0.00 |
| main | `precipitation_24h` | 40 | 3 | 0.90 (0.42) | 57 % | 95 % | -0.02 |
| main | `precipitation_daily` | 40 | 3 | 0.90 (0.14) | 55 % | 98 % | -0.02 |
| main | `temperature_2m` | 40 | 4 | 0.89 (0.18) | 70 % | 90 % | -0.12 |
| main | `temperature_2m_00utc` | 40 | 4 | 0.70 (-0.50) | 42 % | 72 % | -0.23 |
| main | `temperature_2m_06utc` | 40 | 4 | 0.73 (-0.33) | 52 % | 65 % | -0.19 |
| main | `temperature_2m_12utc` | 40 | 4 | 0.83 (0.21) | 75 % | 100 % | +0.04 |
| main | `temperature_2m_18utc` | 40 | 4 | 0.75 (-0.37) | 45 % | 72 % | -0.09 |
| main | `wind_speed_10m` | 35 | 4 | 0.38 (-0.75) | 31 % | 34 % | +0.16 |

Within a kraj, rankings are noisier (fewer stations), but the automatic climate
stations still give the same ranking within the intervals in 97-100 % of the kraj
rankings. With only the main stations a kraj ranking would rest on 3-5 stations and
change its winner about half the time.

## Stations that stand out

50 stations are flagged for at least one variable (40 of them for the 06 UTC
temperature, i.e. night inversions; none for precipitation once compared on the same
days). The ten most marked (`mae`, `area_mae`: the station's and its okres's median-model
MAE on the same days; `ratio` their quotient; `bias_excess`: the station's bias minus
its okres's, forecast - observed; `flagged`: variables flagged for the station):

| name | okres | elevation | network | variable | mae | area_mae | ratio | bias | bias_excess | flagged | hint |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Sněžka, Poštovna | Trutnov | 1602 | main | wind_speed_10m | 6.04 | 1.35 | 4.50 | -6.02 | -6.28 | 1 | stronger wind than forecast: exposed ridge or summit |
| Milešovka | Litoměřice | 830 | main | wind_speed_10m | 5.23 | 1.13 | 4.60 | -5.20 | -5.98 | 2 | stronger wind than forecast: exposed ridge or summit |
| Praděd | Bruntál | 1490 | climate | wind_speed_10m | 4.79 | 1.53 | 3.10 | -4.79 | -5.78 | 1 | stronger wind than forecast: exposed ridge or summit |
| Orlické Záhoří - vodárna | Rychnov nad Kněžnou | 665 | climate | temperature_2m_06utc | 3.82 | 1.13 | 3.40 | 3.55 | 2.96 | 2 | colder than the models and its okres: valley, frost hollow or inversion |
| Lysá hora | Frýdek-Místek | 1322 | main | wind_speed_10m | 2.75 | 1.11 | 2.50 | -2.54 | -2.92 | 1 | stronger wind than forecast: exposed ridge or summit |
| Bílá, Polaň | Frýdek-Místek | 613 | snow | temperature_2m_06utc | 2.89 | 1.23 | 2.30 | 2.81 | 2.88 | 2 | colder than the models and its okres: valley, frost hollow or inversion |
| Luční bouda | Trutnov | 1413 | climate | wind_speed_10m | 2.50 | 1.35 | 1.90 | -2.40 | -2.66 | 1 | stronger wind than forecast: exposed ridge or summit |
| Kateřinice, Ojičná | Vsetín | 586 | snow | temperature_2m_06utc | 2.37 | 1.63 | 1.50 | -2.05 | -2.66 | 2 | warmer than the models and its okres: town, slope or sheltered sensor |
| Horská Kvilda | Klatovy | 1052 | climate | temperature_2m | 3.36 | 1.47 | 2.30 | 2.89 | 2.65 | 2 | colder than the models and its okres: valley, frost hollow or inversion |
| Rokytská slať | Klatovy | 1098 | snow | temperature_2m_06utc | 3.48 | 1.52 | 2.30 | 3.22 | 2.57 | 2 | colder than the models and its okres: valley, frost hollow or inversion |

All ten are siting, not faults:

- **Summits** (Sněžka, Milešovka, Praděd, Lysá hora, Luční bouda): every model forecasts
  2.5-6 m/s too little wind, because a grid cell of 1-25 km smooths a summit away. These
  are the stations where strong wind matters; they stay in, and they help explain why
  the main network (with Sněžka, Šerák, Lysá hora, Churáňov and Milešovka) ranks wind
  differently.
- **Valleys and frost hollows** (Orlické Záhoří - vodárna, Horská Kvilda, Rokytská slať,
  Bílá - Polaň): 2.5-3 °C colder than forecast and than their okres, most at 06 UTC
  after clear nights, a well-known
  effect of cold air pooling (Horská Kvilda is one of the coldest places in Czechia).
- **Warm slope** (Kateřinice, Ojičná snow station, 586 m): about 2.7 °C warmer than its
  okres at 06 UTC, likely above the valley inversion.

For precipitation, the largest ratio is Chýnov's 1.9 (a single day, see above), below
the threshold.

## Proposals

1. **Manual gauges: skip a daily total that follows a missing day** (applied:
   `gauges.drop_after_gaps`, a value after a gap in the same gauge's own readings, except
   in the checked historical archive). In August and
   September 178 manual values follow one or more missing days (32 gauges, almost all in
   September, whose data ČHMÚ has not completed yet); 94 % of them are wet with a mean
   of 5.4 mm, against 36 % and 2.2 mm for values after a reported day. They are either
   multi-day totals or a selection of wet days, and both make the models look too dry.
   `gauges.py` could drop a value whose previous day is missing until the month is
   complete (ČHMÚ's later checked data then fills the gap and the day is rescored).
2. **An exclusion list, should a station ever be broken** (not applied: nothing needs it). A file such as
   `src/meteoverdict/data/excluded_stations.yaml` with `station`, `variables`, `from`,
   `until` and `reason`, applied in `aggregate` and `ranking` (not in the stored scores,
   so it can be undone without rescoring) and shown on the station page. Nothing found
   in this check needs it: no station has errors that its siting does not explain.
3. **Say which stations are scored** (applied). The methodology now says that all stations are
   ČHMÚ's official network and that rankings with only the main stations differ for
   wind and night temperature (Limitations).

## Caveats

- 52 days of late summer: no winter inversions, snow or frozen precipitation; the
  check should be repeated with a longer window (`mvd station-check`).
- Fewer models reach the longer lead days (11 at D+1, 5 at D+5), so Spearman at D+4 and
  D+5 rests on 5-6 models and jumps in steps.
- The main stations are a subset of all stations, so (a) and (b) are not independent;
  the intervals are those of each ranking, not of the difference between them.
- The bootstrap ignores correlation between consecutive days (as on the site), so the
  intervals are slightly too narrow, which makes changes look significant more often,
  not less.
