// The heatmap's PNG decoding off the main thread: gets { id, blob, kind }, answers { id, array }
// (the array's buffer is transferred, not copied) or { id, error }.
import { decodeHeatImage } from "./heat-decode.js";

self.onmessage = async ({ data: { id, blob, kind } }) => {
  try {
    const array = await decodeHeatImage(blob, kind);
    self.postMessage({ id, array }, [array.buffer]);
  } catch (error) {
    self.postMessage({ id, error: String(error?.message ?? error) });
  }
};
