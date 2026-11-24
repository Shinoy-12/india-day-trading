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

## Missing bars: patch only the gaps from Kite (keeps tokens low)
Run `entry.py` on Yahoo as usual; that costs no tokens. Yahoo's 5-minute NSE bars sometimes skip a bar. When one is missing, `entry.py` answers NO DATA, names the missing times, and with `--json` gives the exact Kite window in `kite_fetch`. Then, if the Kite MCP's `market` tool is available:

1. Get the instrument token (once per stock): `market` with `mode=search`, `search_mode=get_by_id`, `id=NSE:<SYMBOL>`.
2. Fetch only that window: `market` with `mode=historical`, `instrument_token`, and the `interval`, `from_date` and `to_date` from `kite_fetch`. Keep `to_date` at the END of the last missing bar: Kite cuts a candle off at `to_date`, so an earlier end gives a partial candle.
3. Save the answer as JSON (for example `trader/bars/raw.json`) and run `python3 shared/kite_bars.py add <SYMBOL> trader/bars/raw.json`. It keeps closed candles only, in `trader/bars/kite-<SYMBOL>-<date>.json`.
4. Run the same `entry.py` check again. Kite's bars fill Yahoo's gaps by themselves from now on (Yahoo's own bars are never replaced), and the output says "Patched from Kite: 11:35". A slot is fetched from Kite once a day, not on every check.

Without the Kite MCP, tell the user bars are missing and don't call the entry. To run on Kite alone for a whole day instead: `kite_bars.py file <SYMBOL> raw.json`, then `entry.py check <SYMBOL> --offline trader/bars`.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] `DEFAULTS`: no_entries_before 09:30, no_entries_after e.g. 14:45 (leave room before square-off).
- [x] `yahoo_symbol()` replaces the US version (which turns `.` into `-`).
- [x] Skip the 09:00-09:08 pre-open auction when building bars.
- [x] Refuse when the stock is at or near its upper circuit.
- [x] F&O stocks: pass `fno_stock=True` to `session()`; continuous trading ends 15:15 (closing auction), so no entries near it.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
