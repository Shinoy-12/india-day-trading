---
name: trader-in-budget
description: >-
  Budget Manager. Sizes every NSE position to your rupee budget and your max loss per
  trade, counting Indian charges (brokerage, STT, exchange, SEBI, stamp duty, GST).
  Reads the trade plan from trader-in-exit (entry, stop, target), finds the whole shares
  that fit inside four limits (max loss per trade, position cap, max order, cash after
  your buffer, optionally times the stock's Zerodha MIS leverage), says which limit
  decided it, and writes ONE bracket order to trader/orders.json for trader-in-risk and
  trader-in-broker. A stop too far away for your max loss is a plain refusal, not a
  smaller order. Nothing is placed. Use when the user says "how many shares", "size this
  trade", "how much should I buy", "I have Rs 50,000", "I only want to risk Rs 500 a
  trade", "use MIS leverage", "set my rules", "keep 10% in cash", or after /trader-in-
  exit writes a plan.
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
