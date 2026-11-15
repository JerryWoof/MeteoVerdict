// Decoding the heatmap's PNGs into the model's arrays. Dependency-free (no DOM, no imports) so
// the same code runs in the decode worker (heat-decode.worker.js) and, as a fallback, on the main thread.

/** Elevation in metres from RGBA pixels (R·256 + G); alpha 0 (outside Czechia) is 65535. */
export function heatDecodeElev(rgba) {
  const out = new Uint16Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4 + 3] ? rgba[i * 4] * 256 + rgba[i * 4 + 1] : 65535;
  return out;
}

/** Gray values from RGBA pixels (alpha 0 is 0: no data). */
export function heatDecodeGray(rgba) {
  const out = new Uint8Array(rgba.length / 4);
  for (let i = 0; i < out.length; i++) out[i] = rgba[i * 4 + 3] ? rgba[i * 4] : 0;
  return out;
}

/** A PNG's RGBA pixels exactly as stored (no colour conversion, no premultiplying). */
export async function decodePngPixels(blob) {
  const bitmap = await createImageBitmap(blob, { colorSpaceConversion: "none", premultiplyAlpha: "none" });
  const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0);
  bitmap.close();
  return ctx.getImageData(0, 0, canvas.width, canvas.height).data;
}

/** A PNG as the model's array: kind "elev" (Uint16Array) or "gray" (Uint8Array). */
export async function decodeHeatImage(blob, kind) {
  const rgba = await decodePngPixels(blob);
  return kind === "elev" ? heatDecodeElev(rgba) : heatDecodeGray(rgba);
}
