---
name: trader-in-risk
description: >-
  Risk Manager for Indian day trades. Blocks anything over your limits before it reaches the broker: stop required, loss at stop (incl. costs) within max loss, reward:risk, daily loss limit, trades per day, entry window, NSE closed, circuit limits, ASM/GSM stocks and non-EQ series. Getting out is never blocked.
---

# trader-in-risk

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace the NYSE clock block (`NYSE_HOLIDAYS`, `NYSE_EARLY_CLOSE`, `OPEN`/`CLOSE`, `trading_day`, `session`, `next_open`) with `from market_in import ...`.
- [x] New York time -> India time in messages, defaults and argument help.
- [x] Remove US-only checks (PDT, short-sale rules) and add: circuit-limit proximity, ASM/GSM list, series must be in `tradable_series` (EQ), F&O ban list if trading derivatives.
- [x] No new entries after a cutoff that leaves time before `SQUARE_OFF`.
- [x] Validate Kite-shaped orders instead of Alpaca JSON; prices on valid ticks.
- [x] Margin check uses `intraday_leverage.max_multiple`.
- [x] Block MIS entries for stocks where `mis_leverage()` is None (not on Zerodha's MIS list), and use that per-stock leverage, not a flat 5x.
- [x] Square-off cutoff via `square_off_time(fno_stock)`: 15:12 for F&O (CAS) stocks, 15:25 otherwise; Zerodha charges ₹50 + GST per auto square-off.
- [x] Circuit check: take `lower_circuit_limit`/`upper_circuit_limit` from a Kite quote.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
