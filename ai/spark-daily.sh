#!/bin/bash
# MeteoVerdict AI, once a day on the DGX Spark (cron, 08:30 Europe/Prague, after the
# daily scoring): fetch the archive, retrain and hindcast out of sample, make the live
# forecast per okres, score with `mvd blend-test --candidate`, publish ai.zip to the
# release ai-latest.
# The token (fine-grained, Contents: read and write on this repository only) is read
# from ~/.config/mv-ai/github-token and never stored in the repository.
set -euo pipefail
export PYTHONUNBUFFERED=1
export PATH="$HOME/.local/bin:$PATH"
cd "$HOME/meteoverdict"
git pull --ff-only -q
export GITHUB_REPOSITORY=JerryWoof/MeteoVerdict
GITHUB_TOKEN=$(cat "$HOME/.config/mv-ai/github-token")
export GITHUB_TOKEN
uv sync -q
uv sync -q --project ai
mkdir -p ai-out
uv run mvd stations --out data/stations.parquet
uv run --project ai mvai sync --months 4
last=$(date -u -d yesterday +%F)
first=$(date -u -d '45 days ago' +%F)
uv run --project ai mvai hindcast --first "$first" --last "$last" --history-days 40 \
  --cache ai-out/cache --out ai-out/hindcast.parquet
uv run --project ai mvai forecast --outlook data/outlook-models.zip
uv run mvd blend-test --days 45 --out ai-out/blend-test.json --candidate ai-out/hindcast.parquet
uv run --project ai mvai publish --blend-test ai-out/blend-test.json --upload
echo "done $(date -Is)"
