---
name: trader-in-alerts
description: >-
  Price Alerts for NSE stocks. Rings when a price, a stop, a target or the opening bell
  hits. Turns the trade plan into three alerts in one go (the stop, the target and
  flat-by before Zerodha's MIS square-off, 15:25 or 15:12 for F&O stocks), plus above /
  below / stop / target levels, percent moves from the previous close, any time of day,
  and the 09:15 NSE opening bell, each ringing once. Knows NSE hours and holidays in
  India time, fetches free delayed Yahoo quotes (.NS) or reads a saved Kite quote
  (official prices plus circuit limits), and writes trader/prices.json for sizing and
  the risk check. Use when the user says "alert me when", "tell me if RELIANCE hits",
  "watch my stop", "watch my trade", "remind me to close by 3:05", "is the market open",
  "when does NSE open", "get me a price", or right after /trader-in-exit writes a plan.
---

# trader-in-alerts

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] Yahoo symbols via `yahoo_symbol()` (`RELIANCE` -> `RELIANCE.NS`).
- [x] Drop the Stooq fallback (no useful Indian coverage).
- [x] "Opening bell" alert = 09:15 IST; flat-by default from `FLAT_BY`, never after `SQUARE_OFF`.
- [x] $ -> ₹ via `rupees()`.
- [x] F&O stocks: alerts and GTTs only trigger until 15:15 at Zerodha.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
