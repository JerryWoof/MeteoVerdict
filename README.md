# MeteoVerdict radar, live

The radar frames of the last hours (reflectivity, MERGE precipitation, echo tops, motion fields, storm cells), the newest nowcast and Meteosat images for https://meteoverdict.cz/radar.html, replaced every 5 minutes by the Radar workflow (this branch has a single commit). Format: docs/data-sources.md#radar-live-data-contract in the main branch.

Radar data: Czech Hydrometeorological Institute (ČHMÚ / CHMI), opendata.chmi.cz, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). PNG frames cropped to the data area, with the frame, labels and background made transparent, by MeteoVerdict.

Satellite images: contains modified EUMETSAT Meteosat data 2026 (CC BY 4.0), processed by ČHMÚ (opendata.chmi.cz, CC BY 4.0); cropped and converted to WebP by MeteoVerdict.
