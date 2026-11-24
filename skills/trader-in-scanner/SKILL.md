---
name: trader-in-scanner
description: >-
  Chart Scanner for NSE. Builds the day-tradable universe (NSE EQ series stocks that
  Zerodha allows for MIS intraday, about 1,500, F&O stocks marked), runs a pre-market
  scan of daily closes (20-day closing-high breakout, bull flag, reclaimed the 20-day
  average, oversold, oversold bounce) and an intraday opening-range breakout scan on
  5-minute bars from 09:15 IST, then writes trader/watchlist.json for trader-in-news and
  trader-in-entry. Daily data from NSE's official bhavcopy, intraday from free Yahoo
  5-minute bars (.NS symbols); NSE holidays respected. Use when the user says "scan the
  market", "scan NSE", "find me setups", "what is breaking out", "opening range
  breakouts", "bull flags", "oversold stocks", "pre-market scan", "build my watchlist",
  or "what should I look at today".
---

# trader-in-scanner

**Status: ported to NSE (2026-11-24).** Run from the folder that should hold `trader/`.

## Commands
```bash
python3 scan.py universe                       # once a week: trader/universe.txt
python3 scan.py daily                          # before 09:15 IST: daily setups (NSE bhavcopy)
python3 scan.py daily --source yahoo           # fallback if NSE's files are unavailable
python3 scan.py daily --symbols RELIANCE,SBIN,M&M
python3 scan.py orb                            # after 09:35 IST: opening-range breakouts
python3 scan.py orb --now "2026-11-23 10:30"   # replay a recent session (Yahoo keeps ~5 days of 5m bars)
```
Refresh Zerodha's lists first if they are more than a week old: `python3 refresh_data.py`.

## How it works
- **Universe:** NSE `EQUITY_L.csv`, series `EQ` only (BE/BZ are trade-to-trade), kept only if on
  Zerodha's MIS list (`zerodha_mis_margins.json`). ETFs are not in EQUITY_L. F&O stocks are marked `|FNO`.
- **Clock:** `market_in.py`: 09:15–15:30 IST, NSE holidays. A year missing from `nse_holidays.json` stops the scan.
- **F&O stocks:** continuous trading ends at 15:15 (closing auction); their bars stop there and hits say so.
- **Daily data:** NSE bhavcopy, one zip per trading day for every stock. The last 45 trading days are
  cached in `trader/bhavcopy/`, so after the first run (about 45 files, ~30 s) each run fetches one new file.
  Weekends are tried once, because Muhurat trading falls on them; a 404 is remembered.
- **Splits and bonuses:** closes are back-adjusted with NSE's adjusted previous close, but only when the
  stock traded in EQ the day before. After a gap (suspension, or trading in another series) a price
  mismatch restarts that stock's history instead of guessing a factor.
- **Floors:** ₹50 minimum price; daily also needs 100,000 shares traded. Change with `--min-price` / `--min-volume`.
- **ORB:** stage 1 (Yahoo spark) only needs the opening range plus one bar, because Yahoo's NSE spark data
  drops bars even for liquid stocks; stage 2 (v8 chart) needs every bar from 09:15 to the cutoff.
- **Entry cutoff:** no ORB hits after 15:00 by default (`--until` or `no_entries_after` in trader/config.json).

## Known limits
- Bhavcopy for a session appears in the evening after the close; before that, the scan uses the previous session.
- If NSE changes the bhavcopy columns, the scan stops with a message; use `--source yahoo` until it is updated.
- Intraday (orb) still uses Yahoo, which drops some 5-minute bars; Kite Connect would be the reliable upgrade.
- Yahoo's intraday data is free, delayed and unofficial. A scan is a list of charts, not a list of stocks to buy.
