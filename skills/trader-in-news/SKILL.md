---
name: trader-in-news
description: >-
  News Monitor for NSE stocks. Tracks news on every stock you watch and flags what moves
  it: Yahoo Finance headlines per ticker (.NS), the company's filings in NSE's public
  feeds (announcements, financial results, board meetings, corporate actions) and how
  far each stock is from yesterday's close. Shows only what is new since the last check,
  newest first, in India time, tags each item (earnings, analyst, deal, capital, people,
  risk, surveillance, regulatory, macro) and never repeats one. Use when the user says
  "any news on TCS", "why is this moving", "what's the news on my watchlist", "morning
  briefing", "pre-market news", "monitor the news", "did anything break", "check the NSE
  filings", or after /trader-in-scanner finds setups.
---

# trader-in-news

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace SEC 8-K feed with NSE/BSE corporate announcements (respect site terms; no scraping behind logins).
- [x] Add Indian RSS sources (e.g. Moneycontrol, ET Markets, Business Standard) since Yahoo's .NS coverage is thin.
- [x] Re-map tags: results, board meeting, dividend/bonus/split, pledge, SAST, rating, ASM/GSM, F&O ban.
- [x] India time in output.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
