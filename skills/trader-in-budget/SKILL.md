---
name: trader-in-budget
description: >-
  Budget Manager. Sizes every NSE position in whole shares to your rupee budget and max loss per trade, net of Indian trading costs (STT, exchange, SEBI, stamp duty, GST, brokerage), and writes one order plan in Kite's shape. Nothing is placed.
---

# trader-in-budget

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Max loss per trade includes `round_trip_costs()` at the stop, not just (entry - stop) x qty.
- [x] Intraday leverage cap from `india_rules.json` (`intraday_leverage`) replaces US margin logic.
- [x] Order output in Kite's shape (see trader-in-broker) instead of Alpaca bracket JSON.
- [x] Prices via `ceil_tick()` / `floor_tick()` instead of cents; $ -> ₹.
- [x] Leverage per stock from `mis_leverage()`; costs use `round_trip_costs(..., exchange)` (NSE vs BSE charges differ).
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
