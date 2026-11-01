# Monthly accuracy report

`mvd monthly-report YYYY-MM` writes the accuracy report of one finished calendar month
from the scores we already have; used to be drawn by `report.html`; the page and its footer link were removed in November 2026 (the files under `site/reports` are still written).

```
mvd store download --from 2026-09            # scores-2026-09.parquet from the release data-2026-09
mvd stations                                 # the station table, if data/stations.parquet is missing
mvd monthly-report 2026-09                   # → site/reports/2026-09.json and index.json
```

## What it does

- Takes the days of the month from `data/scores/YYYY-MM.parquet` and treats them as a
  window of their own: `aggregate.aggregate` and `ranking.rank` run on those days only,
  at the levels Czechia and okres. So the report uses the **same fair sample** (the
  station-days every compared model has), the **80 % coverage rule** and the **tie rule**
  (blocks of 4 consecutive days resampled 1,000 times, "≈" unless the 95 % interval of
  the difference to the best excludes zero and the Diebold–Mariano test agrees) as the web pages. It refuses a month with fewer than 20 scored days.
- Variables: temperature at 2 m, wind at 10 m, precipitation (the 06–06 UTC total, which
  also covers the manual gauges); leads D+1 … D+5.
- Per variable and lead, for Czechia: every model's MAE and bias, who is best, who is
  tied with the best, whether there is a clear winner, and how the plain mean of all
  models compares (`mean_of_all`; this is **not** our combined forecast, whose
  out-of-sample check is `blend-test.json`).
- For D+1 and D+3: in how many okresy each model is first, and in how many of them
  clearly.

## Publishing

`site/reports/*.json` (and an optional `YYYY-MM.pdf` next to it) are committed;
`web/scripts/copy-data.mjs` copies the folder into the site, and the Pages workflow runs
on changes to it. The PDF is the page printed from Chrome (the page has a print style):

```
google-chrome --headless=new --no-pdf-header-footer --virtual-time-budget=15000 \
  --print-to-pdf=site/reports/2026-09.pdf "http://localhost:5173/report.html#2026-09"
```

Nothing is sent to anyone; sending the report on is a decision for the owner.

## Caveats (also on the page)

One month only, so the ranking may flip in other weather; ties are normal and common for
rain; each lead compares only the models that reach it; points against grid cells and
Open-Meteo's processing; ČHMÚ may not yet have checked the last days of the month
(regenerate afterwards); it says who got it right, not why.
