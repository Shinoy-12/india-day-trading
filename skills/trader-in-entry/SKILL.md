---
name: trader-in-entry
description: >-
  Entry Timer for NSE stocks. Builds the opening range (09:15-09:30 IST by default) from free Yahoo 1m/5m bars and calls the entry on the first completed bar that closes above the range high or your level. Long side only; never places an order.
---

# trader-in-entry

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] `DEFAULTS`: no_entries_before 09:30, no_entries_after e.g. 14:45 (leave room before square-off).
- [x] `yahoo_symbol()` replaces the US version (which turns `.` into `-`).
- [x] Skip the 09:00-09:08 pre-open auction when building bars.
- [x] Refuse when the stock is at or near its upper circuit.
- [x] F&O stocks: pass `fno_stock=True` to `session()`; continuous trading ends 15:15 (closing auction), so no entries near it.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
