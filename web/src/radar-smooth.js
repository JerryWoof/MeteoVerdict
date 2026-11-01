// Smooth drawing of a radar frame at k × the grid's resolution. The frames are classes (levels
// 1 … 15) on ČHMÚ's ~1 km grid; drawing each cell as a flat square and letting the map stretch
// it looks coarse. Here the *level* is interpolated bilinearly between the cell centres and only
// then rounded and coloured from the table, so every pixel still has exactly a legend colour
// (no blended colours) and a cell centre keeps its own class. Edges become diagonal and round
// instead of staircases; coverage (no data) and "aloft" follow the nearest cell.
import { ALOFT, NODATA } from "./radar-palette.js";

const LEVEL = new Uint8Array(256);
for (let c = 0; c < 256; c++) LEVEL[c] = c & NODATA ? 0 : c & 31;

/**
 * Draw `codes` (w × h) into `out` (packed RGBA, w·k × h·k) with the colour table `lut`.
 * The output pixel centres are the source's sub-cell centres, so the picture stays aligned.
 */
export function smoothDraw(out, codes, w, h, k, lut) {
  const ow = w * k;
  const oh = h * k;
  const x0 = new Int32Array(ow);
  const x1 = new Int32Array(ow);
  const fx = new Float32Array(ow);
  for (let ox = 0; ox < ow; ox++) {
    const sx = (ox + 0.5) / k - 0.5;
    const i = Math.floor(sx);
    x0[ox] = Math.max(0, Math.min(w - 1, i));
    x1[ox] = Math.max(0, Math.min(w - 1, i + 1));
    fx[ox] = Math.min(1, Math.max(0, sx - i));
  }
  const nodata = lut[NODATA];
  for (let oy = 0; oy < oh; oy++) {
    const sy = (oy + 0.5) / k - 0.5;
    const j = Math.floor(sy);
    const r0 = Math.max(0, Math.min(h - 1, j)) * w;
    const r1 = Math.max(0, Math.min(h - 1, j + 1)) * w;
    const fy = Math.min(1, Math.max(0, sy - j));
    for (let ox = 0; ox < ow; ox++) {
      const a = x0[ox];
      const b = x1[ox];
      const c00 = codes[r0 + a];
      const c10 = codes[r0 + b];
      const c01 = codes[r1 + a];
      const c11 = codes[r1 + b];
      const gx = fx[ox];
      const top = LEVEL[c00] + (LEVEL[c10] - LEVEL[c00]) * gx;
      const bottom = LEVEL[c01] + (LEVEL[c11] - LEVEL[c01]) * gx;
      const level = Math.round(top + (bottom - top) * fy);
      const o = oy * ow + ox;
      // the nearest cell: its coverage and (where it has an echo) its aloft flag
      const nearest = fy < 0.5 ? (gx < 0.5 ? c00 : c10) : gx < 0.5 ? c01 : c11;
      if (level === 0) {
        out[o] = nearest & NODATA ? nodata : 0;
        continue;
      }
      let flag = LEVEL[nearest] ? nearest & ALOFT : 0;
      if (!LEVEL[nearest]) {
        // no echo at the nearest cell: the strongest of the four lends its flag
        let best = c00;
        for (const c of [c10, c01, c11]) if (LEVEL[c] > LEVEL[best]) best = c;
        flag = best & ALOFT;
      }
      out[o] = lut[level | flag];
    }
  }
  return out;
}
