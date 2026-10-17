// The radar page's base map: light and muted so the radar colours stay readable.
// - OpenFreeMap vector tiles (OpenMapTiles schema, OSM data, ODbL): water, rivers, main
//   roads, the national border and the town and village labels; glyphs from OpenFreeMap.
// - AWS Terrain Tiles (terrarium, s3 open data) as a faint hillshade.
// Order on the map: land, hillshade, water, roads | satellite, radar, … | borders, labels.
// docs/licensing.md and docs/data-sources.md ("Radar base map") credit both.

import { OSM_COPYRIGHT, TERRAIN_ATTRIBUTION } from "./footer.js";

export const GLYPHS = "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf";
const TILES = "https://tiles.openfreemap.org/planet";
const TERRAIN = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

// OpenFreeMap's TileJSON adds "OpenFreeMap © OpenMapTiles Data from OpenStreetMap" (with
// links) to the attribution control itself; we add the wording ODbL asks for and the relief
export const BASEMAP_ATTRIBUTION = [
  `<a href="${OSM_COPYRIGHT}" target="_blank">© OpenStreetMap contributors</a>`,
  `<a href="${TERRAIN_ATTRIBUTION}" target="_blank">Relief: Terrain Tiles (EU-DEM, SRTM, …)</a>`,
].join(" · ");

export const LAND = "#f3f1ec";
const WATER = "#b6c8d6";
const TEXT_HALO = "rgba(255,255,255,0.9)";

/** The labels that select their place when clicked. */
export const PLACE_LAYERS = ["place-village", "place-town", "place-city"];

export function basemapSources() {
  return {
    omt: { type: "vector", url: TILES },
    // terrarium tiles go to z15; z11 is enough for a faint relief and keeps requests few
    terrain: { type: "raster-dem", tiles: [TERRAIN], encoding: "terrarium", tileSize: 256, maxzoom: 11 },
  };
}

/** Under the radar: hillshade, water, rivers, main roads. */
export function baseLayers() {
  return [
    { id: "background", type: "background", paint: { "background-color": LAND } },
    {
      id: "hillshade", type: "hillshade", source: "terrain",
      paint: {
        "hillshade-exaggeration": ["interpolate", ["linear"], ["zoom"], 5, 0.55, 10, 0.35],
        "hillshade-shadow-color": "#5f6469",
        "hillshade-highlight-color": "#ffffff",
        "hillshade-accent-color": "#9a9ea2",
      },
    },
    { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": WATER } },
    {
      id: "waterway", type: "line", source: "omt", "source-layer": "waterway", minzoom: 6,
      filter: ["any", ["==", ["get", "class"], "river"], [">=", ["zoom"], 10]],
      paint: {
        "line-color": WATER,
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, ["match", ["get", "class"], "river", 0.8, 0.3], 9, ["match", ["get", "class"], "river", 1.3, 0.4], 12, ["match", ["get", "class"], "river", 2.2, 0.8]],
      },
    },
    {
      id: "roads", type: "line", source: "omt", "source-layer": "transportation", minzoom: 6,
      filter: [
        "all",
        ["!=", ["get", "brunnel"], "tunnel"],
        ["any", ["match", ["get", "class"], ["motorway", "trunk"], true, false], ["all", ["==", ["get", "class"], "primary"], [">=", ["zoom"], 8]]],
      ],
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#d9d3c7",
        "line-width": ["interpolate", ["linear"], ["zoom"], 6, ["match", ["get", "class"], "primary", 0.4, 0.7], 12, ["match", ["get", "class"], "primary", 1.6, 2.4]],
      },
    },
  ];
}

const name = (language) => ["coalesce", ["get", `name:${language}`], ["get", "name"]];

function place(id, classes, minzoom, size, colour, font = "Noto Sans Regular") {
  return {
    id, type: "symbol", source: "omt", "source-layer": "place", minzoom,
    filter: ["match", ["get", "class"], classes, true, false],
    layout: {
      "text-field": null, // set by topLayers (the page's language)
      "text-font": [font],
      "text-size": ["interpolate", ["linear"], ["zoom"], ...size],
      "text-max-width": 8,
      "symbol-sort-key": ["coalesce", ["get", "rank"], 99],
    },
    paint: { "text-color": colour, "text-halo-color": TEXT_HALO, "text-halo-width": 1.4, "text-halo-blur": 0.3 },
  };
}

/** Over the radar: the national border and the place labels (more as you zoom). */
export function topLayers(language) {
  const labels = [
    place("place-village", ["village"], 10, [10, 10.5, 14, 13], "#4b535a"),
    place("place-town", ["town"], 7.5, [7.5, 10.5, 12, 14], "#353d44"),
    place("place-city", ["city"], 5, [5, 11, 10, 16], "#22292f", "Noto Sans Bold"),
  ];
  for (const layer of labels) layer.layout["text-field"] = name(language);
  return [
    {
      id: "country-line", type: "line", source: "omt", "source-layer": "boundary",
      filter: ["all", ["==", ["get", "admin_level"], 2], ["!=", ["get", "maritime"], 1]],
      layout: { "line-join": "round" },
      paint: { "line-color": "#59636b", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 1, 10, 2] },
    },
    ...labels,
  ];
}
