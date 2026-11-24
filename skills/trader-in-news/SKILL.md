---
name: trader-in-news
description: >-
  News Monitor for Indian stocks. Tracks Yahoo headlines for .NS symbols plus NSE/BSE corporate announcements (results, board meetings, M&A, pledges, credit ratings) and how far each stock is from yesterday's close, newest first in India time.
---

# trader-in-news

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace SEC 8-K feed with NSE/BSE corporate announcements (respect site terms; no scraping behind logins).
- [x] Add Indian RSS sources (e.g. Moneycontrol, ET Markets, Business Standard) since Yahoo's .NS coverage is thin.
- [x] Re-map tags: results, board meeting, dividend/bonus/split, pledge, SAST, rating, ASM/GSM, F&O ban.
- [x] India time in output.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
