---
name: trader-in-timemachine
description: >-
  Time Machine for NSE day trades. Replays every possible outcome of a trade before you
  risk a rupee: 10,000 simulated sessions plus every past time the setup fired. Takes
  the plan from trader-in-exit (entry, stop, target), rebuilds the rest of the day
  10,000 times from the stock's own 5-minute bars over the last 60 days (75-bar NSE
  sessions, 72 for F&O stocks), and re-runs the same rule on every past session up to
  your flat-by time. Prints the odds of target first, stop first, or neither, where the
  price sits at flat-by, the average R before and after Indian charges, the history, and
  one honest verdict, then hands off to /trader-in-budget. Use when the user says "run
  the time machine", "replay this trade", "what are the odds", "simulate this trade",
  "monte carlo", "backtest this setup", "how often does this hit the target", "is this a
  coin flip", or after /trader-in-exit writes a plan, before /trader-in-budget.
---

# trader-in-timemachine

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] Session end = `FLAT_BY` / square-off, not 16:00.
- [x] Subtract `round_trip_costs()` from every simulated outcome before averaging R.
- [x] Tick-aware rounding instead of 0.01; Yahoo `.NS` symbols.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
