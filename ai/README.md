# MeteoVerdict AI (experimental)

Machine-learning forecasts for the site's **AI forecast** tab (`web/ai.html`). They are
trained once a day on an NVIDIA DGX Spark (GB10 Grace Blackwell, 128 GB of memory shared
by CPU and GPU). Everything here is experimental: an experiment is called "works" only
when `mvd blend-test` shows it beating the combined forecast out of sample, with the
whole 95 % interval below zero.

This is its own uv project, because it needs GPU packages (XGBoost with CUDA, and
PyTorch for the deep experiments) that the site's daily pipeline on GitHub Actions does
not. It uses the `meteoverdict` package from the repository root.

## MeteoVerdict AI v1

Gradient-boosted trees (XGBoost 3 on the GPU, MAE objective). Separate models for
temperature and wind, each covering all stations and lead days. The tree predicts
how much to correct the median of all models. Its inputs are:

- each model's deviation from that median (19 models);
- the spread of the models (mean, standard deviation, minimum, maximum and count);
- the station's position and elevation;
- the hour and the lead day;
- what was known when the forecast was made: the station's mean error at that hour
  over the last 3 and 14 days, and the measured value at the same hour on the issue day.

Training gives recent days more weight (half-life 14 days). There are no calendar
features: with months rather than years of history, the trees tied summer's corrections
to the date and carried them into autumn. In v0 that made temperature 0.35 °C too warm.

Out of sample, exactly as live: for every issue day *i* one model is trained on the days
before *i* and predicts days *i* + 1 … *i* + 5. Then
`mvd blend-test --candidate` scores it like the combined forecast, at 00, 06, 12 and
18 UTC on the same station-days. Candidates never enter the training of the
combination, the out-of-sample choice or the hindsight best.

## On the Spark

```bash
cd ~/meteoverdict
uv sync --project ai            # XGBoost with CUDA (aarch64 wheels)
uv sync --project ai --extra deep   # + PyTorch cu130 for the deep experiments
ai/spark-daily.sh               # what cron runs at 08:30 Europe/Prague
```

`spark-daily.sh` does the whole run:

1. Downloads the last four months of the archive (`mvai sync`).
2. Trains and predicts the new issue day. Earlier days come from the cache in
   `ai-out/cache/`.
3. Scores the last 45 days with `mvd blend-test --candidate`.
4. Uploads `ai.zip` to the release `ai-latest` (`mvai publish --upload`). The Pages
   build unpacks it into `site/data/ai/`.

It needs a fine-grained GitHub token with Contents read and write on this repository
only, in `~/.config/mv-ai/github-token`. The token is never in the repository.

## Experiments

The list with their status is in `mvai/publish.py` (`EXPERIMENTS`); the texts are in
`web/src/i18n.js` (`ai.exp.*`).
