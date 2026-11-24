---
name: trader-in-entry
description: >-
  Entry Timer for NSE stocks. Watches a setup bar by bar and tells you the moment to get
  in. Reads free Yahoo 1-minute or 5-minute bars (.NS), builds the opening range (09:15
  to 09:30 IST by default) and calls the entry on the first completed bar that CLOSES
  above the range high, or above a level you give it (like a 20-day high from the
  scanner), with an optional volume check. Knows NSE holidays and that F&O stocks stop
  at 15:15 for the closing auction. Says waiting and how far, triggered with the time
  and the price, expired, or not open yet, and writes trader/entry.json for
  /trader-in-exit. Long side only. It never places an order. Use when the user says
  "tell me when to get in", "watch RELIANCE", "has it broken out", "did it break the
  opening range", "entry signal", "time my entry", "check my watchlist", or after
  /trader-in-scanner and /trader-in-news, before /trader-in-exit.
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
