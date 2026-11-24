---
name: trader-in-exit
description: >-
  Exit Planner for NSE day trades. Sets stop and target before entry, rounded to valid NSE ticks, at the opening-range midpoint by default and 2R target, with R measured net of trading costs.
---

# trader-in-exit

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] `CENT` / `cents()` / `floor_cents()` -> `floor_tick()` (stop) and `ceil_tick()`; tick depends on price band.
- [x] Minimum-risk check should include round-trip costs: a 1R that costs 30% in fees is not 1R.
- [x] Warn when stop or target is beyond the stock's circuit limit.
- [x] Use the stock's own `tick_size` from Kite (`market.search` get_by_id, verbosity full) in `floor_tick()`/`ceil_tick()`; the band table is only a fallback.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
