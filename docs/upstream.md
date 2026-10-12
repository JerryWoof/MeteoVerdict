# Upstream contributions

Roadmap 5.5: where could what this project learned about ČHMÚ open data help other
open-source projects? Checked on 2026-10-12 against the live services and the upstream
repositories; re-check before acting, both move quickly.

## wetterdienst

[wetterdienst](https://github.com/earthobservations/wetterdienst) (MIT) gives unified
access to observations of many national weather services.

**ČHMÚ is already covered.** The `chmi/observation` provider was added in July 2026
(upstream PR #1750); version 0.146.0 has resolutions `10_minutes`, `hourly`, `daily`,
`monthly` and `annual`. So "add CHMI to wetterdienst" is done; the useful gap is
narrower.

**The gap: only closed years.** The provider reads only
`meteorology/climate/historical_csv/`, which ČHMÚ updates once a year. It does not read
`recent/` (the current year, monthly JSON files per station) or `now/` (the last three
days, daily JSON files per station); see [data-sources.md](data-sources.md#directory-layout).
Measured with wetterdienst 0.146.0, daily mean temperature of station
`0-20000-0-11406`:

| Period requested | Values returned |
|---|---|
| 2025-12-01 … 2025-12-31 | 31 (1 Dec to 31 Dec 2025) |
| 2026-09-01 … 2026-09-30 | 0 |

The station's `historical_csv` daily file ends on 2025-12-31 (last modified
2026-09-04). Anyone who needs ČHMÚ data from this year, as this project does every
day, cannot get it from wetterdienst today.

**What we could contribute.** This project already reads `recent/` and `now/` and has
documented their formats from real files: the shared JSON envelope, file names (monthly
`recent/` files in month folders that hold the latest published year for that month,
daily `now/` files kept about three days), the ten-minute to hourly aggregation, and
the publication lag (the current month is only in `now/`). The natural contribution is a
`recent` period (and possibly `now`) for `chmi/observation`, starting with an issue that
proposes it and links this documentation. Our readers (`meteoverdict.chmi`,
`meteoverdict.observations`) are MIT like wetterdienst, but wetterdienst has its own
parser and data model, so the contribution would be new code in their structure, not a
copy of ours.

**Should meteoverdict use wetterdienst instead of its own reader?** Not now: without
`recent/` and `now/` it cannot feed the daily run, and the backfill needs the current
year too.

**AI policy.** wetterdienst's `CONTRIBUTING.md` has no rule on AI-assisted
contributions. The repository carries `AGENTS.md` and `CLAUDE.md` with instructions for
Claude Code, and its README thanks Anthropic for a Claude subscription for maintainers,
so AI-assisted work is evidently used by the maintainers themselves. A contribution
should still say openly how it was made, and be opened by a person who answers for it.

**Upstream activity.** The repository is very active (several issues and PRs a day,
including CHMI quality-flag work in October 2026), so an issue first is better than an
unannounced PR.

## Next step

Opening the issue (and later a PR) on wetterdienst has to come from the maintainer's
own GitHub account; it is roadmap 5.5b.
