---
name: trader-in-timemachine
description: >-
  Time Machine for NSE day trades. Replays a plan (entry, stop, target) over 10,000 simulated sessions rebuilt from the stock's own 5-minute bars over the last 60 days and every past time the setup fired, with results net of Indian trading costs.
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
