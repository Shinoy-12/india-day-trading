---
name: trader-in-alerts
description: >-
  Price Alerts for NSE/BSE stocks. Rings once when a price, stop, target or the 09:15 NSE open hits; turns a trade plan into stop / target / flat-by alerts; fetches free delayed Yahoo quotes (.NS / .BO).
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
