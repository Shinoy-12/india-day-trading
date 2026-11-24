#!/usr/bin/env python3
"""Refresh the Zerodha-sourced lists the trader-in-* skills read. Standard library only.

    python3 refresh_data.py            # both lists
    python3 refresh_data.py mis        # stocks allowed for MIS (intraday) + leverage
    python3 refresh_data.py fno        # stocks with F&O contracts (closing-auction stocks)

Both come from Zerodha's public margin-calculator pages. Run it every week or so.
"""

import datetime
import html
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
MIS_URL = "https://zerodha.com/margin-calculator/Equity/"
FNO_URL = "https://zerodha.com/margin-calculator/Futures/"
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def cells(page):
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        c = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", x)).split())
             for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if c:
            yield c


def updated(page):
    m = re.search(r"Last updated:\s*([^<]+)", page)
    return m.group(1).strip() if m else None


def write(name, doc):
    path = os.path.join(HERE, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    return path


def refresh_mis():
    page = get(MIS_URL)
    stocks = {c[0]: {"mis_margin_pct": c[1].rstrip("%"), "leverage": c[2].rstrip("x")}
              for c in cells(page) if len(c) >= 3 and c[2].endswith("x")}
    if len(stocks) < 500:
        raise SystemExit("MIS page parsed to only %d stocks; page layout may have changed" % len(stocks))
    write("zerodha_mis_margins.json", {
        "_source": MIS_URL, "_last_updated": updated(page),
        "_note": "Stocks allowed for MIS (intraday) at Zerodha and their leverage. A stock not "
                 "listed here cannot be traded MIS. Refresh with refresh_data.py.",
        "stocks": stocks})
    return "MIS list: %d stocks" % len(stocks)


def refresh_fno():
    page = get(FNO_URL)
    syms = sorted({c[0].split()[0] for c in cells(page) if c[0] and re.match(r"^[A-Z0-9&-]+ ", c[0])} - INDICES)
    if len(syms) < 100:
        raise SystemExit("Futures page parsed to only %d symbols; page layout may have changed" % len(syms))
    write("nse_fno_stocks.json", {
        "_source": FNO_URL, "_fetched": datetime.date.today().isoformat(),
        "_note": "NSE stocks with futures contracts. Since 2026-08-03 these are in SEBI's Closing "
                 "Auction Session: continuous trading ends 15:15, Zerodha squares off MIS at 15:12.",
        "stocks": syms})
    return "F&O list: %d stocks" % len(syms)


def main(argv):
    which = argv[1:] or ["mis", "fno"]
    jobs = {"mis": refresh_mis, "fno": refresh_fno}
    for w in which:
        if w not in jobs:
            raise SystemExit("unknown list %r (mis or fno)" % w)
        print(jobs[w]())


if __name__ == "__main__":
    main(sys.argv)
