#!/usr/bin/env python3
"""News monitor for trader-in-news (NSE). Standard library only.
Ported from day-trader-skill's US news monitor (MIT).

Watches headlines and NSE corporate filings for the stocks you watch or hold
and prints only what is new since the last check, newest first, with how far
each stock has moved today and a flag on anything that touches your tickers.

    python3 news.py                                  # watchlist + plan + portfolio tickers
    python3 news.py --tickers TCS INFY RELIANCE
    python3 news.py --tickers TCS --all --hours 72   # everything in the last 3 days, seen or not
    python3 news.py --no-nse                         # headlines only
    python3 news.py --no-moves                       # skip the price line per ticker

Your tickers, when --tickers is not given: every hit in trader/watchlist.json
(trader-in-scanner), the symbol in trader/plan.json (trader-in-exit) and the
positions in trader/portfolio.json.

Sources:
  - Yahoo Finance headline RSS, one request per ticker:
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<TICKER>.NS&region=IN&lang=en-IN
  - NSE corporate filings, NSE's public RSS feeds (one request per feed for
    the whole market, filtered to your tickers): announcements, financial
    results, board meetings and corporate actions (dividends, splits, bonus):
    https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml
    These feeds roll: they hold the latest filings only, so run news.py
    often while you trade. A filing is matched to your ticker by the symbol in
    its document link, or by the company name from NSE's equity list
    (EQUITY_L.csv, cached in trader/cache/ for a day).
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<TICKER>.NS?range=1d&interval=5m

Times print in India time (IST). State: trader/state/news.json remembers
what you have seen (30 days), so an item shows once. Offline: --offline DIR
reads yahoo-<TICKER>.xml, chart-<TICKER>.json, nse-<feed>.xml and
EQUITY_L.csv from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402

import xml.etree.ElementTree as ET

YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"
CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/%s.xml"
NSE_FEEDS = {"announcements": "Online_announcements", "results": "Financial_Results",
             "board": "Board_Meetings", "actions": "Corporate_action"}
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_L_CACHE = "trader/cache/EQUITY_L.csv"
BROWSER_UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving

# NSE filing subjects that move a stock: flagged "!" like the US 8-K items were.
IMPORTANT = re.compile(r"financial result|outcome of board|acquisition|amalgamation|merger|resignation|"
                       r"insolvency|NCLT|default|delay in payment|credit rating|fraud|pledge|"
                       r"buyback|bonus|split|delisting|trading window|SEBI order", re.I)
KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bprofit\b|\bQ[1-4]\b|\bPAT\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|target price|price target|\boutperform\b|\bunderperform\b|\bbuy rating\b|\bsell rating\b"),
    ("legal", r"\blawsuit\b|\bprobe\b|\binvestigation\b|\bNCLT\b|\bcourt\b|\bED\b raid|\bCBI\b|\btax demand\b|\bpenalty\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bamalgamation\b|\btakeover\b|\bdeal\b|\border win\b|\bbags order\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\bbonus\b|\bsplit\b|\brights issue\b|\bQIP\b|\bOFS\b|\bpledge\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bMD\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\bdefault\b|\binsolvency\b|\bdelist|\bfraud\b|\bdowngrade of rating\b|\bcredit rating\b|\boutage\b"),
    ("halt", r"\btrading (?:halt|suspen)|\bsuspension of trading\b|\bcircuit\b"),
    ("surveillance", r"\bASM\b|\bGSM\b|\bsurveillance\b|\bF&O ban\b"),
    ("regulatory", r"\bSEBI\b|\bRBI\b|\bCCI\b|\bUSFDA\b|\bFDA\b|\bapproval\b|\bwarning letter\b"),
    ("macro", r"\bRBI policy\b|\brepo rate\b|\bCPI\b|\binflation\b|\bGDP\b|\bUnion Budget\b|\bGST\b|\bFIIs?\b|\bFPIs?\b|\bcrude\b|\brupee\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- time

IST_HOURS = 5.5  # India Standard Time, UTC+5:30, no daylight saving


def local_offset(utc):
    """Hours from UTC for India: always +5.5 (no DST)."""
    return IST_HOURS


def to_local(utc):
    return utc.replace(tzinfo=None) + _dt.timedelta(hours=IST_HOURS)


def local_to_utc(local):
    return local - _dt.timedelta(hours=IST_HOURS)


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{ticker: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[market_in.kite_symbol(sym)[1]] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(market_in.kite_symbol(pl["symbol"])[1], pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            s = market_in.kite_symbol(sym)[1]
            out[s] = p.get("name") or out.get(s)
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.15):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"}
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as exc:
            raise NewsError("HTTP %s for %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise NewsError("could not reach %s: %s" % (url, exc.reason))


def yahoo_symbol(ticker):
    return market_in.yahoo_symbol(ticker)


def _norm_name(name):
    """'Tata Consultancy Services Limited' -> 'tata consultancy services'."""
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp|inc)\b", " ", n)
    return " ".join(n.split())


def nse_names(fetcher, cache=EQUITY_L_CACHE):
    """{SYMBOL: company name} from NSE's EQUITY_L.csv, cached for a day."""
    import csv
    import io
    text = None
    if fetcher.offline:
        text = fetcher.get(EQUITY_L_URL, "EQUITY_L.csv").decode("utf-8", "replace")
    elif cache and os.path.isfile(cache) and time.time() - os.path.getmtime(cache) < 86400:
        with open(cache, encoding="utf-8") as fh:
            text = fh.read()
    if text is None:
        text = fetcher.get(EQUITY_L_URL, "EQUITY_L.csv").decode("utf-8", "replace")
        if cache:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as fh:
                fh.write(text)
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows:
        return {}
    hdr = [h.strip() for h in rows[0]]
    si, ni = hdr.index("SYMBOL"), hdr.index("NAME OF COMPANY")
    return {r[si].strip(): r[ni].strip() for r in rows[1:] if len(r) > max(si, ni)}


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS), ISO 8601, or NSE's "24-Nov-2026 00:28:46" (IST) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:  # NSE's RSS: "24-Nov-2026 00:28:46", India time
                d = _dt.datetime.strptime(value, "%d-%b-%Y %H:%M:%S") - _dt.timedelta(hours=IST_HOURS)
                d = d.replace(tzinfo=_dt.timezone.utc)
            except ValueError:
                return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker):
    """Yahoo headline RSS -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        out.append({"id": "rss:" + guid, "source": "Yahoo Finance", "kind": "headline",
                    "ticker": ticker, "title": title, "summary": _text(it, "description"),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_nse_rss(data, feed, watch, names):
    """An NSE filings RSS feed (the whole market) -> items for your tickers only."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("NSE %s feed is not valid XML: %s" % (feed, exc))
    by_name = {}
    for sym in watch:
        n = _norm_name(watch.get(sym) or names.get(sym))
        if n:
            by_name[n] = sym
    out = []
    for it in root.iter("item"):
        company = _text(it, "title")
        link = _text(it, "link")
        desc = _text(it, "description")
        m = re.search(r"/corporate/([A-Z0-9&\-]+?)_\d", link)
        sym = m.group(1) if m and m.group(1) in watch else by_name.get(_norm_name(company))
        if not sym:
            continue
        subject = desc.split("SUBJECT:", 1)[1].strip() if "SUBJECT:" in desc else desc[:160]
        title = "%s: %s" % (company.strip(), subject)
        guid = _text(it, "guid") or ("%s|%s|%s" % (link, company, _text(it, "pubDate")))
        out.append({"id": "nse:%s:%s" % (feed, guid), "source": "NSE filing", "kind": "filing", "form": feed,
                    "ticker": sym, "title": title, "summary": desc, "important": bool(IMPORTANT.search(desc)),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def mention_patterns(watch):
    pats = {}
    for t, name in watch.items():
        alts = [r"\(%s\)" % re.escape(t), r"\$%s\b" % re.escape(t),
                r"\b(?:NSE|BSE)\s*:\s*%s\b" % re.escape(t)]
        if name and len(name) >= 4:
            alts.append(r"\b%s\b" % re.escape(name).replace(r"\ ", r"[\s-]"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
        if it["kind"] == "filing" and it.get("form") == "results" and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def collect(fetcher, watch, state, nse=True, feeds=tuple(NSE_FEEDS), errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % yahoo_symbol(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("headlines for %s: %s" % (t, exc))
    if nse:
        try:
            names = nse_names(fetcher)
        except NewsError as exc:
            errors.append("NSE equity list (company names): %s" % exc)
            names = {}
        for feed in feeds:
            try:
                data = fetcher.get(NSE_RSS % NSE_FEEDS[feed], "nse-%s.xml" % feed)
                items += parse_nse_rss(data, feed, watch, names)
            except NewsError as exc:
                if not (fetcher.offline and "no file" in str(exc)):
                    errors.append("NSE %s feed: %s" % (feed, exc))
    return items


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT):
    out = []
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s IST" % to_local(m["time"]).strftime("%H:%M")) if m.get("time") else ""
        out.append("%-11s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], "{:,.2f}".format(m["price"]), m["pct"], "{:,.2f}".format(m["prev_close"]),
            when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT):
    out = render_moves(moves or [], move_pct)
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = to_local(it["time"]).strftime("%Y-%m-%d %H:%M IST") if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or it["ticker"]
        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"][:160]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % to_local(now).strftime("%Y-%m-%d %H:%M IST"))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--feeds", default=",".join(NSE_FEEDS),
                    help="NSE filing feeds, comma separated (%s)" % ", ".join(NSE_FEEDS))
    ap.add_argument("--no-nse", action="store_true", help="headlines only")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {market_in.kite_symbol(t)[1]: None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no tickers. Pass --tickers, or run /trader-in-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    fetcher = Fetcher(offline=args.offline)
    feeds = [f.strip().lower() for f in args.feeds.split(",") if f.strip()]
    bad = [f for f in feeds if f not in NSE_FEEDS]
    if bad:
        print("news: unknown feed(s) %s; use %s" % (", ".join(bad), ", ".join(NSE_FEEDS)), file=sys.stderr)
        return 2
    items = collect(fetcher, watch, state, nse=not args.no_nse, feeds=feeds, errors=errors)
    items = dedupe(tag(items, watch))
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
