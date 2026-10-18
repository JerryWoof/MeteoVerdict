"""``ai.json`` for the site's AI forecast tab (web/ai.html): MeteoVerdict AI's
out-of-sample scores from ``mvd blend-test --candidate`` and the list of experiments.
Uploaded as ``ai.zip`` to the release ``ai-latest``; the Pages build unpacks it into
``site/data/ai``."""

from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from meteoverdict.releases import GitHubReleaseStore

TAG = "ai-latest"
NOTES = (
    "Experimental: MeteoVerdict AI and other machine-learning forecasts, computed daily "
    "on an NVIDIA DGX Spark (ai/ in the repository). Read by the site's AI forecast tab."
)
VARIABLES = ("temperature_2m", "wind_speed_10m")

# status: planned, testing, works (the whole interval better than the combined
# forecast), no_gain; tech: one line on the technology
EXPERIMENTS = [
    {"id": "meteoverdict_ai", "tech": "XGBoost 3 (gradient-boosted trees) on the Blackwell GPU"},
    {
        "id": "deep_blend",
        "status": "planned",
        "tech": "PyTorch: transformer / graph neural network",
    },
    {
        "id": "downscale_100m",
        "status": "planned",
        "tech": "ML on 30 m terrain (Copernicus DEM), U-Net",
    },
    {
        "id": "atlas_ensemble",
        "status": "planned",
        "tech": "NVIDIA Earth-2 Medium Range (Atlas), Earth2Studio",
    },
    {"id": "aifs_ens", "status": "planned", "tech": "ECMWF AIFS ENS v2 open data"},
    {"id": "regimes", "status": "planned", "tech": "NVIDIA RAPIDS (cuML): clustering, SHAP"},
    {"id": "nowcast", "status": "planned", "tech": "pysteps vs. deep generative nowcasting"},
    {
        "id": "chronos",
        "status": "planned",
        "tech": "Chronos / TimesFM (time-series foundation models)",
    },
    {"id": "weathernext3", "status": "planned", "tech": "Google WeatherNext 3 (access on request)"},
]


def scores(blend_test: dict, model_id: str) -> list[dict]:
    """Czechia rows of ``model_id``: its MAE, the combined forecast's and the best
    model's (best_oos), and AI minus combined with its 95 % interval."""
    groups = blend_test["groups"]
    g = [dict(zip(groups["columns"], r, strict=True)) for r in groups["rows"]]
    best = {(r["variable"], r["lead_day"]): r["mae_best_oos"] for r in g if r["level"] == "cz"}
    sm = blend_test["single_models"]
    out = []
    for row in (dict(zip(sm["columns"], r, strict=True)) for r in sm["rows"]):
        if row["model"] != model_id or row["variable"] not in VARIABLES:
            continue
        # diff_combined is combined minus the model: flip it to AI minus combined
        out.append({
            "variable": row["variable"], "lead_day": row["lead_day"], "days": row["days"],
            "mae_ai": row["mae"], "mae_combined": row["mae_combined"],
            "mae_best": best.get((row["variable"], row["lead_day"])),
            "diff": -row["diff_combined"], "low": -row["high_combined"],
            "high": -row["low_combined"],
        })  # fmt: skip
    return sorted(out, key=lambda r: (VARIABLES.index(r["variable"]), r["lead_day"]))


def status(rows: list[dict]) -> str:
    if not rows:
        return "testing"
    if any(r["high"] < 0 for r in rows):
        return "works"
    if all(r["low"] > 0 for r in rows):
        return "no_gain"
    return "testing"


#: what an experiment's own run leaves (``<id>.json``, see ai/README.md) and may show
RESULT_KEYS = ("status", "tech", "headline", "table", "period", "map", "drivers", "generated")


def results(results_dir: Path | None) -> dict[str, dict]:
    """The experiments' own results (``<results_dir>/<id>.json``) by id."""
    if results_dir is None or not results_dir.is_dir():
        return {}
    out = {}
    for path in sorted(results_dir.glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(doc, dict) and doc.get("id"):
            out[doc["id"]] = {k: doc[k] for k in RESULT_KEYS if k in doc}
    return out


def document(
    blend_test: dict, model_id: str, models: int, found: dict[str, dict] | None = None
) -> dict:
    rows = scores(blend_test, model_id)
    found = found or {}
    experiments = []
    for e in EXPERIMENTS:
        e = {**e, **found.get(e["id"], {})}
        if e["id"] == "meteoverdict_ai":
            e["status"] = status(rows)
            first = [r for r in rows if r["variable"] == "temperature_2m" and r["lead_day"] == 1]
            if first:
                d1 = first[0]
                e["result"] = {
                    "ai": round(d1["mae_ai"], 2),
                    "combined": round(d1["mae_combined"], 2),
                }
        experiments.append(e)
    return {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": {"id": model_id, "name": "MeteoVerdict AI", "version": "v1", "models": models},
        "test": {
            "from": blend_test["from"], "to": blend_test["to"], "days": blend_test["test_days"],
        },
        "scores": rows,
        "experiments": experiments,
    }  # fmt: skip


def write_zip(doc: dict, out_dir: Path, results_dir: Path | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ai.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    path = out_dir / "ai.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(out_dir / "ai.json", "ai.json")
        # the files an experiment's map points to (e.g. the 100 m temperature image)
        for e in doc["experiments"]:
            for key in ("png", "meta"):
                name = (e.get("map") or {}).get(key)
                if not isinstance(name, str):
                    continue
                source = results_dir / name if results_dir else None
                if source is not None and source.is_file() and ".." not in name:
                    z.write(source, name)
        # the live forecast per okres (`mvai forecast`), when it was made
        if (out_dir / "ai-forecast.json").exists():
            z.write(out_dir / "ai-forecast.json", "ai-forecast.json")
    return path


def upload(path: Path) -> None:
    """Put ``path`` into the release ``ai-latest`` (GITHUB_TOKEN, GITHUB_REPOSITORY)."""
    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=300, transport=httpx.HTTPTransport(retries=3)) as client:
        GitHubReleaseStore(client, repo, token, notes=NOTES).put(TAG, path.name, path)
