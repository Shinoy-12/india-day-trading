---
name: trader-in-analyst
description: >-
  The Earnings Analyst for Indian listed companies. Lays out what changed in a company's
  reported quarters: revenue, gross, operating and net margins, net profit and diluted
  EPS, quarter by quarter in Rs crore with Indian fiscal-year labels (Q2 FY27), each
  against the same quarter a year earlier, with the trailing twelve months. Numbers come
  from Yahoo Finance's compilation of the filed results (unofficial; it says so and
  links NSE's results page), plus the company's latest results and board-meeting filings
  in NSE's feeds. Reads an earnings call transcript when you paste one. Use when the
  user says "how did TCS's results look", "analyze the earnings", "what changed this
  quarter", "is revenue growing", "compare margins", "sum up the call", "does it report
  this week", or before trading a stock around its results.
---

# trader-in-analyst

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace SEC EDGAR (`data.sec.gov` companyfacts / submissions, CIK lookup) with BSE or NSE financial-results filings (XBRL). Map by ISIN or BSE scrip code instead of CIK.
- [x] Map Ind AS line items (Revenue from operations, Profit after tax, Basic/Diluted EPS) in place of US-GAAP tags.
- [x] Indian quarters: results within 45 days of quarter end (60 for Q4/annual); fiscal year ends 31 March.
- [x] Respect the exchange sites' terms of use and rate limits; prefer official downloads.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
