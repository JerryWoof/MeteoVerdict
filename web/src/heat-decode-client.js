import { decodeHeatImage } from "./heat-decode.js";

let worker; // undefined: not tried yet, null: unavailable
let nextId = 0;
const pending = new Map();

function startWorker() {
  if (typeof Worker === "undefined" || typeof OffscreenCanvas === "undefined" || typeof createImageBitmap === "undefined") return null;
  try {
    const w = new Worker(new URL("./heat-decode.worker.js", import.meta.url), { type: "module" });
    w.onmessage = ({ data }) => {
      const job = pending.get(data.id);
      if (!job) return;
      pending.delete(data.id);
      if (data.error) job.reject(new Error(data.error));
      else job.resolve(data.array);
    };
    w.onerror = () => {
      // the worker cannot run here: this and later images decode on the main thread
      worker = null;
      w.terminate();
      for (const job of pending.values()) job.reject(new Error("worker failed"));
      pending.clear();
    };
    return w;
  } catch {
    return null;
  }
}

/** A PNG blob as the model's array ("elev": Uint16Array, "gray": Uint8Array), decoded in a worker when there is one. */
export async function decodeHeatBlob(blob, kind) {
  if (worker === undefined) worker = startWorker();
  if (worker) {
    try {
      return await new Promise((resolve, reject) => {
        const id = nextId++;
        pending.set(id, { resolve, reject });
        worker.postMessage({ id, blob, kind });
      });
    } catch {
      // fall through to the main thread
    }
  }
  return decodeHeatImage(blob, kind);
}
