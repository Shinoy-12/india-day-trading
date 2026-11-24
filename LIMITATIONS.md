# Known limitations, and what would fix them

A list to come back to once trading pays for better data. Ordered by how much a fix helps day trading, most first. Prices are as known in Nov 2026: check them before paying.

Free routes already tried and ruled out: NSE's website lookups (`www.nseindia.com/api/...`) and BSE's (`api.bseindia.com`) both answer "Access Denied" to programs. Getting past that would mean dodging their bot protection, which this repo doesn't do.

## 1. Intraday 5-minute bars depend on Yahoo
**Now:** the entry timer, scanner and time machine read Yahoo's free bars, which sometimes skip a bar for NSE stocks. The tools refuse to call anything on a day with a gap. The entry timer and time machine can patch a gap with Kite candles, but only when Claude is open (through the Kite MCP), and each patch costs a few hundred tokens. The scanner skips stocks with a gap. The `watch` loop polls Yahoo only. Yahoo and Kite prices can differ by a few paise.

**Fix (paid):** Kite Connect with historical data (about ₹500/month). The scripts would then fetch complete bars straight from Zerodha with no Claude needed: the watch loop would run on its own, the scanner would stop skipping stocks, and patching would cost no tokens.

**Work:** a Kite Connect fetcher in `shared/` (API key and daily login token kept in environment variables, never in files), used by `entry.py`, `scan.py` (orb) and `timemachine.py` in place of Yahoo.

## 2. Earnings numbers are Yahoo's copy, not the filing
**Now:** `trader-in-analyst` uses Yahoo Finance's compilation of each company's results. It can lag a fresh result by days or carry a copying error. The tool says so and links each new results PDF from NSE's announcements feed so you can check by hand.

**Fix (paid):** an Indian fundamentals data service that sells filed quarterly results through an API. Compare a few on price, coverage of NSE stocks and how fast new results appear.

**Fix (free, rough):** read the headline numbers out of the results PDFs NSE already links. PDF tables vary by company, so expect misreads. Use it only to cross-check Yahoo, not as the main source.

## 3. No live insider (SEBI PIT) trades
**Now:** NSE's insider RSS feed stopped on 2 May 2026; the tool warns about it. The live stand-in is NSE's 5%-holder feed (SAST Regulation 29), which only says company, who and when. Buy or sell, shares and % sit in PDFs inside a ZIP, so the tool shows a link instead. Small insider trades by directors (below the 5% rules) aren't covered at all. Bulk and block deals work fully.

**Fix (paid):** a data service that sells NSE corporate filings (insider/PIT and SAST disclosures) as structured data.

## 4. "Results filed" covers about one day
**Now:** the analyst's list of results filings comes from NSE's announcements feed, which holds only roughly the last day. It answers "did they just report?", not "show me every past result". Board-meeting dates (the "does it report this week?" question) work fine.

**Fix:** comes with the paid filings data in 2 or 3.

## 5. Not yet run through a live session
**Now:** the Kite patching, the missing-bar checks, the 5%-holder alerts and the leftover-GTT check (`ticket.py gtt-check`, tested on sample data in Kite's documented format, since no GTT was open) were tested on saved data from 23 Nov 2026 and the live feeds on 24 Nov 2026, not during market hours.

**Fix (free):** a paper run through one full NSE session: scanner in the morning, entry checks every 5 minutes, then the exit, time machine, budget and risk steps.

## 6. Smaller gaps
- Kite has no paper-trading account, so paper mode in `trader-in-broker` is a local simulation: fills are assumed, not real.
- SME-platform (NSE Emerge) companies aren't in NSE's main equity list, so their 5%-holder filings show no symbol. They can't be traded intraday on Zerodha MIS anyway.
- Zerodha's MIS and F&O stock lists come from Zerodha's public pages: run `shared/refresh_data.py` weekly or they go stale.
