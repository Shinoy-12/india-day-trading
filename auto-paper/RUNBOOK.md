# Auto-paper runbook (unattended paper trading)

Standing instruction from the user, 2026-11-24: "option 1": run the pipeline unattended
in PAPER mode and record trades that PASS /trader-in-risk as simulated fills.
This authorization covers PAPER ONLY.

Work from the folder that holds trader/.
Setup: copy auto_paper.py and sectors.py into that trader/ folder, and orb_filters.py into a folder next to it
(for example backtest/). Run `python3 trader/auto_paper.py tick` from the working folder. Skills live in ~/.claude/skills/trader-in-*.
Today's report: trader/reports/<YYYY-MM-DD>.md (append; create if missing). Times are IST.

## Hard rules (check first, every run)
1. Read trader/config.json. If "paper" is not true, or "allow_margin"/"allow_short"/"allow_options"
   is true: STOP. Write "Stopped: config is not paper-only" to the report. Place nothing.
2. Never call any Kite orders or gtt tool that changes anything. Paper fills are recorded with
   ticket.py only.
3. If NSE is closed today (holiday/weekend; use market_in.py / nse_holidays.json): write one line, stop.
4. Never take a trade that /trader-in-risk did not PASS. Never loosen config limits.

## Morning step (09:10)
- `/trader-in-news` on the watchlist (trader/watchlist.json, top 30 by turnover). Note anything tagged
  earnings, risk, surveillance, regulatory in the report as "avoid today".

## Intraday step (every 15 minutes, 09:35 to 15:00)
A. Manage open paper positions first (ticket.py / trader/portfolio.json):
   for each, fetch 5-minute Yahoo bars since entry. If a bar's low <= stop, record a sell fill
   at the stop; else if high >= target, record a sell fill at the target
   (`python3 ~/.claude/skills/trader-in-broker/ticket.py fill --symbol S --side sell --qty Q --price P`).
   If both in the same bar, assume the stop (conservative). Write each exit to the report.
B. If the time is 09:35–15:00, trades today < max_trades_per_day, and today's realized loss is under
   max_daily_loss_inr: run `/trader-in-scanner orb`. Skip "avoid today" names and any symbol already
   traded today. For the best hit (most traded), run in order:
   /trader-in-entry → /trader-in-exit → /trader-in-timemachine → /trader-in-budget → /trader-in-risk.
   - If the time machine verdict is negative expectancy after charges, skip it and note why.
   - If risk says BLOCK, note the reason and stop this step.
   - If PASS: `ticket.py approve --index N --reply "AUTO-PAPER: standing instruction 2026-11-24 'option 1' (paper only)"`,
     then record a buy fill at the entry price, then `ticket.py result` as placed. Write the trade
     (symbol, qty, entry, stop, target, R, risk verdict) to the report.
   At most one new entry per run.

## Close step (15:05)
- Close every open paper position: `ticket.py flatten`, then record a sell fill at the latest price.
- Write the day summary to the report: each trade with P&L after charges, total, what was skipped and
  why, and anything that broke (missing bars, script errors, odd data). End with `ticket.py log` output.

## Implementation (2026-11-25)
The steps above are implemented in trader/auto_paper.py (`tick` every 15 min, `close` at 15:05).
It scans only the ~50 most-traded stocks, skips breakouts older than 20 min, and keeps one paper trade open at a time.
Scheduled tasks just run that script.

## Filters (2026-11-25)
See FILTERS in trader/auto_paper.py and backtest-2026-11/orb_filters.py. On: realistic fill, sector trend
(sector index above its range mid today and above its 20-day average; sectors via trader/sectors.py).
Off, because they tested worse: Nifty filter, volume filter, stricter time-machine threshold.
