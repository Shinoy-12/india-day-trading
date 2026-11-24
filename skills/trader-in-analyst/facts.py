#!/usr/bin/env python3
"""Earnings reader for trader-in-analyst (NSE). Standard library only.
Ported from day-trader-skill's US earnings analyst (MIT).

Lays out what changed in an Indian company's reported quarters: revenue,
gross, operating and net margins, net profit, diluted EPS, and growth against
the same quarter a year earlier, plus the last four quarters (TTM). It also
lists the company's latest NSE filings about results: financial results filed,
and board meetings announced (the "does it report this week" question).

    python3 facts.py TCS
    python3 facts.py TCS INFY --quarters 8
    python3 facts.py TCS --json
    python3 facts.py RELIANCE HDFCBANK TCS --metrics trader/metrics.json

Sources:
  Quarterly numbers: Yahoo Finance's fundamentals timeseries for <SYMBOL>.NS
    https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/TCS.NS
    (quarterlyTotalRevenue, quarterlyCostOfRevenue, quarterlyGrossProfit,
    quarterlyOperatingIncome, quarterlyNetIncome, quarterlyDilutedEPS).
    These are Yahoo's compilation of the results the company filed under SEBI
    LODR Regulation 33 (usually consolidated), not the filing itself: free and
    unofficial, and they can lag a fresh result by days. For a decision, check
    the result on nseindia.com (the link below) or the company's own release.
    NSE's and BSE's own results APIs need a browser session, so this tool does
    not call them.
  Filings: NSE's public RSS feeds of financial results and board meetings,
    matched to the company by the symbol in the document link or its name in
    NSE's equity list (EQUITY_L.csv, cached in trader/cache/ for a day). The
    feeds roll: they hold the latest filings only.

Indian conventions: amounts in Rs crore (1 crore = 10 million); quarters are
labelled by Indian fiscal year, which ends on 31 March (the quarter ending
30 September 2026 is Q2 FY27). Indian companies publish the fourth quarter as
its own quarter, so nothing is derived. Banks and NBFCs report revenue
differently; their margins can be blank or not comparable.

--metrics FILE merges one row per ticker into a JSON file (TTM revenue and EPS,
margins, growth). Offline: --offline DIR reads timeseries-<SYMBOL>.json,
nse-results.xml, nse-board.xml and EQUITY_L.csv from DIR.

Numbers only: this tool never says whether a stock is a buy.
"""

import argparse
import csv
import datetime as _dt
import email.utils
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402

UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
TS_URL = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
          "?type=%s&period1=%d&period2=%d")
TYPES = {"revenue": "quarterlyTotalRevenue", "cost_of_revenue": "quarterlyCostOfRevenue",
         "gross_profit": "quarterlyGrossProfit", "operating_income": "quarterlyOperatingIncome",
         "net_income": "quarterlyNetIncome", "eps_diluted": "quarterlyDilutedEPS"}
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/%s.xml"
NSE_FEEDS = {"results": "Financial_Results", "board": "Board_Meetings"}
NSE_RESULTS_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_L_CACHE = "trader/cache/EQUITY_L.csv"
CRORE = 1e7
IST = _dt.timedelta(hours=5, minutes=30)


class FactsError(Exception):
    pass


class Fetcher(object):
    def __init__(self, offline=None, pause=0.3):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raise FactsError("HTTP %s for %s" % (exc.code, url.split("?")[0]))
        except urllib.error.URLError as exc:
            raise FactsError("could not reach %s: %s" % (url.split("/")[2], exc.reason))

    def json(self, url, name):
        try:
            return json.loads(self.get(url, name).decode("utf-8"))
        except ValueError:
            raise FactsError("%s is not JSON" % name)


# ---------------------------------------------------------------- the quarters

def _date(s):
    return _dt.date.fromisoformat(str(s)[:10])


def fiscal_label(end):
    """Indian fiscal year ends 31 March: 2026-09-30 -> 'Q2 FY27'."""
    d = _date(end)
    fy = d.year + 1 if d.month > 3 else d.year
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(d.month)
    return ("Q%d FY%02d" % (q, fy % 100)) if q else "FY%02d" % (fy % 100)


def timeseries(fetcher, sym, years=4):
    """{metric: {end: value}} from Yahoo's fundamentals timeseries."""
    now = int(time.time())
    url = TS_URL % (urllib.parse.quote(market_in.yahoo_symbol(sym), safe=""), ",".join(TYPES.values()),
                    now - years * 366 * 86400, now)
    doc = fetcher.json(url, "timeseries-%s.json" % sym)
    out = {k: {} for k in TYPES}
    for res in ((doc.get("timeseries") or {}).get("result") or []):
        typ = ((res.get("meta") or {}).get("type") or [None])[0]
        key = next((k for k, v in TYPES.items() if v == typ), None)
        if not key:
            continue
        for x in res.get(typ) or []:
            if x and x.get("asOfDate") and (x.get("reportedValue") or {}).get("raw") is not None:
                out[key][x["asOfDate"]] = float(x["reportedValue"]["raw"])
    if not out["revenue"] and not out["net_income"]:
        raise FactsError("no quarterly revenue or net profit for %s.NS at Yahoo (an ETF, a new "
                         "listing, or the symbol is different there)" % sym)
    return out


def _yoy_match(series_, end, days=365, slack=10):
    target = _date(end) - _dt.timedelta(days=days)
    best = None
    for e in series_:
        gap = abs((_date(e) - target).days)
        if gap <= slack and (best is None or gap < best[0]):
            best = (gap, e)
    return series_[best[1]] if best else None


def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round(100.0 * (a - b) / abs(b), 1)


def margin(part, whole):
    if part is None or not whole:
        return None
    return round(100.0 * part / whole, 1)


def analyse(s, quarters=6, name=None):
    """Every number in the report, as a dict. s = {metric: {end: value}}."""
    rev = s["revenue"]
    ends = sorted(set(rev) | set(s["net_income"]), reverse=True)[:quarters]
    rows = []
    for end in ends:
        r = rev.get(end)
        gp = s["gross_profit"].get(end)
        if gp is None and r is not None and end in s["cost_of_revenue"]:
            gp = r - s["cost_of_revenue"][end]
        oi = s["operating_income"].get(end)
        ni = s["net_income"].get(end)
        eps = s["eps_diluted"].get(end)
        prior = {k: _yoy_match(s[k], end) for k in ("revenue", "net_income", "eps_diluted")}
        rows.append({
            "end": end, "fiscal": fiscal_label(end), "derived": False,
            "revenue": r, "gross_profit": gp, "operating_income": oi, "net_income": ni,
            "eps_diluted": round(eps, 2) if eps is not None else None,
            "gross_margin": margin(gp, r), "operating_margin": margin(oi, r), "net_margin": margin(ni, r),
            "revenue_yoy": pct(r, prior["revenue"]), "net_income_yoy": pct(ni, prior["net_income"]),
            "eps_yoy": pct(eps, prior["eps_diluted"]),
        })
    ttm = {}
    for key in ("revenue", "net_income", "eps_diluted"):
        last4 = sorted(s[key])[-4:]
        if len(last4) == 4 and (_date(last4[-1]) - _date(last4[0])).days < 300:
            ttm[key] = sum(s[key][e] for e in last4)
    if "eps_diluted" in ttm:
        ttm["eps_diluted"] = round(ttm["eps_diluted"], 2)
    return {"entity": name, "rows": rows, "ttm": ttm}


def cr(v):
    """Rs crore, for sentences."""
    return "n/a" if v is None else "₹{:,.0f} cr".format(v / CRORE)


def changes(result):
    """Plain sentences: what changed in the latest quarter."""
    rows = result["rows"]
    if not rows:
        return []
    cur = rows[0]
    prev = rows[1] if len(rows) > 1 else None
    out = []
    line = "%s (quarter ending %s): revenue %s" % (cur["fiscal"], cur["end"], cr(cur["revenue"]))
    if cur["revenue_yoy"] is not None:
        line += " (%+.1f%% vs a year earlier)" % cur["revenue_yoy"]
    line += ", net profit %s" % cr(cur["net_income"])
    if cur["net_income_yoy"] is not None:
        line += " (%+.1f%%)" % cur["net_income_yoy"]
    if cur["eps_diluted"] is not None:
        line += ", diluted EPS ₹%.2f" % cur["eps_diluted"]
        if cur["eps_yoy"] is not None:
            line += " (%+.1f%%)" % cur["eps_yoy"]
    out.append(line + ".")
    for key, name in (("gross_margin", "Gross margin"), ("operating_margin", "Operating margin"),
                      ("net_margin", "Net margin")):
        if cur[key] is None:
            continue
        s = "%s %.1f%%" % (name, cur[key])
        if prev and prev[key] is not None:
            s += " (%+.1f points vs the quarter before)" % (cur[key] - prev[key])
        out.append(s + ".")
    if cur["net_income"] is not None and cur["operating_income"] is not None \
            and cur["net_income"] > cur["operating_income"]:
        out.append("Net profit is above operating profit: it includes other income or one-offs "
                   "(investments, tax items, exceptional gains). Check the filed result before reading it "
                   "as growth.")
    if prev and cur["revenue"] is not None and prev["revenue"]:
        out.append("Revenue %+.1f%% vs the quarter before (many businesses are seasonal: "
                   "compare with a year earlier first)." % pct(cur["revenue"], prev["revenue"]))
    return out


# ---------------------------------------------------------------- NSE filings

def _norm_name(name):
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp|inc)\b", " ", n)
    return " ".join(n.split())


def nse_names(fetcher, cache=EQUITY_L_CACHE):
    """{SYMBOL: company name} from NSE's EQUITY_L.csv, cached for a day."""
    text = None
    if not fetcher.offline and cache and os.path.isfile(cache) and time.time() - os.path.getmtime(cache) < 86400:
        with open(cache, encoding="utf-8") as fh:
            text = fh.read()
    if text is None:
        text = fetcher.get(EQUITY_L_URL, "EQUITY_L.csv").decode("utf-8", "replace")
        if cache and not fetcher.offline:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as fh:
                fh.write(text)
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    hdr = [h.strip() for h in rows[0]] if rows else []
    if "SYMBOL" not in hdr:
        raise FactsError("NSE's equity list has an unexpected format")
    si, ni = hdr.index("SYMBOL"), hdr.index("NAME OF COMPANY")
    return {r[si].strip(): r[ni].strip() for r in rows[1:] if len(r) > max(si, ni)}


def _pub(value):
    """NSE RSS pubDate "24-Nov-2026 00:28:46" (IST) -> "2026-11-24 00:28 IST"."""
    v = (value or "").strip()
    try:
        return _dt.datetime.strptime(v, "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M IST")
    except ValueError:
        try:
            d = email.utils.parsedate_to_datetime(v)
            return (d.astimezone(_dt.timezone.utc).replace(tzinfo=None) + IST).strftime("%Y-%m-%d %H:%M IST")
        except (TypeError, ValueError, IndexError):
            return v


def nse_filings(fetcher, sym, company):
    """{"results": [...], "board": [...]}: the company's items in NSE's rolling feeds."""
    want = _norm_name(company)
    out = {}
    for key, feed in NSE_FEEDS.items():
        out[key] = []
        root = ET.fromstring(fetcher.get(NSE_RSS % feed, "nse-%s.xml" % key))
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            m = re.search(r"/corporate/([A-Z0-9&\-]+?)_\d", link)
            if (m and m.group(1) == sym) or (want and _norm_name(title) == want):
                out[key].append({"title": title, "detail": " ".join((it.findtext("description") or "").split()),
                                 "date": _pub(it.findtext("pubDate")), "link": link})
    return out


# ---------------------------------------------------------------- output

def _c(v):
    return "-" if v is None else "{:,.0f}".format(v / CRORE)


def _p(v):
    return "-" if v is None else "%+.1f%%" % v if v < 0 or v > 0 else "0.0%"


def _pm(v):
    return "-" if v is None else "%.1f%%" % v


def render(ticker, result, filings):
    out = ["%s (NSE: %s). Rs crore except EPS. Source: Yahoo Finance fundamentals (unofficial; verify "
           "against the filed result)." % (result["entity"] or ticker, ticker), ""]
    out.append("%-11s %-8s %10s %8s %7s %7s %7s %10s %8s %7s" % (
        "quarter end", "fiscal", "revenue", "rev yoy", "gross", "oper", "net", "net prof", "EPS dil", "EPS yoy"))
    for r in result["rows"]:
        out.append("%-11s %-8s %10s %8s %7s %7s %7s %10s %8s %7s" % (
            r["end"], r["fiscal"], _c(r["revenue"]), _p(r["revenue_yoy"]), _pm(r["gross_margin"]),
            _pm(r["operating_margin"]), _pm(r["net_margin"]), _c(r["net_income"]),
            "-" if r["eps_diluted"] is None else "%.2f" % r["eps_diluted"], _p(r["eps_yoy"])))
    t = result["ttm"]
    if t:
        out.append("")
        out.append("Last 4 quarters: revenue %s, net profit %s, diluted EPS %s." % (
            cr(t.get("revenue")), cr(t.get("net_income")),
            "₹%.2f" % t["eps_diluted"] if t.get("eps_diluted") is not None else "-"))
    out.append("")
    out.append("What changed:")
    for line in changes(result):
        out.append("  - " + line)
    if filings is not None:
        out.append("")
        res, board = filings.get("results") or [], filings.get("board") or []
        for f in res[:3]:
            out.append("NSE financial result filed %s: %s" % (f["date"], f["detail"][:200]))
        for f in board[:3]:
            out.append("NSE board meeting notice %s: %s  %s" % (f["date"], f["detail"][:200], f["link"]))
        if not res and not board:
            out.append("No result or board-meeting filing for %s in NSE's latest feeds (they roll: only the "
                       "newest filings are there)." % ticker)
        out.append("All filed results: %s (search %s)." % (NSE_RESULTS_PAGE, ticker))
    if result["rows"]:
        age = (_dt.date.today() - _date(result["rows"][0]["end"])).days
        if age > 140:
            out.append("")
            out.append("NOTE: the latest quarter here ended %s, %d days ago: a newer result may be filed "
                       "but not yet at Yahoo. Check NSE." % (result["rows"][0]["end"], age))
    return "\n".join(out) + "\n"


def metrics_row(ticker, result):
    rows = result["rows"]
    cur = rows[0] if rows else {}
    t = result["ttm"]
    return {"ticker": ticker, "name": result["entity"], "exchange": "NSE",
            "period_end": cur.get("end"), "fiscal": cur.get("fiscal"), "revenue_ttm": t.get("revenue"),
            "net_income_ttm": t.get("net_income"), "eps_ttm": t.get("eps_diluted"),
            "revenue_growth_yoy": cur.get("revenue_yoy"), "eps_growth_yoy": cur.get("eps_yoy"),
            "net_income_growth_yoy": cur.get("net_income_yoy"),
            "gross_margin": cur.get("gross_margin"), "operating_margin": cur.get("operating_margin"),
            "net_margin": cur.get("net_margin"), "currency": "INR",
            "source": "Yahoo Finance fundamentals timeseries (unofficial)"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tickers", nargs="+", help="NSE symbols, e.g. TCS INFY")
    ap.add_argument("--quarters", type=int, default=6)
    ap.add_argument("--no-filings", action="store_true", help="skip the NSE results and board-meeting feeds")
    ap.add_argument("--metrics", metavar="FILE", help="merge a row per ticker into this JSON")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    fetcher = Fetcher(offline=args.offline)
    names = {}
    try:
        names = nse_names(fetcher)
    except FactsError as exc:
        print("facts: NSE equity list unavailable (%s); company names and filing matches by name are off"
              % exc, file=sys.stderr)
    results, rows, failed = [], [], 0
    for t in args.tickers:
        tick = market_in.kite_symbol(t)[1]
        try:
            result = analyse(timeseries(fetcher, tick), quarters=args.quarters, name=names.get(tick))
            filings = None
            if not args.no_filings:
                try:
                    filings = nse_filings(fetcher, tick, names.get(tick))
                except (FactsError, ET.ParseError) as exc:
                    print("facts: %s: NSE feeds: %s" % (tick, exc), file=sys.stderr)
        except FactsError as exc:
            print("facts: %s: %s" % (tick, exc), file=sys.stderr)
            failed += 1
            continue
        results.append({"ticker": tick, "result": result, "filings": filings, "changes": changes(result)})
        rows.append(metrics_row(tick, result))
        if not args.json:
            sys.stdout.write(render(tick, result, filings))
            sys.stdout.write("\n")
    if args.json:
        print(json.dumps(results, indent=2))
    if args.metrics and rows:
        existing = {}
        if os.path.isfile(args.metrics):
            with open(args.metrics, encoding="utf-8") as fh:
                existing = {r["ticker"]: r for r in json.load(fh).get("companies", [])}
        for r in rows:
            existing[r["ticker"]] = r
        folder = os.path.dirname(args.metrics)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.metrics, "w", encoding="utf-8") as fh:
            json.dump({"as_of": _dt.date.today().isoformat(),
                       "companies": sorted(existing.values(), key=lambda r: r["ticker"])}, fh, indent=2)
            fh.write("\n")
        if not args.json:
            print("wrote %s (%d companies)" % (args.metrics, len(existing)))
    if not args.json:
        print("Numbers only, not advice: never a buy or sell call.")
    return 0 if results and not failed else (1 if results else 2)


if __name__ == "__main__":
    sys.exit(main())
