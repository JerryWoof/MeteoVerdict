"""Probe the Open-Meteo Previous Runs archive for every model in models.yaml.

One request per model fetches the D+1 forecasts (``_previous_day1``) of the three
verified variables at Praha-Libuš since 2021, then reports per variable the first day
with data, the share of hours filled since then and the months below 90 %.
Prints a Markdown report.

Run (needs network): uv run scripts/probe_archive.py [--end YYYY-MM-DD] [--start YYYY-MM-DD]
[--model ID ...]  (default: every model in models.yaml; ``--model`` also takes ids that are
not in the catalogue yet). Cost: about 0.3 weighted calls per 14 days per model (45 for
2021 to 2026), so a narrower ``--start`` keeps it cheap.
"""

from __future__ import annotations

import argparse
import time
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import httpx

from meteoverdict.models import load_models

URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
PRAHA_LIBUS = (50.0078, 14.4469)
VARIABLES = ("temperature_2m", "precipitation", "wind_speed_10m")
EARLIEST = date(2021, 1, 1)


def fetch_d1(client: httpx.Client, model: str, end: date, start: date = EARLIEST) -> dict:
    lat, lon = PRAHA_LIBUS
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(f"{v}_previous_day1" for v in VARIABLES),
        "models": model,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }
    for wait in (10, 30, 60, None):
        response = client.get(URL, params=params)
        if response.status_code != 429 or wait is None:
            break
        time.sleep(wait)  # minutely rate limit
    response.raise_for_status()
    return response.json()["hourly"]


def summarise(times: list[str], values: list) -> tuple[str, str, str]:
    filled = [i for i, v in enumerate(values) if v is not None]
    if not filled:
        return "none", "", ""
    first = filled[0]
    total, ok = defaultdict(int), defaultdict(int)
    for t, v in zip(times[first:], values[first:], strict=True):
        total[t[:7]] += 1
        ok[t[:7]] += v is not None
    share = sum(ok.values()) / sum(total.values())
    low = ", ".join(f"{m} {ok[m] / total[m]:.0%}" for m in sorted(total) if ok[m] / total[m] < 0.9)
    return times[first][:10], f"{share:.0%}", low


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    default_end = datetime.now(UTC).date() - timedelta(days=2)
    parser.add_argument("--end", type=date.fromisoformat, default=default_end)
    parser.add_argument("--start", type=date.fromisoformat, default=EARLIEST)
    parser.add_argument("--model", action="append", help="model id; repeat for several")
    args = parser.parse_args()
    ids = args.model or [m.id for m in load_models()]
    print(
        f"Probed {datetime.now(UTC):%Y-%m-%d %H:%M} UTC at Praha-Libuš, D+1, "
        f"{args.start} to {args.end}\n"
    )
    print("| Model | Variable | First day | Hours filled since | Months below 90 % |")
    print("|---|---|---|---|---|")
    with httpx.Client(timeout=180, transport=httpx.HTTPTransport(retries=3)) as client:
        for model in ids:
            hourly = fetch_d1(client, model, args.end, args.start)
            for var in VARIABLES:
                first, share, low = summarise(hourly["time"], hourly[f"{var}_previous_day1"])
                print(f"| `{model}` | {var} | {first} | {share} | {low} |", flush=True)


if __name__ == "__main__":
    main()
