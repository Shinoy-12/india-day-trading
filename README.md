# india-day-trader-skill

Claude Code skills for intraday trading on NSE/BSE, ported from
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) (US, MIT).

**Status:** all eleven skills work for NSE / Zerodha Kite, tested on NSE data (23 Nov 2026 replay and NSE's live files). Paper mode is a local simulation (Kite has no paper account). Still to do: a paper run through a live session before real money.

## Layout
```
shared/
  market_in.py        India clock, NSE ticks, costs, Yahoo/Kite symbols
  india_rules.json    hours, tick bands, charges, leverage (each block has a 'verified' date)
  nse_holidays.json   NSE trading holidays + special sessions (2026 filled from Zerodha)
  zerodha_mis_margins.json  stocks allowed for intraday MIS and their leverage
  nse_fno_stocks.json       F&O stocks (closing auction, continuous trading ends 15:15)
  refresh_data.py           re-downloads both Zerodha lists
skills/trader-in-*/   one folder per skill
tools/                the one-off porting scripts (reproducible port)
auto-paper/           unattended PAPER trading (see RUNBOOK.md) and the 60-day ORB filter backtest
install.sh            copies skills + shared files into ~/.claude/skills
```

## Before first use
1. Add each new year to `shared/nse_holidays.json` (zerodha.com/marketintel/holiday-calendar). The clock refuses
   any year that isn't listed.
2. Check every block in `shared/india_rules.json` against its `source` and set `verified`.
3. `python3 shared/market_in.py check` lists what's still unverified.

## Pipeline (same as the US version)
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker, with alerts alongside.
`trader-in-insider` replaces the US Congress (Pelosi) tracker: SEBI insider-trading disclosures and NSE bulk/block deals.

## Main differences from the US version
| Area | US | India |
|---|---|---|
| Hours | 09:30-16:00 ET | 09:15-15:30 IST (F&O stocks: 15:15, then closing auction); Zerodha square-off 15:25, F&O stocks 15:12 |
| Universe | Nasdaq Trader directories | NSE `EQUITY_L.csv`, EQ series |
| Quotes | Yahoo `TSLA` | Yahoo `RELIANCE.NS` / `.BO` |
| Ticks | $0.01 | price-band ticks |
| Filings | SEC EDGAR | NSE/BSE (SEBI LODR, PIT, SAST) |
| Broker | Alpaca (paper account) | Zerodha Kite MCP (no paper: local simulation) |
| Extra rules | PDT | circuit limits, ASM/GSM, STT and other charges |

Known limitations, and the paid or free fixes for each: [LIMITATIONS.md](LIMITATIONS.md).

Not investment advice. Trading tools here never place an order without your explicit yes.
