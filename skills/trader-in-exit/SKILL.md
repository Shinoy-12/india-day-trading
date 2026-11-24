---
name: trader-in-exit
description: >-
  Exit Planner for NSE day trades. Sets your stop and your target before you enter, so
  you know when to get out. Reads the entry from trader-in-entry (or a price you give),
  puts the stop at the opening-range midpoint by default (or the range low, your price,
  a percent, or a multiple of the ATR), rounds it down to the stock's NSE tick (from
  Kite), and sets the target at 2R (or 1R, or your price). Shows the round-trip Indian
  charges per share and sets flat-by before Zerodha's MIS square-off (15:05 by default).
  Refuses a stop at or above the entry, a target at or below it, or a stop too tight to
  survive the spread, and says why. Writes trader/plan.json for the Time Machine, the
  Budget Manager and Price Alerts. Long side only. Use when the user says "where's my
  stop", "set my stop and target", "plan the exit", "when do I get out", "stop loss",
  "what's my R", "risk reward", or right after /trader-in-entry triggers, before
  /trader-in-timemachine.
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
