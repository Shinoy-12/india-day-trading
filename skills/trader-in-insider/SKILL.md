---
name: trader-in-insider
description: >-
  The Insider Tracker (Indian stand-in for the US Pelosi tracker; India has no STOCK
  Act). Watches the trades Indian rules make public: SEBI insider-trading (PIT)
  disclosures by directors, promoters and key managers, read from NSE's XBRL filings,
  and NSE's daily bulk and block deals (big investors). Alerts once per new filing and
  turns each into clean rows (who, category, stock, buy or sell, quantity, rupee value,
  average price, mode such as market, ESOP or pledge, holding before and after, trading
  days it took to disclose). Flags trades in stocks you hold. Use when the user says
  "insider trading", "are promoters buying", "who is buying X", "bulk deals", "block
  deals", "big investor trades", "did any director sell", "alert me on insider filings",
  or "run the insider skill".
argument-hint: "[symbol or name] [--holdings]"
---

# trader-in-insider

Indian company insiders (directors, promoters, key managerial people and their
relatives) must disclose trades over Rs 10 lakh: to the company within 2
trading days, and the company to the exchange within 2 more (SEBI PIT
Regulation 7(2)). Big investors show up in NSE's bulk deals (over 0.5% of a
company's shares in a day) and block deals (Rs 10 crore or more in the block
window), published each evening. This skill reads those public files, notices
what is new, and lays each one out.

It is fast. It is not early. An insider trade is public days after it
happens, a bulk or block deal the evening after. There is no inside
information here: only public filings, read quickly. Say that every time.

**Status:** built for NSE (2026-11-24), tested on NSE's live files. NSE's
insider RSS feed's newest filing was 2 May 2026 when this was built; the tool
warns when the feed is stale and points to NSE's insider-trading page. NSE's
insider lookup and BSE's both block programs, so there is no live insider
source. The live stand-in is NSE's 5%-holder feed (SEBI takeover code,
Regulation 29: anyone reaching 5% of a company, or moving 2% or more above it,
promoters included): `insider.py holders`, also part of `insider.py new`. It
gives company, who and when only; the buy or sell, shares and % are in the
filing's PDFs (link shown). Say so when you show these rows.

Tool in this folder (standard library Python):

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py" --help
```

## What it reads and writes

- Reads `https://nsearchives.nseindia.com/content/RSS/Insider_Trading.xml` and
  each disclosure's XBRL (`.../corporate/xbrl/IT_..._WEB.xml`), plus
  `.../content/equities/bulk.csv` and `block.csv`, and the 5%-holder feed
  `.../content/RSS/Sast_Regulation29.xml` (symbols from NSE's `EQUITY_L.csv`,
  cached a day in `trader/cache/`; SME-platform companies show no symbol).
- Writes `trader/state/insider.json` (what was shown, so each item alerts once)
  and keeps the XBRL files in `trader/state/insider-xbrl/`.
- Reads `trader/portfolio.json` and `trader/plan.json` to flag trades in what
  you hold or plan.

## The rules

- **Quote the filing.** Every insider row comes from its NSE XBRL file, with
  the link. A bulk or block row names NSE's file and date.
- **Mode matters.** An ESOP allotment, a pledge, a gift or an inter-se
  promoter transfer is not a market buy. Say the mode; `--market-only` hides
  the rest.
- **Say the delay.** Each insider row shows the trading days from the trade to
  the company being told; over 2 is flagged LATE.
- **Pairs are pairs.** A promoter-group sale matched by a promoter buy of the
  same shares on the same day is a transfer inside the group, not a vote of
  confidence either way.
- **Bulk and block deals are not insiders.** They are big clients (funds,
  traders); one name can buy and sell the same day.

## Steps

1. What is new: `insider.py new` (add `--holdings` for what you hold, `--limit 20`
   to read only the newest insider filings). Exit 0 when something is new.
2. A stock: `insider.py insider --symbol BAJAJFINSV` and `insider.py deals --symbol LENSKART`.
3. A name: `insider.py deals --name "GOLDMAN"`, `insider.py insider --name "Lath"`.
4. One filing: `insider.py read <XBRL link>`.
5. Big holders (live): `insider.py holders` (add `--holdings` or `--symbol`).
5. To watch through the day, run `new` on a schedule (a scheduled task or
   /loop); it alerts once per item.

Report rows as the tool prints them, with the delay, the mode and the link,
and end with: public filings, fast not early, not advice.
