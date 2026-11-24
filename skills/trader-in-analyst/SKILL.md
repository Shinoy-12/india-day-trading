---
name: trader-in-analyst
description: >-
  Earnings Analyst for Indian listed companies. Reads quarterly results filed under SEBI LODR Reg. 33 (NSE/BSE XBRL) and sums up revenue, margins, net profit and EPS against the same quarter a year earlier.
---

# trader-in-analyst

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace SEC EDGAR (`data.sec.gov` companyfacts / submissions, CIK lookup) with BSE or NSE financial-results filings (XBRL). Map by ISIN or BSE scrip code instead of CIK.
- [x] Map Ind AS line items (Revenue from operations, Profit after tax, Basic/Diluted EPS) in place of US-GAAP tags.
- [x] Indian quarters: results within 45 days of quarter end (60 for Q4/annual); fiscal year ends 31 March.
- [x] Respect the exchange sites' terms of use and rate limits; prefer official downloads.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
