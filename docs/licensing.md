# Licensing and terms of use

What we may do with each source, what it obliges us to do, and under which terms we
publish our own outputs. Checked on **2026-10-12**; the providers of the models added on
2026-10-15 (ECCC, JMA, CMA, NOAA AIGFS, KNMI, DMI) and the ČHMÚ radar data and Meteosat
images on that day. This
is a summary for the project, not legal advice.

## Sources

| Source | Licence | Evidence | Obligations for us |
|---|---|---|---|
| ČHMÚ station observations and metadata (opendata.chmi.cz) | CC BY 4.0 | National Open Data Catalogue (data.gov.cz), e.g. "Meteorologická data měřená v síti stanic ČHMÚ za aktuální rok v intervalu 1 hodina" and "Aktuální meteorologická data … v intervalu 10 minut a 1 hodina": `autorské-dílo` and `databáze-jako-autorské-dílo` = CC BY 4.0, author ČHMÚ | credit ČHMÚ, link the licence, say what we changed |
| ČHMÚ ALADIN forecasts (opendata.chmi.cz/meteorology/weather/nwp_aladin) | CC BY 4.0 | National Open Data Catalogue: "Numerické předpovědi počasí modelu ALADIN/ČHMÚ" and its two product datasets (oblast ČR, projekce Lambert) | same as above |
| ČHMÚ weather radar composites (opendata.chmi.cz/meteorology/weather/radar) | CC BY 4.0 | National Open Data Catalogue, checked 2026-10-15: "Radarová data ČHMÚ", "Sloučená informace maximální radarové odrazivosti MAX_Z pro území Česka", the PseudoCAPPI_2km, ECHO_TOP and MERGE datasets and both "Extrapolační předpověď …" datasets | credit ČHMÚ on the radar page and in the release notes, link the licence, say what we changed (packing per day, cropped PNG frames, station extraction) |
| ČHMÚ Meteosat images (opendata.chmi.cz/meteorology/weather/satellite/geo: `vis-ir`, `night-M`, `wv062`, …) | CC BY 4.0, twice: EUMETSAT's for the satellite data, ČHMÚ's for its images | **Not in the National Open Data Catalogue** (no satellite dataset of ČHMÚ there, checked 2026-10-15 by SPARQL), so no dataset-level record. ČHMÚ states for all its open data: "Otevřená data ČHMÚ můžete využívat bezplatně při respektování licence Creative Commons BY 4.0" (chmi.cz FAQ "Jak mohu používat otevřená data ČHMÚ?", read 2026-10-15). EUMETSAT Data Policy (www-cdn.eumetsat.int/files/2026-01/45173 - Data_Policy.pdf, read 2026-10-15): RGB composites and visualisations of single channels are "Advanced Image Products" (Annex II), which Article 4 lists as **"Core"** data; Article 5.1: Core data are free and unrestricted for all users "under a CC-BY-4.0 licence"; Article 6.1: users may redistribute all Core data (the ban on redistribution in 6.2 is for the original numerical data of "Recommended" data, which these JPGs are not); Article 7.2: the rights in images generated from EUMETSAT data lie with whoever generated them (here ČHMÚ) | credit both: "contains modified EUMETSAT Meteosat data <year>" (wording required by Article 6.3) and ČHMÚ with the licence link; say what we changed (cropped, converted to WebP). If ČHMÚ ever publishes different terms for this folder, they take precedence for its images |
| Open-Meteo API (all other forecasts, and ALADIN as served by Open-Meteo): Forecast, Previous Runs and Single Runs APIs | CC BY 4.0 | open-meteo.com/en/licence, /en/terms | credit Open-Meteo with a link **next to every place the data is shown**; free tier only for **non-commercial** use and under 600 calls/min, 5,000/hour, 10,000/day and 300,000/month, shared by all our workflows |
| UK Met Office models via Open-Meteo | **CC BY-SA 4.0** | open-meteo.com/en/licence | credit; anything we publish that is derived from it must be shared under CC BY-SA 4.0 (ShareAlike) |
| DWD (ICON-D2, ICON-EU, ICON global), ECMWF (IFS, AIFS), KNMI, DMI via Open-Meteo | CC BY 4.0 | open-meteo.com/en/licence (KNMI and DMI link CC BY 4.0) | credit the provider |
| NOAA NCEP (GFS, AIGFS) via Open-Meteo | US government work, no restrictions | open-meteo.com/en/licence (links weather.gov/disclaimer) | credit as courtesy |
| Météo-France (ARPEGE Europe and World) via Open-Meteo | Licence Ouverte 2.0 (Etalab), compatible with CC BY | data.gouv.fr datasets "Paquets Arpège", licence `lov2` | credit Météo-France |
| ECCC / Canadian Meteorological Centre (GEM Global) via Open-Meteo | Environment and Climate Change Canada Data Servers End-use Licence: worldwide, royalty-free, perpetual, commercial use allowed | open-meteo.com/en/licence links eccc-msc.github.io/open-data/licence/readme_en/ (read 2026-10-15) | attribution "Data Source: Environment and Climate Change Canada" (or "Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada") with a link to the licence where possible; no suggestion of official status or endorsement |
| Japan Meteorological Agency (GSM) via Open-Meteo | JMA Terms of Use (Public Data License 1.0), which JMA states are **compatible with CC BY 4.0** (content may be used under CC BY 4.0 instead) | open-meteo.com/en/licence links jma.go.jp/jma/en/copyright.html (read 2026-10-15) | cite the source ("Source: Japan Meteorological Agency"), say that it was edited, and do not present edited data as made by the Government of Japan. **Unclear:** the terms are written for JMA's website content; whether they also govern the GSM model data Open-Meteo redistributes is not stated, and third-party rights are the user's to check |
| China Meteorological Administration (GRAPES) via Open-Meteo | CC BY 4.0 **as stated by Open-Meteo** | open-meteo.com/en/licence links only the CC BY 4.0 text, no CMA document | credit CMA. **Unclear:** we found no licence statement by CMA itself for this data; Open-Meteo's statement is the only evidence |
| GeoSphere Austria (AROME) via Open-Meteo | CC BY 4.0 | GeoSphere Data Hub, dataset `nwp-v1-1h-2500m` | credit GeoSphere Austria (not listed on Open-Meteo's licence page) |
| Kraj and okres boundaries (ČÚZK) | CC BY 4.0 | cuzk.gov.cz, "Otevřená data – základní informace"; converted by siwekm/czech-geojson (CC BY 4.0) | credit ČÚZK and the converter |
| Municipalities for the radar page's place search (ČÚZK RÚIAN, `vdp.cuzk.gov.cz`, file `ST_UZSZ`) | CC BY 4.0 | cuzk.gov.cz, "Otevřená data – základní informace": "ČÚZK poskytuje otevřená data pod licencí Creative Commons CC-BY 4.0" (as for the boundaries above) | credit ČÚZK on the radar page (footer and map credits: "Boundaries, municipalities: ČÚZK"), link the licence, say what we changed (names, okres and definition points only, converted from S-JTSK to WGS 84, rounded) |
| Radar base map: OpenFreeMap vector tiles (`tiles.openfreemap.org`, OpenMapTiles schema, OpenStreetMap data) | OSM data: **ODbL 1.0**; OpenMapTiles schema: CC BY 4.0; OpenFreeMap: a free public instance, no API key, no registration | openfreemap.org (asks for the OpenMapTiles and OpenStreetMap attribution, which its TileJSON adds to the map), openstreetmap.org/copyright, openmaptiles.org | the map shows tiles only (a Produced Work under the ODbL; we do not copy or redistribute the database): credit "OpenFreeMap © OpenMapTiles © OpenStreetMap contributors" on the map (the attribution control) and in the radar page footer, with links |
| Radar base map relief: AWS Terrain Tiles (`s3.amazonaws.com/elevation-tiles-prod`, terrarium PNG; Registry of Open Data on AWS) | free open data; the sources need attribution | github.com/tilezen/joerd, docs/attribution.md (read 2026-10-18) | credit the elevation sources: for our area EU-DEM ("produced using Copernicus data and information funded by the European Union - EU-DEM layers"), SRTM and GMTED2010 (courtesy of the U.S. Geological Survey), DGM Österreich (© offene Daten Österreichs) and ETOPO1 (NOAA); the map credit links the full list, the footer names them |
| Elevation of the okres forecast points: Open-Meteo Elevation API (Copernicus DEM GLO-90); of the obce (test): AWS Terrain Tiles as the radar relief row above | Open-Meteo: CC BY 4.0; Copernicus DEM GLO-90: free licence, attribution required | open-meteo.com/en/docs/elevation-api (read 2026-10-18) | only single heights used in the calculation; credit Open-Meteo (footer) and "Copernicus DEM GLO-90 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA" here |
| Population of the obce (test): ČSÚ DataStat, set OBY02A ("Počet obyvatel podle pohlaví"), 1 January | ČSÚ open data: free use with the source named (unverified wording; checked only that the data are public through the open DataStat API) | data.csu.gov.cz/datastat (read 2026-10-18) | the forecast page's footer names "Population of the villages: ČSÚ" with a link to the set |
| Forecast and measured maps' base map when zoomed in: the radar page's (OpenFreeMap / OpenMapTiles / OSM, Terrain Tiles) | as the radar base map rows above | — | the forecast and measured pages' footers and map credits name them as the radar page's do |

## What we publish, and under which licence

| Output | Where | Licence |
|---|---|---|
| Code | this repository | MIT |
| ALADIN station archive (`aladin-YYYY-MM` releases) | GitHub Release assets | CC BY 4.0, derived from ČHMÚ data only; release notes credit ČHMÚ and list our changes |
| ČHMÚ station data archive (`chmi-*` releases: every element of every station) | GitHub Release assets | CC BY 4.0, ČHMÚ data only, values unchanged (JSON → Parquet); release notes credit ČHMÚ and state the change |
| Station pages (`measured.html`, `station-data.zip` in `data-latest`) | GitHub Pages | CC BY 4.0, ČHMÚ data only; the page credits ČHMÚ with a link and the licence |
| Radar archive (`radar-YYYY-MM` releases) and live frames (branch `radar-live`) | GitHub Release assets, a git branch | CC BY 4.0, derived from ČHMÚ data only (echo-top frames, motion fields and storm cells are our derivations from the ČHMÚ composites); release notes and the branch README credit ČHMÚ and list our changes |
| Satellite archive (`satellite-YYYY-MM` releases), satellite frames in `radar-live` and the radar day sets | GitHub Release assets, a git branch, GitHub Pages | CC BY 4.0; the release notes, the branch README and `index.json` (`satellite_attribution`) credit EUMETSAT ("contains modified EUMETSAT Meteosat data <year>") and ČHMÚ and list our changes |
| Single model runs at ~100 stations (`runs-YYYY-MM` releases) | GitHub Release assets | **CC BY-SA 4.0** (includes UK Met Office data); release notes credit Open-Meteo and the providers |
| AI forecast outputs (`ai-latest` release, `data/scores/ai/`: `ai.json`, `ai-forecast.json`, `fc/`, the heatmap inputs) | GitHub Release asset, GitHub Pages | **CC BY-SA 4.0**: they are derived from forecasts of all sources, including UK Met Office data (ShareAlike); the files carry no licence field yet, the Data page states it |
| Scores, rankings, web map, open data | repository and GitHub Pages | **CC BY-SA 4.0**: they combine all sources, including UK Met Office data (ShareAlike). CC BY 4.0 inputs may be included in CC BY-SA 4.0 work. |

Publishing these outputs openly is allowed: every source permits redistribution and
adaptation with attribution. Keeping them private would not change any obligation
below, and public data is the point of the project.

## Rules for the project

1. **Non-commercial.** The free Open-Meteo API may only be used for non-commercial
   purposes (no ads, no subscriptions, no commercial products; see their terms). If the
   project or its results are used commercially, an Open-Meteo API subscription
   (Professional for the Previous Runs API) is required. The Single Runs API
   (`mvd fetch-runs`, run-by-run verification of every model) is used on the same free,
   non-commercial tier without an API key; the page that shows it says so.
2. **Attribution everywhere data is shown:** README, web map and release notes credit
   Open-Meteo (with link), ČHMÚ, the model providers (since 2026-10-15 also
   Environment and Climate Change Canada, the Japan Meteorological Agency and the China
   Meteorological Administration) and ČÚZK, link the licences, and say that values were
   processed (station extraction, unit conversion, scoring).
3. **Respect rate limits:** batch locations, request 14-day windows (same cost as one
   day), back off on HTTP 429. The free tier allows 300,000 calls a month, so a full
   backfill of all stations takes months and must be spread out (roadmap 2.6). All
   workflows together stay below the daily and the monthly limit: the outlook's fallback
   ≤ 800, the single runs' fallback ≤ 400 and 8,300 shared by the backfill and the
   histories a day,
   ≤ 294,500 in a 31-day month ([budget](data-sources.md#open-meteo-budget)); the outlook
   and the newest single runs come from Open-Meteo's open-data bucket on AWS (no API calls; same CC BY
   4.0 data and attribution, read with range requests of a few kB per station), the API
   asks about 100 stations, not all ~500, and no request weighs more than 500 (the limit
   is 600 a minute).
4. **The forecast pages** do not ask Open-Meteo from the visitors' browsers (since
   2026-10-17; before, the detailed forecast page `forecast-detail.html` sent one request per
   okres shown). `mvd outlook` makes the only requests, four times a day for all okresy
   (about 420 calls with 11 weighted models, 732 with all 19, in at most two requests),
   and publishes `outlook.json` and, per okres, every model's hourly forecast as Open-Meteo
   gave it (`data/scores/forecast/models/<okres>.json`, rounded, with our combined
   series). Redistributing these raw values is allowed by CC BY 4.0 (UK Met Office: CC
   BY-SA 4.0) with attribution: every file carries `licence` and `attribution`, and the
   pages credit Open-Meteo and the model providers. The run's whole answer is also kept
   in the releases `outlook-models-YYYY-MM` (`outlook-models-YYYY-MM-DD.parquet`, one
   file per UTC day, same terms).
5. **Open data files** (`api/v1/`, roadmap 6.11) carry the licence (CC BY-SA 4.0) and
   the attribution text in every file; they are derived data (combined forecasts,
   scores), not a redistribution of the raw Open-Meteo API.
6. **Do not imply endorsement** by ČHMÚ, Open-Meteo or any model provider.
7. **GitHub:** data files live in Release assets (≤ 2 GiB each), not in git history.
   The scheduled workflows are this project's data pipeline, which GitHub Actions
   allows.
8. **No weather warnings.** Only ČHMÚ issues weather warnings (below). Our flags are
   named and labelled as MeteoVerdict thresholds, never as warnings, and wherever one
   is shown the page links ČHMÚ's official warnings.

## Weather warnings (Act 262/2024 Sb.)

Act No. 262/2024 Sb., on the public hydrometeorological service (*zákon o veřejné
hydrometeorologické službě*, in force since 1 January 2025;
[text](https://www.zakonyprolidi.cz/cs/2024-262), read 2026-10-19):

- **§ 6:** ČHMÚ has the *exclusive right* to issue and cancel hydrometeorological
  warnings (*výlučné oprávnění k vyhlašování nebo odvolávání hydrometeorologických
  výstrah*) and publishes them online.
- **§ 10:** it is an offence to publish or spread information that can give the
  misleading impression of being such a warning or its cancellation. For a natural
  person only if done intentionally (§ 10(1)); for a legal person or an entrepreneur
  without that condition (§ 10(2)). Fine up to **100,000 Kč** (§ 10(3)), handled by the
  Czech Environmental Inspectorate, **ČIŽP** (§ 10(4)).

What the project does about it (since October 2026):

- Threshold flags are named as thresholds: `gust_over_threshold` (corrected gust at
  least 13.5 m/s), `frost`, `ground_frost`, `heavy_rain`. The former `gust_warning` is
  kept for one API version as a deprecated alias with the same value (`outlook.json`,
  `api/v1`), then removed.
- The pages say "Gusts over 13.5 m/s (MeteoVerdict threshold, not an ČHMÚ warning)"
  instead of "Watch for strong gusts", and next to every flag "Not an official ČHMÚ
  warning; official warnings: chmi.cz" with a link to https://www.chmi.cz/. Every JSON
  file of `api/v1` carries the same `notice`, and so does `api/v1/index.json`. The CSV
  files of `api/v1` hold the hourly series only, with no flag, so they carry no notice;
  they stay plain CSV without a comment line, which `=IMPORTDATA` and Excel would show as
  a data row ([open-data.md](open-data.md)).
- Scores of event forecasts (POD, FAR on the comparison page) speak of *event
  forecasts* (*předpovědi jevu*), not warnings.

This is our reading of the Act, not legal advice.
