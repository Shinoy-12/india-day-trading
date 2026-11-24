#!/usr/bin/env python3
"""Insider and big-money tracker for trader-in-insider (NSE). Standard library only.
The Indian stand-in for day-trader-skill's US Pelosi tracker (MIT): India has no
STOCK Act, so it watches the trades Indian law makes public instead.

    python3 insider.py new                       # everything not seen at the last check (alerts once)
    python3 insider.py new --holdings            # only stocks in trader/portfolio.json and the plan
    python3 insider.py insider --symbol RELTD    # insider trades in NSE's feed, as rows
    python3 insider.py deals --name "GOLDMAN"    # today's bulk and block deals by a client name
    python3 insider.py holders                   # 5%-holder filings (SAST Reg 29), the live feed
    python3 insider.py read https://nsearchives.nseindia.com/corporate/xbrl/IT_..._WEB.xml

Sources (NSE's public files, no login):
  insider  SEBI insider-trading disclosures (PIT Regulation 7(2)): directors,
           promoters, key managerial people and their relatives must tell the
           company within 2 trading days of a trade over Rs 10 lakh, and the
           company tells the exchange within 2 more. NSE lists them in an RSS
           feed, each with an XBRL file:
           https://nsearchives.nseindia.com/content/RSS/Insider_Trading.xml
           The feed rolls and can lag: check NSE's insider-trading page too.
  bulk     bulk deals: one client trading more than 0.5% of a company's shares
           in a day, published after the close for that day:
           https://nsearchives.nseindia.com/content/equities/bulk.csv
  block    block deals: trades of at least Rs 10 crore in the separate block
           window, published the same way:
           https://nsearchives.nseindia.com/content/equities/block.csv
  holder   5%-holder filings (SEBI takeover code, Regulation 29): anyone
           reaching 5% of a company, or moving 2% or more above it. Live
           (NSE's insider RSS stopped in May 2026), but the feed gives only
           company, who and when; the details are in the linked filing:
           https://nsearchives.nseindia.com/content/RSS/Sast_Regulation29.xml

Rows: source, trade date, disclosed, days to disclose (insider: trading days
from the last trade day to the company being told; over 2 is flagged LATE),
who, category, company, symbol, buy/sell, quantity, value (Rs), average price,
mode (market, ESOP, off-market, pledge...), holding before -> after.

It is fast. It is not early. An insider trade is public days after it happens,
a bulk or block deal the evening after. There is no inside information here:
only public filings, read quickly. Mode matters: an ESOP allotment or a pledge
is not a market buy.

State: trader/state/insider.json (what was shown, so each item alerts once) and
trader/state/insider-xbrl/ (the XBRL files read). Offline: --offline DIR reads
Insider_Trading.xml, bulk.csv, block.csv and the XBRL files by name from DIR.
Exit code 0 when something new was found (new), else 1.
"""

import argparse
import csv
import datetime as _dt
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402

UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
FEED_URL = "https://nsearchives.nseindia.com/content/RSS/Insider_Trading.xml"
DEALS_URL = "https://nsearchives.nseindia.com/content/equities/%s.csv"
INSIDER_PAGE = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"
# SEBI takeover code Regulation 29: anyone reaching 5% of a company, or moving 2% or more above
# that, discloses it. Live, unlike the insider feed; the details are in PDFs inside a ZIP.
HOLDERS_URL = "https://nsearchives.nseindia.com/content/RSS/Sast_Regulation29.xml"
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_L_CACHE = "trader/cache/EQUITY_L.csv"
STATE = "trader/state/insider.json"
XBRL_DIR = "trader/state/insider-xbrl"
LATE_TRADING_DAYS = 2
KEEP_DAYS = 120


class InsiderError(Exception):
    pass


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.4):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url):
        if self.offline:
            path = os.path.join(self.offline, url.rstrip("/").rsplit("/", 1)[-1])
            if not os.path.isfile(path):
                raise InsiderError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise InsiderError("NSE answered HTTP %d for %s" % (e.code, url.rsplit("/", 1)[-1]))
        except urllib.error.URLError as e:
            raise InsiderError("could not reach nsearchives.nseindia.com: %s" % e.reason)


# ---------------------------------------------------------------- dates

def _d(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def trading_days_between(a, b):
    """Trading days after a, up to and including b (0 when b <= a). Unknown years count weekdays."""
    if not a or not b or b <= a:
        return 0
    n, d = 0, a
    while d < b:
        d += _dt.timedelta(days=1)
        try:
            n += 1 if market_in.trading_day(d)[0] else 0
        except market_in.MarketError:
            n += 1 if d.weekday() < 5 else 0
    return n


# ---------------------------------------------------------------- insider (PIT) filings

def parse_feed(data):
    """NSE insider RSS -> [{company, link, published}] (XBRL links only)."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise InsiderError("the insider feed is not valid XML: %s" % e)
    out = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        if "/xbrl/" not in link:
            continue
        out.append({"company": " ".join((it.findtext("title") or "").split()), "link": link,
                    "published": (it.findtext("pubDate") or "").strip()})
    return out


def _fields(xml_bytes):
    """XBRL -> {local element name: [values in document order]}."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        raise InsiderError("an insider XBRL file is not valid XML: %s" % e)
    out = {}
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1]
        txt = (el.text or "").strip()
        if txt:
            out.setdefault(name, []).append(txt)
    return out


def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse_xbrl(xml_bytes, link="", published=""):
    """One PIT disclosure (it can list several people) -> rows."""
    f = _fields(xml_bytes)

    def col(name):
        return f.get(name) or []
    people = col("NameOfThePerson")
    rows = []
    for i, who in enumerate(people or [""]):
        def at(name):
            v = col(name)
            return v[i] if i < len(v) else (v[0] if len(v) == 1 else None)
        qty = _num(at("SecuritiesAcquiredOrDisposedNumberOfSecurity"))
        value = _num(at("SecuritiesAcquiredOrDisposedValueOfSecurity"))
        side = (at("SecuritiesAcquiredOrDisposedTransactionType") or "").strip()
        d_from = _d(at("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate"))
        d_to = _d(at("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate")) or d_from
        told = _d(at("DateOfIntimationToCompany"))
        delay = trading_days_between(d_to, told) if d_to and told else None
        sym = (at("NSESymbol") or "").strip()
        rows.append({
            "source": "insider", "symbol": sym if sym and sym.upper() != "NOTLISTED" else "",
            "company": at("NameOfTheCompany") or "", "who": who, "category": at("CategoryOfPerson") or "",
            "side": side.lower() if side else "", "instrument": at("TypeOfInstrument") or "",
            "quantity": int(qty) if qty is not None else None, "value_inr": value,
            "avg_price": round(value / qty, 2) if value and qty else None,
            "trade_from": d_from.isoformat() if d_from else None, "trade_to": d_to.isoformat() if d_to else None,
            "told_company": told.isoformat() if told else None, "published": published,
            "trading_days_to_disclose": delay, "late": delay is not None and delay > LATE_TRADING_DAYS,
            "mode": at("ModeOfAcquisitionOrDisposal") or "",
            "held_before_pct": _num(at("SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding")),
            "held_after_pct": _num(at("SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding")),
            "regulation": at("RegulationOfInsiderTrading") or "", "link": link,
            "id": "insider:%s:%d" % (link.rsplit("/", 1)[-1], i),
        })
    return rows


def read_xbrl(fetcher, link, cache=XBRL_DIR):
    name = link.rsplit("/", 1)[-1]
    path = os.path.join(cache, name) if cache else None
    if path and os.path.isfile(path) and not fetcher.offline:
        with open(path, "rb") as fh:
            return fh.read()
    data = fetcher.get(link)
    if path and not fetcher.offline:
        os.makedirs(cache, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    return data


def insider_rows(fetcher, limit=None, errors=None):
    errors = [] if errors is None else errors
    items = parse_feed(fetcher.get(FEED_URL))
    rows = []
    for it in items[:limit] if limit else items:
        try:
            rows += parse_xbrl(read_xbrl(fetcher, it["link"]), it["link"], it["published"])
        except InsiderError as e:
            errors.append("%s: %s" % (it["company"], e))
    return rows


# ---------------------------------------------------------------- bulk and block deals

def parse_deals(data, kind):
    """bulk.csv / block.csv -> rows."""
    text = data.decode("utf-8", "replace").lstrip("﻿")
    if text.lstrip().startswith("<"):
        raise InsiderError("NSE sent a web page instead of %s.csv" % kind)
    rows = []
    rd = csv.reader(io.StringIO(text))
    hdr = [h.strip().lower() for h in next(rd, [])]
    if "symbol" not in hdr or "client name" not in hdr:
        raise InsiderError("%s.csv has an unexpected format (header %s)" % (kind, ",".join(hdr)[:80]))
    ix = {h: i for i, h in enumerate(hdr)}
    pcol = next((h for h in hdr if h.startswith("trade price")), None)
    for i, r in enumerate(rd):
        if len(r) < len(hdr) or not r[ix["symbol"]].strip():
            continue
        qty = _num(r[ix["quantity traded"]])
        price = _num(r[ix[pcol]]) if pcol else None
        d = _d(r[ix["date"]].title())
        rows.append({
            "source": kind, "symbol": r[ix["symbol"]].strip(), "company": r[ix["security name"]].strip(),
            "who": r[ix["client name"]].strip(), "category": "%s deal client" % kind,
            "side": r[ix["buy/sell"]].strip().lower(), "quantity": int(qty) if qty is not None else None,
            "avg_price": price, "value_inr": round(qty * price, 2) if qty and price else None,
            "trade_from": d.isoformat() if d else None, "trade_to": d.isoformat() if d else None,
            "told_company": None, "published": d.isoformat() if d else "", "trading_days_to_disclose": 0,
            "late": False, "mode": "market (%s window)" % kind if kind == "block" else "market",
            "remarks": r[ix["remarks"]].strip() if "remarks" in ix and r[ix["remarks"]].strip() != "-" else "",
            "link": DEALS_URL % kind,
            "id": "%s:%s:%s:%s:%s:%s" % (kind, r[ix["date"]], r[ix["symbol"]], r[ix["client name"]],
                                        r[ix["buy/sell"]], r[ix["quantity traded"]]),
        })
    return rows


def deal_rows(fetcher, errors=None):
    errors = [] if errors is None else errors
    got = {}
    for kind in ("bulk", "block"):
        try:
            got[kind] = parse_deals(fetcher.get(DEALS_URL % kind), kind)
        except InsiderError as e:
            errors.append("%s deals: %s" % (kind, e))
            got[kind] = []
    # NSE's bulk file repeats trades done in the block window: keep those once, as block deals
    key = lambda r: (r["trade_to"], r["symbol"], r["who"], r["side"], r["quantity"])
    blocks = {key(r) for r in got["block"]}
    return [r for r in got["bulk"] if key(r) not in blocks] + got["block"]


# ---------------------------------------------------------------- 5% holders (SAST Regulation 29)

def _norm_name(name):
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp|inc)\b", " ", n)
    return " ".join(n.split())


def symbols_by_name(fetcher, cache=EQUITY_L_CACHE):
    """{normalized company name: SYMBOL} from NSE's EQUITY_L.csv, cached for a day."""
    text = None
    if not fetcher.offline and cache and os.path.isfile(cache) and time.time() - os.path.getmtime(cache) < 86400:
        with open(cache, encoding="utf-8") as fh:
            text = fh.read()
    if text is None:
        text = fetcher.get(EQUITY_L_URL).decode("utf-8", "replace")
        if cache and not fetcher.offline:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as fh:
                fh.write(text)
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    hdr = [h.strip() for h in rows[0]] if rows else []
    if "SYMBOL" not in hdr or "NAME OF COMPANY" not in hdr:
        raise InsiderError("NSE's equity list has an unexpected format")
    si, ni = hdr.index("SYMBOL"), hdr.index("NAME OF COMPANY")
    return {_norm_name(r[ni]): r[si].strip() for r in rows[1:] if len(r) > max(si, ni)}


def parse_holders(data, names):
    """NSE's SAST Regulation 29 RSS -> rows: who filed on which company, and when."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise InsiderError("the 5%-holder feed is not valid XML: %s" % e)
    rows = []
    for it in root.iter("item"):
        company = " ".join((it.findtext("title") or "").split())
        desc = " ".join((it.findtext("description") or "").split())
        who = desc.split(":", 1)[1].strip() if ":" in desc else desc
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        d = _d(pub)
        rows.append({
            "source": "holder", "symbol": names.get(_norm_name(company), ""), "company": company,
            "who": who, "category": "5% holder (SAST Reg 29)", "side": "", "quantity": None,
            "avg_price": None, "value_inr": None, "trade_from": None, "trade_to": d.isoformat() if d else None,
            "told_company": None, "published": pub, "trading_days_to_disclose": None, "late": False,
            "mode": "", "remarks": "", "link": link, "id": "holder:%s" % (link or company + pub + who),
        })
    return rows


def holder_rows(fetcher, errors=None):
    errors = [] if errors is None else errors
    try:
        names = symbols_by_name(fetcher)
    except InsiderError as e:
        errors.append("NSE equity list (for symbols): %s" % e)
        names = {}
    return parse_holders(fetcher.get(HOLDERS_URL), names)


# ---------------------------------------------------------------- filters and holdings

def held_symbols(portfolio="trader/portfolio.json", plan="trader/plan.json", watchlist=None):
    out = set()
    for path in (portfolio, plan):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            continue
        for p in doc.get("positions", []) if isinstance(doc, dict) else []:
            s = p.get("ticker") or p.get("symbol")
            if s:
                out.add(market_in.kite_symbol(s)[1])
        if isinstance(doc, dict) and doc.get("symbol"):
            out.add(market_in.kite_symbol(doc["symbol"])[1])
    return out


def filt(rows, symbol=None, name=None, side=None, min_value=None, market_only=False):
    out = []
    for r in rows:
        if symbol and r["symbol"].upper() != market_in.kite_symbol(symbol)[1]:
            continue
        if name and name.lower() not in ("%s %s" % (r["who"], r["company"])).lower():
            continue
        if side and r["side"] != side:
            continue
        if min_value and (r.get("value_inr") or 0) < min_value:
            continue
        if market_only and not re.search(r"market", r.get("mode") or "", re.I):
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------- output

def money(v):
    if v is None:
        return "-"
    return ("₹%.2f cr" % (v / 1e7)) if v >= 1e7 else ("₹%.2f lakh" % (v / 1e5)) if v >= 1e5 \
        else "₹{:,.0f}".format(v)


def line(r, held=()):
    flag = "  << YOU HOLD %s" % r["symbol"] if r["symbol"] in held else ""
    if r["source"] == "holder":
        return ("HOLDER  %-11s %s: %s filed a 5%%-holder disclosure (SAST Reg 29), published %s%s\n"
                "        buy or sell, shares and %% are in the filing: %s" % (
                    r["symbol"] or "(no NSE sym)", r["company"][:40], r["who"][:60], r["published"], flag, r["link"]))
    when = r["trade_from"] or "?"
    if r.get("trade_to") and r["trade_to"] != r["trade_from"]:
        when += " to " + r["trade_to"]
    head = "%-7s %-11s %-4s %s %s (%s) by %s, %s" % (
        r["source"].upper(), r["symbol"] or "(no NSE sym)", r["side"].upper()[:4],
        "{:,}".format(r["quantity"]) if r["quantity"] is not None else "?", r["company"][:40],
        money(r.get("value_inr")), r["who"][:48], r["category"])
    tail = ["traded %s" % when]
    if r["avg_price"]:
        tail.append("avg ₹%.2f" % r["avg_price"])
    if r["mode"]:
        tail.append("mode: %s" % r["mode"])
    if r.get("held_before_pct") is not None and r.get("held_after_pct") is not None:
        tail.append("holding %.2f%% -> %.2f%%" % (r["held_before_pct"], r["held_after_pct"]))
    if r["source"] == "insider" and r.get("told_company"):
        tail.append("told the company %s (%s trading day%s)%s" % (
            r["told_company"], r["trading_days_to_disclose"], "" if r["trading_days_to_disclose"] == 1 else "s",
            " LATE" if r["late"] else ""))
    if r.get("remarks"):
        tail.append(r["remarks"])
    return head + flag + "\n        " + ", ".join(tail) + ("\n        " + r["link"] if r["source"] == "insider" else "")


STALE_DAYS = 14


def feed_note(fetcher):
    """A note when NSE's insider RSS has gone quiet (its newest filing is old)."""
    try:
        items = parse_feed(fetcher.get(FEED_URL))
    except InsiderError:
        return None
    dates = [d for d in (_d(i["published"]) for i in items) if d]
    if not dates:
        return None
    age = (_dt.date.today() - max(dates)).days
    if age > STALE_DAYS and not fetcher.offline:
        return ("NSE's insider RSS feed's newest filing is from %s (%d days ago): the feed may have stopped "
                "updating, so newer insider trades can be missing here. The full list is on %s"
                % (max(dates).isoformat(), age, INSIDER_PAGE))
    return None


def show(rows, held, errors, title):
    print(title)
    if not rows:
        print("  nothing to show.")
    for r in sorted(rows, key=lambda r: (r["trade_to"] or "", r.get("value_inr") or 0), reverse=True):
        print(line(r, held))
    for e in errors:
        print("note: " + e)
    print("Public filings, read quickly: fast, not early. An insider trade is public days after it happens; "
          "an ESOP or a pledge is not a market buy. Not advice.")


# ---------------------------------------------------------------- state

def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"seen": {}}


def save_state(path, state, now):
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v >= cutoff}
    state["last_check"] = now.isoformat()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- commands

def _common_filters(a, rows):
    return filt(rows, a.symbol, a.name, a.side, a.min_value, getattr(a, "market_only", False))


def cmd_insider(a, fetcher, held):
    errors = []
    rows = _common_filters(a, insider_rows(fetcher, a.limit, errors))
    note = feed_note(fetcher)
    if note:
        errors.append(note)
    if a.holdings:
        rows = [r for r in rows if r["symbol"] in held]
    if a.json:
        print(json.dumps({"rows": rows, "notes": errors}, indent=2))
    else:
        show(rows, held, errors, "Insider trades in NSE's feed (SEBI PIT disclosures), newest trade first:")
        if not note:
            print("NSE's insider RSS can lag. Full list: %s" % INSIDER_PAGE)
    return 0 if rows else 1


def cmd_deals(a, fetcher, held):
    errors = []
    rows = _common_filters(a, deal_rows(fetcher, errors))
    if a.holdings:
        rows = [r for r in rows if r["symbol"] in held]
    if a.json:
        print(json.dumps({"rows": rows, "notes": errors}, indent=2))
    else:
        show(rows, held, errors, "NSE bulk and block deals (the latest day NSE published), biggest first:")
    return 0 if rows else 1


def cmd_holders(a, fetcher, held):
    errors = []
    rows = _common_filters(a, holder_rows(fetcher, errors))
    if a.holdings:
        rows = [r for r in rows if r["symbol"] in held]
    if a.json:
        print(json.dumps({"rows": rows, "notes": errors}, indent=2))
    else:
        show(rows, held, errors, "5%-holder filings in NSE's feed (SEBI takeover code, Regulation 29), newest first:")
    return 0 if rows else 1


def cmd_new(a, fetcher, held):
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None)
    state = load_state(a.state)
    seen = state.setdefault("seen", {})
    errors, rows = [], []
    if not a.no_insider:
        try:
            rows += insider_rows(fetcher, a.limit, errors)
        except InsiderError as e:
            errors.append("insider feed: %s" % e)
        note = feed_note(fetcher)
        if note:
            errors.append(note)
    if not a.no_deals:
        rows += deal_rows(fetcher, errors)
    if not a.no_holders:
        try:
            rows += holder_rows(fetcher, errors)
        except InsiderError as e:
            errors.append("5%%-holder feed: %s" % e)
    rows = _common_filters(a, rows)
    if a.holdings:
        rows = [r for r in rows if r["symbol"] in held]
    fresh = [r for r in rows if r["id"] not in seen]
    if a.json:
        print(json.dumps({"new": fresh, "notes": errors}, indent=2))
    else:
        show(fresh, held, errors, "New since the last check (%d new of %d):" % (len(fresh), len(rows)))
        mine = sorted({r["symbol"] for r in fresh if r["symbol"] in held})
        if mine:
            print("ALERT: new filings touch what you hold or plan: %s." % ", ".join(mine))
    if not a.dry_run:
        stamp = now.isoformat()
        for r in rows:
            seen.setdefault(r["id"], stamp)
        save_state(a.state, state, now)
    return 0 if fresh else 1


def cmd_read(a, fetcher, held):
    rows = parse_xbrl(fetcher.get(a.url), a.url)
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        show(rows, held, [], "One insider disclosure:")
    return 0 if rows else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Insider and big-money tracker (trader-in-insider, NSE).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--symbol", help="one NSE symbol")
        p.add_argument("--name", help="a person or client name (part of it), or a company name")
        p.add_argument("--side", choices=["buy", "sell"])
        p.add_argument("--min-value", type=float, help="only trades worth at least this many rupees")
        p.add_argument("--holdings", action="store_true", help="only stocks in trader/portfolio.json and the plan")
        p.add_argument("--portfolio", default="trader/portfolio.json")
        p.add_argument("--plan", default="trader/plan.json")
        p.add_argument("--offline", metavar="DIR")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("new", help="insider filings and deals not seen at the last check (alerts once)")
    common(p)
    p.add_argument("--limit", type=int, help="read only the newest N insider filings")
    p.add_argument("--no-insider", action="store_true")
    p.add_argument("--no-deals", action="store_true")
    p.add_argument("--no-holders", action="store_true", help="skip the 5%%-holder (SAST Reg 29) feed")
    p.add_argument("--market-only", action="store_true", help="hide ESOP, pledge, off-market and gift rows")
    p.add_argument("--state", default=STATE)
    p.add_argument("--dry-run", action="store_true", help="do not remember what was shown")
    p = sub.add_parser("insider", help="insider trades (SEBI PIT) in NSE's feed, as rows")
    common(p)
    p.add_argument("--limit", type=int)
    p.add_argument("--market-only", action="store_true")
    p = sub.add_parser("deals", help="the latest bulk and block deals")
    common(p)
    p = sub.add_parser("holders", help="5%%-holder filings (SAST Regulation 29), the live big-holder feed")
    common(p)
    p = sub.add_parser("read", help="read one insider XBRL disclosure")
    p.add_argument("url")
    p.add_argument("--offline", metavar="DIR")
    p.add_argument("--json", action="store_true")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    fetcher = Fetcher(offline=a.offline)
    held = held_symbols(a.portfolio, a.plan)
    try:
        return {"new": cmd_new, "insider": cmd_insider, "deals": cmd_deals, "holders": cmd_holders, "read": cmd_read}[a.cmd](a, fetcher, held)
    except InsiderError as e:
        print("insider.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
