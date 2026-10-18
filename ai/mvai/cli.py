"""``mvai``: MeteoVerdict AI on the DGX Spark."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from mvai import data, gbm, live, publish

MODEL_ID = "meteoverdict_ai"


def hindcast_cmd(args: argparse.Namespace) -> None:
    first, last = date.fromisoformat(args.first), date.fromisoformat(args.last)
    history = first - timedelta(days=args.history_days)
    fc, obs = data.load(args.data, history, last)
    stations = pl.read_parquet(args.stations)
    parts = []
    for variable in data.VARIABLES:
        wide, cols = data.table(fc, obs, stations, variable)
        print(f"{variable}: {wide.height:,} rows, {len(cols)} models")
        pred = gbm.hindcast(wide, cols, variable, first, last, cache=args.cache)
        if not pred.is_empty():
            parts.append(data.as_forecasts(pred, variable, args.model_id))
    keys = ["station_id", "time", "model", "lead_day"]
    out = parts[0]
    for p in parts[1:]:
        out = out.join(p, on=keys, how="full", coalesce=True)
    out = out.with_columns(pl.lit(None, pl.Float32).alias("precipitation")).select(
        "station_id", "time", "model", "lead_day",
        "temperature_2m", "precipitation", "wind_speed_10m",
    )  # fmt: skip
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(args.out)
    print(f"→ {args.out} ({out.height:,} rows)")


def forecast_cmd(args: argparse.Namespace) -> None:
    """The live AI forecast per okres (``ai-forecast.json``)."""
    from datetime import UTC, datetime

    docs = live.okres_forecasts(args.outlook)
    generated = min(d["generated"] for d in docs.values())
    issued = datetime.fromisoformat(generated.replace("Z", "+00:00")).astimezone(UTC)
    today = issued.date()
    fc, obs = data.load(args.data, today - timedelta(days=args.history_days), today)
    stations = pl.read_parquet(args.stations)
    pools = live.pools_of(args.data / "scores", stations, issued)
    frames = {}
    for variable in data.VARIABLES:
        wide, cols = data.table(fc, obs, stations, variable)
        train = wide.filter((pl.col("date") < today) & pl.col("obs").is_not_null())
        booster = gbm.fit(train, cols, today)
        measured = (
            wide.filter(pl.col("obs").is_not_null())
            .select("station_id", "time", "obs")
            .unique(["station_id", "time"])
        )
        context = live.station_context(wide, measured, stations, issued)
        frames[variable] = live.forecast(booster, cols, variable, docs, pools, context, issued)
        print(
            f"{variable}: trained on {train.height:,} rows, "
            f"{frames[variable]['okres'].n_unique() if frames[variable].height else 0} okresy"
        )
    names = dict(stations.select("okres_code", "okres").unique().iter_rows())
    doc = live.document(frames, issued, generated, names)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    path = args.out_dir / "ai-forecast.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    print(f"→ {path} ({len(doc['okresy'])} okresy, issued {issued:%Y-%m-%d %H:%M} UTC)")


def sync_cmd(args: argparse.Namespace) -> None:
    """The months' observations, forecasts, scores and single runs from the releases."""
    import os

    import httpx

    from meteoverdict import runs, store
    from meteoverdict.releases import GitHubReleaseStore

    today = date.today()
    days = (today - timedelta(days=30 * k) for k in range(args.months))
    months = sorted({d.strftime("%Y-%m") for d in days})
    repo = os.environ.get("GITHUB_REPOSITORY", "JerryWoof/MeteoVerdict")
    token = os.environ.get("GITHUB_TOKEN", "")
    with httpx.Client(timeout=600, transport=httpx.HTTPTransport(retries=3)) as client:
        releases = GitHubReleaseStore(client, repo, token, notes=store.RELEASE_NOTES)
        if not token:  # public releases read without a token (the Mac uploads the results)
            releases.headers.pop("Authorization")
        done = store.download(releases, args.data, months, print)
        runs.RunsSync(releases, args.data, print).pull(months)
        # every model's forecast per okres for the next days (`mvd outlook`)
        releases.download(store.LATEST_TAG, "outlook-models.zip", args.data / "outlook-models.zip")
    print(f"{len(done)} monthly files downloaded for {', '.join(months)}")


def publish_cmd(args: argparse.Namespace) -> None:
    blend_test = json.loads(args.blend_test.read_text())
    sm = blend_test["single_models"]
    at = sm["columns"].index("model")
    models = len({r[at] for r in sm["rows"]} - {args.model_id})
    found = publish.results(args.results)
    doc = publish.document(blend_test, args.model_id, models, found)
    path = publish.write_zip(doc, args.out_dir, args.results)
    for row in doc["scores"]:
        print(f"{row['variable']:15} D+{row['lead_day']}  AI {row['mae_ai']:.3f}  "
              f"combined {row['mae_combined']:.3f}  diff {row['diff']:+.3f} "
              f"[{row['low']:+.3f}, {row['high']:+.3f}]")  # fmt: skip
    if args.upload:
        publish.upload(path)
        print(f"→ release {publish.TAG}: {path.name}")
    else:
        print(f"→ {path}")


def main() -> None:
    p = argparse.ArgumentParser(prog="mvai")
    sub = p.add_subparsers(required=True)
    h = sub.add_parser("hindcast", help="out-of-sample predictions for blend-test --candidate")
    h.add_argument("--data", type=Path, default=Path("data"))
    h.add_argument("--stations", type=Path, default=Path("data/stations.parquet"))
    h.add_argument("--first", required=True)
    h.add_argument("--last", required=True)
    h.add_argument("--history-days", type=int, default=60)
    h.add_argument("--model-id", default=MODEL_ID)
    h.add_argument("--out", type=Path, default=Path("ai-out/hindcast.parquet"))
    h.add_argument("--cache", type=Path, help="keep and reuse each issue day's predictions")
    h.set_defaults(func=hindcast_cmd)
    f = sub.add_parser("forecast", help="the live AI forecast per okres")
    f.add_argument("--data", type=Path, default=Path("data"))
    f.add_argument("--stations", type=Path, default=Path("data/stations.parquet"))
    f.add_argument("--outlook", type=Path, required=True, help="outlook-models.zip")
    f.add_argument("--history-days", type=int, default=40)
    f.add_argument("--out-dir", type=Path, default=Path("ai-out/site"))
    f.set_defaults(func=forecast_cmd)
    y = sub.add_parser("sync", help="download the archive months from the releases")
    y.add_argument("--data", type=Path, default=Path("data"))
    y.add_argument("--months", type=int, default=4)
    y.set_defaults(func=sync_cmd)
    u = sub.add_parser("publish", help="ai.json for the AI forecast tab (release ai-latest)")
    u.add_argument("--blend-test", type=Path, required=True)
    u.add_argument("--model-id", default=MODEL_ID)
    u.add_argument("--out-dir", type=Path, default=Path("ai-out/site"))
    u.add_argument("--upload", action="store_true")
    u.add_argument(
        "--results", type=Path, default=Path.home() / "mv-ai" / "results",
        help="the experiments' own results (<id>.json and the files their maps name)",
    )  # fmt: skip
    u.set_defaults(func=publish_cmd)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
