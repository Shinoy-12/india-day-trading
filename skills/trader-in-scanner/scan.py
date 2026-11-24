#!/usr/bin/env python3
"""Chart Scanner for trader-in-scanner (NSE): scan charts for setups. Standard library only.
Ported from day-trader-skill's US scanner (MIT).

    python3 scan.py universe                          # NSE EQ list x Zerodha MIS list -> trader/universe.txt
    python3 scan.py daily                             # before the open: daily setups -> trader/watchlist.json
    python3 scan.py daily --symbols RELIANCE,SBIN,TCS # or --watchlist FILE, or --limit 200
    python3 scan.py orb                               # after 9:35 AM IST: opening-range breakouts so far
    python3 scan.py orb --at 10:15 --or-minutes 15    # cut the clock at 10:15 AM IST
    python3 scan.py orb --offline day5m.json.gz --now "2026-11-23 10:15" --min-price 0

universe  Downloads NSE's equity list (EQUITY_L.csv), keeps the EQ series (BE/BZ
          are trade-to-trade, no intraday) and keeps only stocks on Zerodha's MIS
          list (shared/zerodha_mis_margins.json), i.e. stocks you can day-trade.
          ETFs are not in EQUITY_L. Stocks with F&O contracts are marked FNO.

daily     Pre-market scan of daily CLOSES from NSE's official bhavcopy (one zip
          per trading day, every stock; the last --days 45 are cached in
          trader/bhavcopy/, so later runs fetch one new file). Closes are
          back-adjusted for splits and bonuses using NSE's adjusted previous
          close. Liquidity: last close >= --min-price (Rs 50) and that day's
          volume >= --min-volume (100,000). --source yahoo uses Yahoo spark
          instead. Setups, from closes only:
            breakout_20d     the last close is above every close of the 20 before it
            bull_flag        up more than 10 % over the 10 sessions before the
                             last 5, then the last 5 closes inside a 5 % range
            reclaim_ma20     closed under the 20-day average, then closed above it
            oversold         RSI 14 (Wilder) under 30
            oversold_bounce  RSI 14 was under 30 yesterday and today closed up
          Today's daily bar is dropped until the session's close.

orb       Opening-range breakouts, 5-minute bars. The range is the first
          --or-minutes (15) of the session, 9:15 IST. Stage 1: spark closes for
          every symbol; a chart goes on only if a completed bar after the range
          closed at or above the highest close of the range. Stage 2: each
          candidate's v8 chart (real highs and lows): a hit = the first completed
          bar to CLOSE above the range high. Stage 2 fetches at most --max-confirm
          (200) charts, most traded first. A chart is usable only when every
          5-minute bar from 9:15 to the cutoff is there. F&O stocks stop
          continuous trading at 15:15 (closing auction). Floors: --min-price 50.

Times are India (IST, UTC+5:30, no DST). --now pins the clock ("2026-11-23
10:15", IST; ...Z for UTC). Market hours, NSE holidays and symbols come from
market_in.py (shared/).

Yahoo's endpoints are free, unofficial and can lag. query2 first, query1 on
a 429 or 5xx, one retry after a pause on a 429. A polite pause between
requests (--pause). Partial results are reported as partial.

--offline PATH reads files instead of the network: universe wants a folder
with EQUITY_L.csv; daily and orb take a folder of <T>.json v8 chart files or
spark responses, or one file that is a spark response, a v8 chart, or a
bundle {"RELIANCE": <v8 json>, ...}. .json.gz is fine.

A scan is a list of charts that match a rule, not a list of stocks to buy.
Exit code 0 when the scan found something, 1 when it did not or could not run.
"""

import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402

UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
YAHOO_HOSTS = ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com")
NSE_EQUITY_FILE = "EQUITY_L.csv"
NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
SPARK_MAX = 20      # Yahoo's spark answers 400 above 20 symbols
PAUSE = 0.3         # seconds between requests: be polite to free endpoints
BACKOFF = 5.0       # seconds to wait before the one retry after a 429
SLEEP = time.sleep  # tests swap this out
BAR_MIN = 5
MAX_CONFIRM = 200   # stage-2 v8 charts per orb scan, most traded first
MIN_DAILY_BARS = 30
DEFAULT_UNIVERSE = "trader/universe.txt"
NOTE = "A scan is a list of charts that match a rule, not a list of stocks to buy."

OPEN = market_in.OPEN        # 09:15 IST
CLOSE = market_in.CLOSE      # 15:30 IST
IST = datetime.timedelta(hours=5, minutes=30)  # India has no DST

SETUPS = [
    ("breakout_20d", "20-day closing-high breakout"),
    ("bull_flag", "bull flag"),
    ("reclaim_ma20", "reclaimed the 20-day average"),
    ("oversold", "oversold (RSI under 30)"),
    ("oversold_bounce", "oversold bounce"),
]
LABEL = dict(SETUPS)


class ScanError(Exception):
    pass


# ---------------------------------------------------------------- time

def to_local(utc):
    """naive UTC -> naive India time."""
    return utc.replace(tzinfo=None) + IST


def local_to_utc(local):
    return local - IST


def ts_to_local(ts):
    """Unix seconds -> naive India time. Never uses the machine's time zone."""
    return to_local(datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts)))


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as India time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise ScanError('--now wants a time like "2026-11-23 10:15" (IST) or ...Z (UTC)')
    if dt.tzinfo is None:
        return local_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_hhmm(text, flag="--at"):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", text or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ScanError("%s wants an India time like 10:15" % flag)
    return datetime.time(int(m.group(1)), int(m.group(2)))


def trading_day(d):
    """(is_trading_day, reason). Weekends and the NSE holiday list (market_in)."""
    try:
        return market_in.trading_day(d)
    except market_in.MarketError as e:
        raise ScanError(str(e))


def session(d, fno=False):
    """(open_time, close_time) of continuous trading in India time, or None if closed.
    fno=True: F&O stocks stop at the closing-auction start (15:15)."""
    try:
        return market_in.session(d, fno)
    except market_in.MarketError as e:
        raise ScanError(str(e))


def clock_label(t):
    """datetime or time -> '10:15 AM'."""
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def day_label(d):
    return "%s %s" % (d.strftime("%a"), d.isoformat())


# ---------------------------------------------------------------- network

def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_get(path):
    """GET a Yahoo Finance path. query2 first, query1 on a 429 or 5xx, and one
    more round after BACKOFF seconds if a 429 was seen. 4xx other than 429 is final."""
    last = "no answer"
    for attempt in (0, 1):
        saw_429 = False
        for host in YAHOO_HOSTS:
            try:
                return http_get(host + path)
            except urllib.error.HTTPError as e:
                last = "HTTP %d" % e.code
                try:
                    body = e.read().decode("utf-8", "replace") if 400 <= e.code < 500 and e.code != 429 else ""
                except Exception:
                    body = ""
                finally:
                    e.close()
                if e.code == 429:
                    saw_429 = True
                    continue
                if e.code >= 500:
                    continue
                if body.strip().startswith("{"):
                    return body  # Yahoo's JSON error ("No data found"), parsed by the caller
                raise ScanError("Yahoo answered %s for %s" % (last, path.split("?")[0]))
            except (urllib.error.URLError, OSError) as e:
                last = str(getattr(e, "reason", e))
                continue
        if attempt == 0 and saw_429:
            SLEEP(BACKOFF)
            continue
        break
    raise ScanError("Yahoo answered %s for %s" % (last, path.split("?")[0]))


def to_yahoo(sym):
    """RELIANCE -> RELIANCE.NS (M&M -> M&M.NS); URL-quoted where used."""
    return market_in.yahoo_symbol(sym)


def from_yahoo(ysym):
    """RELIANCE.NS -> RELIANCE."""
    return market_in.kite_symbol(ysym)[1]


def spark_path(symbols, rng, interval):
    return "/v7/finance/spark?symbols=%s&range=%s&interval=%s" % (
        ",".join(urllib.parse.quote(to_yahoo(s), safe="") for s in symbols), rng, interval)


def chart_path(sym, rng, interval):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (urllib.parse.quote(to_yahoo(sym), safe=""), rng, interval)


# ---------------------------------------------------------------- parsing

def series_from_result(res):
    """A Yahoo chart result (v8 or one spark response) -> plain lists."""
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    t = res.get("timestamp") or []
    n = len(t)

    def col(k):
        v = q.get(k)
        return list(v) + [None] * (n - len(v)) if isinstance(v, list) else None
    return {"t": list(t), "c": col("close") or [None] * n, "o": col("open"), "h": col("high"),
            "l": col("low"), "v": col("volume"), "meta": res.get("meta") or {}}


def parse_spark(text_or_doc, wanted=None):
    """Spark JSON -> {SYM: series}. Symbols Yahoo does not know are simply missing
    from the answer. `wanted` maps Yahoo symbols back to ours (RELIANCE.NS -> RELIANCE)."""
    doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
    sp = (doc or {}).get("spark") if isinstance(doc, dict) else None
    if not isinstance(sp, dict):
        raise ScanError("Yahoo's spark answer is not the shape this tool knows")
    err = sp.get("error")
    out = {}
    for item in sp.get("result") or []:
        resp = item.get("response") or []
        if not resp:
            continue
        ysym = item.get("symbol") or (resp[0].get("meta") or {}).get("symbol") or ""
        sym = (wanted or {}).get(ysym.upper(), from_yahoo(ysym))
        out[sym] = series_from_result(resp[0])
    if err and not out:
        raise ScanError("Yahoo spark: %s" % (err.get("description") or err.get("code") or err))
    return out


def parse_chart(text_or_doc, sym=""):
    """v8 chart JSON -> series. Raises ScanError for Yahoo's 'no data' answers."""
    try:
        doc = json.loads(text_or_doc) if isinstance(text_or_doc, str) else text_or_doc
        chart = doc["chart"]
    except (ValueError, KeyError, TypeError):
        raise ScanError("Yahoo returned something unexpected for %s" % sym)
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise ScanError("no data for %s: %s" % (sym, err.get("description", "unknown ticker")))
    return series_from_result(res[0])


def _read_maybe_gz(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _stem(name):
    for ext in (".json.gz", ".json"):
        if name.endswith(ext):
            return name[:-len(ext)]
    return name


def _absorb(doc, name_hint, data, errors):
    """One parsed offline JSON doc -> data / errors."""
    if isinstance(doc, dict) and "spark" in doc:
        data.update(parse_spark(doc))
    elif isinstance(doc, dict) and "chart" in doc:
        sym = name_hint
        if not sym:
            try:
                sym = (doc["chart"].get("result") or [{}])[0]["meta"]["symbol"]
            except (AttributeError, KeyError, TypeError, IndexError):
                raise ScanError("an offline v8 chart without a symbol: name the file <TICKER>.json")
        sym = from_yahoo(sym)
        try:
            data[sym] = parse_chart(doc, sym)
        except ScanError as e:
            errors[sym] = str(e)
    elif isinstance(doc, dict):
        for k, v in doc.items():
            _absorb(v, k, data, errors)
    else:
        raise ScanError("offline file %s is not a spark answer, a v8 chart or a bundle" % name_hint)


def load_offline(path):
    """A folder of <T>.json(.gz) files or one file -> ({SYM: series}, {SYM: error})."""
    data, errors = {}, {}
    if os.path.isdir(path):
        names = sorted(f for f in os.listdir(path) if f.endswith((".json", ".json.gz")))
        if not names:
            raise ScanError("no .json files in %s" % path)
        for f in names:
            try:
                doc = json.loads(_read_maybe_gz(os.path.join(path, f)))
            except ValueError as e:
                raise ScanError("%s is not valid JSON: %s" % (f, e))
            if isinstance(doc, dict) and ("chart" in doc or "spark" in doc):
                _absorb(doc, "" if "spark" in doc else _stem(f), data, errors)
            else:
                _absorb(doc, "", data, errors)
    elif os.path.isfile(path):
        try:
            doc = json.loads(_read_maybe_gz(path))
        except ValueError as e:
            raise ScanError("%s is not valid JSON: %s" % (path, e))
        _absorb(doc, "", data, errors)
    else:
        raise ScanError("no offline file or folder at %s" % path)
    return data, errors


# ---------------------------------------------------------------- universe

def parse_equity_list(text):
    """NSE EQUITY_L.csv -> rows (dicts with stripped header names)."""
    import csv
    import io
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows or "SYMBOL" not in [h.strip() for h in rows[0]]:
        raise ScanError("not NSE's EQUITY_L.csv (header %s)" % (",".join(rows[0])[:60] if rows else "empty"))
    hdr = [h.strip() for h in rows[0]]
    return [dict(zip(hdr, [c.strip() for c in r])) for r in rows[1:] if r]


def build_universe(text, mis, fno):
    """EQUITY_L text, MIS symbols, F&O symbols -> (kept [(SYM, name, is_fno)], counts)."""
    kept, counts = [], {"rows": 0}
    for r in parse_equity_list(text):
        counts["rows"] += 1
        sym = r.get("SYMBOL", "")
        if r.get("SERIES") not in market_in.RULES.get("tradable_series", ["EQ"]):
            why = "not EQ series (trade-to-trade or other)"
        elif sym not in mis:
            why = "not allowed for MIS at Zerodha"
        else:
            why = "keep"
            kept.append((sym, r.get("NAME OF COMPANY", ""), sym in fno))
        counts[why] = counts.get(why, 0) + 1
    return sorted(kept), counts


# ---------------------------------------------------------------- daily setups

def rsi(closes, n=14):
    """Wilder's RSI on closes (the same math as the reel's refs/scan.py)."""
    if len(closes) < n + 1:
        return None
    g = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    lo = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
    ag, al = sum(g[:n]) / n, sum(lo[:n]) / n
    for i in range(n, len(g)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + lo[i]) / n
    return 100 - 100 / (1 + ag / al) if al else 100.0


def daily_closes(series, now_utc):
    """[(date, close)] of COMPLETE daily bars: null closes dropped, today's bar dropped
    until the session closes, anything dated after the clock dropped."""
    now = to_local(now_utc)
    today = now.date()
    s = session(today)
    today_done = s is None or now.time() >= s[1]
    out = {}
    for ts, c in zip(series["t"], series["c"]):
        if c is None:
            continue
        d = ts_to_local(ts).date()
        if d > today or (d == today and not today_done):
            continue
        out[d] = float(c)  # one bar a day: a late duplicate (the live tick) wins
    return sorted(out.items())


def find_setups(closes):
    """closes (oldest first, >= 30) -> (setup keys, numbers)."""
    c = closes
    last = c[-1]
    hi20 = max(c[-21:-1])
    ma20 = sum(c[-20:]) / 20.0
    ma20_prev = sum(c[-21:-1]) / 20.0
    run = c[-6] / c[-16] - 1
    rng5 = (max(c[-5:]) - min(c[-5:])) / last
    r = rsi(c)
    r_prev = rsi(c[:-1])
    tags = []
    if last > hi20:
        tags.append("breakout_20d")
    if run > 0.10 and rng5 < 0.05:
        tags.append("bull_flag")
    if c[-2] < ma20_prev and last > ma20:
        tags.append("reclaim_ma20")
    if r is not None and r < 30:
        tags.append("oversold")
    if r_prev is not None and r_prev < 30 and last > c[-2]:
        tags.append("oversold_bounce")
    return tags, {"rsi": r, "rsi_prev": r_prev, "high20": hi20, "ma20": ma20,
                  "run_pct": run * 100, "range5_pct": rng5 * 100}


def scan_daily(data, symbols, now_utc, min_price, min_volume):
    """Pure. data = {SYM: series}. Returns (hits, counts, last_date)."""
    hits, dates = [], {}
    counts = {"requested": len(symbols), "fetched": 0, "illiquid": 0, "short": 0, "scanned": 0}
    for sym in symbols:
        s = data.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        bars = daily_closes(s, now_utc)
        meta = s.get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None and bars:
            price = bars[-1][1]
        vol = meta.get("regularMarketVolume")
        if price is None or price < min_price or (min_volume > 0 and (vol is None or vol < min_volume)):
            counts["illiquid"] += 1
            continue
        if len(bars) < MIN_DAILY_BARS:
            counts["short"] += 1
            continue
        counts["scanned"] += 1
        d_last = bars[-1][0]
        dates[d_last] = dates.get(d_last, 0) + 1
        closes = [c for _, c in bars]
        tags, nums = find_setups(closes)
        if tags:
            hits.append({"symbol": sym, "setups": tags, "fno": market_in.is_fno(sym), "price": round(closes[-1], 2),
                         "close_date": d_last.isoformat(), "rsi": round(nums["rsi"], 1),
                         "volume": int(vol) if vol is not None else None})
    hits.sort(key=lambda h: (-(h["price"] * (h["volume"] or 0)), h["symbol"]))  # most rupees traded first
    last_date = max(dates, key=lambda d: (dates[d], d)) if dates else None
    counts["hits"] = len(hits)
    return hits, counts, last_date


# ---------------------------------------------------------------- opening-range breakout

def slot(day, k):
    return datetime.datetime.combine(day, OPEN) + datetime.timedelta(minutes=BAR_MIN * k)


def session_bars(series, day, cutoff, fno=False):
    """5-minute bars of `day` that are complete at `cutoff` (naive India time),
    on the grid, with a close, inside continuous trading. Sorted, one per slot."""
    s = session(day, fno)
    close_t = s[1] if s else CLOSE
    out = {}
    hs, ls = series.get("h"), series.get("l")
    for i, ts in enumerate(series["t"]):
        c = series["c"][i]
        if c is None:
            continue
        et = ts_to_local(ts)
        if et.date() != day or et.second or et.minute % BAR_MIN:
            continue  # another day, or the live tick off the grid
        if et.time() < OPEN or et.time() >= close_t:
            continue  # pre-open auction, closing auction, after hours
        if et + datetime.timedelta(minutes=BAR_MIN) > cutoff:
            continue  # still in progress at the cutoff
        v = series.get("v")
        out[et] = {"start": et, "c": float(c),
                   "h": None if not hs or hs[i] is None else float(hs[i]),
                   "l": None if not ls or ls[i] is None else float(ls[i]),
                   "v": (v[i] or 0) if v else 0}
    return [out[k] for k in sorted(out)]


def usable(bars, day, cutoff, n_range, fno=False):
    """Every slot from 9:15 to the cutoff (or the stock's close) is there, and at least the range."""
    want = int((cutoff - slot(day, 0)).total_seconds() // (BAR_MIN * 60))
    s = session(day, fno)
    if s:
        want = min(want, int((datetime.datetime.combine(day, s[1]) - slot(day, 0)).total_seconds()
                             // (BAR_MIN * 60)))
    if want < n_range or len(bars) != want:
        return False
    return all(b["start"] == slot(day, k) for k, b in enumerate(bars))


def range_ok(bars, day, n_range):
    """The opening-range bars are all there and at least one bar follows them."""
    return (len(bars) > n_range
            and all(b["start"] == slot(day, k) for k, b in enumerate(bars[:n_range])))


def orb_candidate(bars, n_range):
    """Stage 1, closes only: some completed bar after the range closed at or above
    the highest close of the range. Necessary for a breakout (range high >= any range close)."""
    top = max(b["c"] for b in bars[:n_range])
    return any(b["c"] >= top for b in bars[n_range:])


def orb_hit(bars, n_range):
    """Stage 2, real highs and lows: the first completed bar to CLOSE above the range high."""
    rng = bars[:n_range]
    if any(b["h"] is None or b["l"] is None for b in rng):
        return None
    oh = max(b["h"] for b in rng)
    ol = min(b["l"] for b in rng)
    for k in range(n_range, len(bars)):
        b = bars[k]
        if b["c"] > oh:
            closes_at = b["start"] + datetime.timedelta(minutes=BAR_MIN)
            return {"price": round(b["c"], 2), "at": clock_label(closes_at),
                    "bar_start": b["start"].strftime("%H:%M"), "bar_index": k,
                    "or_high": round(oh, 2), "or_low": round(ol, 2),
                    "pct_over": round((b["c"] / oh - 1) * 100, 2), "_t": closes_at}
    return None


def orb_window(now_utc, at, or_minutes, until, explicit_day=None):
    """-> (day, cutoff naive IST) or raise ScanError with the plain message."""
    now = to_local(now_utc)
    day = explicit_day or now.date()
    if or_minutes < BAR_MIN or or_minutes % BAR_MIN or or_minutes > 120:
        raise ScanError("--or-minutes wants a multiple of 5 from 5 to 120 (15 is the classic)")
    ok, why = trading_day(day)
    if not ok:
        raise ScanError("No session on %s (%s): the market is closed. Run orb on a trading day "
                        "after the opening range, or replay a past day with --offline." % (day_label(day), why))
    s = session(day)
    range_end = slot(day, or_minutes // BAR_MIN)
    first_close = range_end + datetime.timedelta(minutes=BAR_MIN)
    close_dt = datetime.datetime.combine(day, s[1])
    if at is not None:
        cutoff = datetime.datetime.combine(day, at)
        if explicit_day is None and cutoff > now + datetime.timedelta(seconds=59):
            raise ScanError("--at %s is later than now (%s IST)." % (at.strftime("%H:%M"), clock_label(now)))
        if cutoff > close_dt:
            raise ScanError("--at %s is after the %s close on %s." % (at.strftime("%H:%M"), clock_label(close_dt),
                                                                       day_label(day)))
    else:
        cutoff = now.replace(second=0, microsecond=0)
        if cutoff >= close_dt:
            raise ScanError("The market closed at %s IST on %s. Replay the session with --at 10:15."
                            % (clock_label(close_dt), day_label(day)))
    if cutoff < first_close:
        raise ScanError("It is %s IST: the %d-minute opening range runs %s to %s and the first bar after it "
                        "closes at %s. Run orb again after %s."
                        % (clock_label(cutoff), or_minutes, clock_label(OPEN), clock_label(range_end), clock_label(first_close),
                           clock_label(first_close)))
    if until is not None and cutoff.time() > until:
        raise ScanError("It is %s IST, after %s, your last time for new entries (no_entries_after): an "
                        "opening-range breakout found now is expired. Run orb tomorrow after %s, or replay "
                        "today with --at 10:15." % (clock_label(cutoff), until.strftime("%H:%M"),
                                                      clock_label(first_close)))
    return day, cutoff


def scan_orb(stage1, symbols, day, cutoff, or_minutes, min_price=0.0, min_volume=0, confirm=None,
             max_confirm=None, fno=frozenset()):
    """stage1 = {SYM: series} with closes (spark or v8). confirm(sym) -> series with highs/lows
    (None = use the stage-1 series). With confirm and max_confirm, only the max_confirm most
    traded candidates (price x volume so far) are confirmed; the rest are counted as unconfirmed.
    fno = symbols whose continuous session ends at the closing auction (15:15).
    Returns (hits, counts, failed {sym: why})."""
    n_range = or_minutes // BAR_MIN
    counts = {"requested": len(symbols), "fetched": 0, "unusable": 0, "illiquid": 0, "scanned": 0,
              "candidates": 0, "confirmed": 0, "unconfirmed": 0}
    hits, failed, cands = [], {}, []
    for sym in symbols:
        s = stage1.get(sym)
        if not s:
            continue
        counts["fetched"] += 1
        f = sym in fno
        bars = session_bars(s, day, cutoff, f)
        # Yahoo's NSE spark data drops 5-minute bars even for liquid stocks, so with a
        # stage 2 coming, stage 1 only needs the range and a bar after it; stage 2's
        # v8 chart is held to every bar.
        ok = (usable(bars, day, cutoff, n_range, f) if confirm is None
              else range_ok(bars, day, n_range))
        if not ok:
            counts["unusable"] += 1
            continue
        vol = sum(b["v"] for b in bars) if s.get("v") else (s.get("meta") or {}).get("regularMarketVolume") or 0
        if bars[-1]["c"] < min_price or vol < min_volume:
            counts["illiquid"] += 1
            continue
        counts["scanned"] += 1
        if orb_candidate(bars, n_range):
            cands.append((sym, bars, bars[-1]["c"] * vol))
    counts["candidates"] = len(cands)
    if confirm is not None and max_confirm and len(cands) > max_confirm:
        cands.sort(key=lambda x: -x[2])
        counts["unconfirmed"] = len(cands) - max_confirm
        cands = cands[:max_confirm]
    for sym, bars, _ in cands:
        full = bars
        if confirm is not None:
            try:
                s2 = confirm(sym)
            except ScanError as e:
                failed[sym] = str(e)
                continue
            full = session_bars(s2, day, cutoff, sym in fno)
            if not usable(full, day, cutoff, n_range, sym in fno):
                failed[sym] = "the v8 chart has a missing bar"
                continue
        counts["confirmed"] += 1
        h = orb_hit(full, n_range)
        if h:
            hits.append(dict({"symbol": sym, "setups": ["orb"], "fno": sym in fno}, **h))
    hits.sort(key=lambda x: (x["_t"], x["symbol"]))
    for h in hits:
        del h["_t"]
    counts["hits"] = len(hits)
    return hits, counts, failed


# ---------------------------------------------------------------- fetching

def progress(a, msg):
    if not getattr(a, "json", False) and not getattr(a, "quiet", False):
        print(msg, file=sys.stderr)


def fetch_spark(symbols, rng, interval, pause, a=None):
    """Batches of 20. -> ({SYM: series}, {SYM: error})."""
    data, failed = {}, {}
    batches = [symbols[i:i + SPARK_MAX] for i in range(0, len(symbols), SPARK_MAX)]
    for k, batch in enumerate(batches):
        if k and pause:
            SLEEP(pause)
        wanted = {to_yahoo(s): s for s in batch}
        try:
            got = parse_spark(yahoo_get(spark_path(batch, rng, interval)), wanted)
        except (ScanError, ValueError) as e:
            for s in batch:
                failed[s] = str(e)
            continue
        for s in batch:
            if s in got:
                data[s] = got[s]
            else:
                failed[s] = "no data from Yahoo"
        if a is not None and len(batches) > 25 and (k + 1) % 50 == 0:
            progress(a, "  spark %d of %d requests" % (k + 1, len(batches)))
    return data, failed


# ---------------------------------------------------------------- NSE bhavcopy (daily)

BHAV_URL = "https://nsearchives.nseindia.com/content/cm/"
BHAV_COLS = ("TradDt", "TckrSymb", "SctySrs", "ClsPric", "PrvsClsgPric", "TtlTradgVol")
BHAV_DAYS = 45                       # trading days to load: setups need 30, RSI warms up on the rest
DEFAULT_BHAV_DIR = "trader/bhavcopy"
ADJ_TOL = 0.005                      # prev-close vs yesterday's close gap that means a corporate action
EPOCH = datetime.datetime(1970, 1, 1)


def bhav_name(d):
    return "BhavCopy_NSE_CM_0_0_0_%s_F_0000.csv.zip" % d.strftime("%Y%m%d")


def parse_bhav(raw):
    """Bhavcopy zip bytes -> {SYM: (close, prev_close, volume)} for tradable series.
    Raises ScanError when NSE's columns are not the ones this parser knows."""
    import csv
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8", "replace")
    except (zipfile.BadZipFile, IndexError) as e:
        raise ScanError("a bhavcopy file is not a readable zip: %s" % e)
    rows = csv.reader(io.StringIO(text.lstrip("﻿")))
    hdr = [h.strip() for h in next(rows, [])]
    missing = [c for c in BHAV_COLS if c not in hdr]
    if missing:
        raise ScanError("NSE's bhavcopy format changed (missing %s); the scanner needs updating, or use "
                        "--source yahoo meanwhile" % ", ".join(missing))
    ix = {c: hdr.index(c) for c in BHAV_COLS}
    series_ok = set(market_in.RULES.get("tradable_series", ["EQ"]))
    out = {}
    for r in rows:
        if len(r) < len(hdr) or r[ix["SctySrs"]].strip() not in series_ok:
            continue
        try:
            out[r[ix["TckrSymb"]].strip()] = (float(r[ix["ClsPric"]]), float(r[ix["PrvsClsgPric"]] or 0),
                                              int(float(r[ix["TtlTradgVol"]] or 0)))
        except ValueError:
            continue
    return out


def get_bhav(d, cache, download, today):
    """One day's bhavcopy, cached under `cache`. -> rows, or None when NSE has no file for
    that day (holiday, or not published yet). A past day's 404 is remembered as .missing."""
    path = os.path.join(cache, bhav_name(d))
    miss = path + ".missing"
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return parse_bhav(fh.read())
    if os.path.exists(miss) or not download:
        return None
    req = urllib.request.Request(BHAV_URL + bhav_name(d), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            if d < today:
                os.makedirs(cache, exist_ok=True)
                open(miss, "w").close()
            return None
        raise ScanError("nsearchives.nseindia.com answered HTTP %d for %s" % (e.code, bhav_name(d)))
    except (urllib.error.URLError, OSError) as e:
        raise ScanError("could not reach nsearchives.nseindia.com: %s" % getattr(e, "reason", e))
    rows = parse_bhav(raw)  # check before caching
    os.makedirs(cache, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(raw)
    return rows


def fetch_bhavcopy(now_utc, days, cache, download, pause, a=None):
    """The last `days` trading days of bhavcopy, oldest first: [(date, rows)].
    Known weekday NSE holidays are skipped without a request. Weekends are asked for
    once (a 404 is remembered), because special sessions such as Diwali's Muhurat
    trading fall on them and the next day's previous close is that session's close."""
    today = to_local(now_utc).date()
    got, d, fetched = [], today, 0
    for _ in range(days * 3):
        if len(got) >= days:
            break
        skip = False
        if d.weekday() < 5:
            try:
                skip = not market_in.trading_day(d)[0]
            except market_in.MarketError:
                pass  # a year with no holiday list: ask NSE, a 404 means no session
        if not skip:
            path = os.path.join(cache, bhav_name(d))
            asks = download and not os.path.exists(path) and not os.path.exists(path + ".missing")
            if asks and fetched and pause:
                SLEEP(pause)
            rows = get_bhav(d, cache, download, today)
            if asks and rows:
                fetched += 1
                if a is not None and fetched % 10 == 0:
                    progress(a, "  bhavcopy: %d files downloaded" % fetched)
            if rows:
                got.append((d, rows))
        d -= datetime.timedelta(days=1)
    return sorted(got), fetched


def bhav_series(daily, symbols):
    """[(date, rows)] oldest first -> ({SYM: series}, {SYM: why}, adjustments).
    Closes are back-adjusted for splits and bonuses: NSE's previous close on an ex-date is
    the adjusted one, so prev_close / yesterday's close is the factor for every earlier close.
    Only when the stock also traded in EQ on the previous loaded day: after a gap (suspension,
    or trading in another series) prev_close may be a price this file set never saw, so a
    mismatch there restarts the stock's history instead of guessing a factor."""
    data, failed, adjusted = {}, {}, 0
    for sym in symbols:
        closes, ts, last_vol, prev, prev_i = [], [], None, None, None
        for i, (d, rows) in enumerate(daily):
            r = rows.get(sym)
            if r is None:
                continue  # not traded that day (suspension) or a different series
            c, pc, v = r
            if prev is not None and pc > 0 and prev > 0 and abs(pc / prev - 1) > ADJ_TOL:
                if prev_i == i - 1:
                    f = pc / prev
                    closes = [x * f for x in closes]
                    adjusted += 1
                else:
                    closes, ts = [], []
            prev_i = i
            closes.append(c)
            ts.append(int((datetime.datetime.combine(d, OPEN) - IST - EPOCH).total_seconds()))
            last_vol, prev = v, c
        if not closes:
            failed[sym] = "not in NSE's bhavcopy (EQ series) for these days"
            continue
        data[sym] = {"t": ts, "c": closes, "o": None, "h": None, "l": None, "v": None,
                     "meta": {"regularMarketPrice": closes[-1], "regularMarketVolume": last_vol}}
    return data, failed, adjusted


def read_symbols(a, offline_syms=None):
    if a.symbols:
        syms = [s for s in re.split(r"[,\s]+", a.symbols.upper()) if s]
    elif a.watchlist:
        syms = symbols_from_file(a.watchlist)
    elif offline_syms is not None and not a.universe:
        syms = sorted(offline_syms)  # offline: every chart in the file, unless a list was given
    else:
        path = a.universe or DEFAULT_UNIVERSE
        if not os.path.exists(path):
            raise ScanError("no %s yet: run `scan.py universe` first, or pass --symbols" % path)
        syms = symbols_from_file(path)
    out = []
    for s in syms:
        if s not in out:
            out.append(s)
    if a.limit:
        out = out[:a.limit]
    if not out:
        raise ScanError("no symbols to scan")
    return out


def symbols_from_file(path):
    if not os.path.exists(path):
        raise ScanError("no file at %s" % path)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if text.lstrip().startswith(("{", "[")):
        try:
            doc = json.loads(text)
        except ValueError as e:
            raise ScanError("%s is not valid JSON: %s" % (path, e))
        items = doc.get("hits", []) if isinstance(doc, dict) else doc
        return [str(x.get("symbol") if isinstance(x, dict) else x).upper() for x in items if x]
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.append(ln.split("|")[0].strip().upper())
    return out


def read_config(path):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except ValueError as e:
        raise ScanError("%s is not valid JSON: %s" % (path, e))
    return cfg if isinstance(cfg, dict) else {}


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


def money(x):
    return "\u20b9{:,.2f}".format(x)


# ---------------------------------------------------------------- commands

def cmd_universe(a):
    t0 = time.time()
    if a.offline:
        p = os.path.join(a.offline, NSE_EQUITY_FILE)
        if not os.path.exists(p):
            raise ScanError("no %s in %s" % (NSE_EQUITY_FILE, a.offline))
        with open(p, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        try:
            text = http_get(NSE_EQUITY_URL, timeout=60)
        except urllib.error.HTTPError as e:
            raise ScanError("nsearchives.nseindia.com answered HTTP %d for %s" % (e.code, NSE_EQUITY_FILE))
        except (urllib.error.URLError, OSError) as e:
            raise ScanError("could not reach nsearchives.nseindia.com: %s" % getattr(e, "reason", e))
    mis_path = os.path.join(market_in.HERE, "zerodha_mis_margins.json")
    if not os.path.exists(mis_path):
        raise ScanError("no %s: run shared/refresh_data.py first" % mis_path)
    with open(mis_path, encoding="utf-8") as fh:
        mis_doc = json.load(fh)
    mis = set(mis_doc["stocks"])
    fno = {s for s in mis if market_in.is_fno(s)}
    kept, counts = build_universe(text, mis, fno)
    if not a.no_write:
        d = os.path.dirname(a.out)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            for sym, name, f in kept:
                fh.write("%s|%s%s\n" % (sym, name, "|FNO" if f else ""))
    dropped = {k: v for k, v in counts.items() if k not in ("keep", "rows")}
    nfno = sum(1 for k in kept if k[2])
    if a.json:
        print(json.dumps({"count": len(kept), "fno": nfno, "rows": counts.get("rows", 0),
                          "mis_list_updated": mis_doc.get("_last_updated"), "dropped": dropped,
                          "out": None if a.no_write else a.out, "seconds": round(time.time() - t0, 1)}, indent=2))
    else:
        print("NSE equity list: %s rows. Zerodha MIS list of %s." % (
            "{:,}".format(counts.get("rows", 0)), mis_doc.get("_last_updated") or "unknown date"))
        print("Kept %s NSE EQ stocks you can trade intraday (MIS); %s of them are F&O stocks "
              "(continuous trading ends 15:15)." % ("{:,}".format(len(kept)), "{:,}".format(nfno)))
        print("Dropped: " + ", ".join("%s %s" % ("{:,}".format(v), k)
                                      for k, v in sorted(dropped.items(), key=lambda kv: -kv[1])) + ".")
        if not a.no_write:
            print("Wrote %s (one SYMBOL|Name[|FNO] a line)." % a.out)
    return 0 if kept else 1


def cmd_daily(a):
    t0 = time.time()
    now = parse_now(a.now)
    offline_syms = None
    if a.offline:
        data, failed = load_offline(a.offline)
        offline_syms = sorted(set(data) | set(failed))
    symbols = read_symbols(a, offline_syms)
    source, label, extra = "offline", "offline files", {}
    if not a.offline and a.source == "yahoo":
        source, label = "yahoo", "Yahoo spark, daily closes only"
        progress(a, "Fetching daily closes for %s symbols (%d spark requests)..."
                 % ("{:,}".format(len(symbols)), (len(symbols) + SPARK_MAX - 1) // SPARK_MAX))
        data, failed = fetch_spark(symbols, "3mo", "1d", a.pause, a)
    elif not a.offline:
        source = "nse_bhavcopy"
        progress(a, "Loading %d days of NSE bhavcopy (cache %s)..." % (a.days, a.bhav_dir))
        daily, downloaded = fetch_bhavcopy(now, a.days, a.bhav_dir, not a.no_download, a.pause, a)
        if len(daily) < MIN_DAILY_BARS:
            raise ScanError("only %d bhavcopy days available (need %d)%s" % (
                len(daily), MIN_DAILY_BARS, "; drop --no-download" if a.no_download else ""))
        data, failed, adjusted = bhav_series(daily, symbols)
        label = "NSE bhavcopy, %d days %s to %s, %d new file%s%s" % (
            len(daily), daily[0][0].isoformat(), daily[-1][0].isoformat(), downloaded,
            "" if downloaded == 1 else "s",
            (", %d split/bonus adjustment%s" % (adjusted, "" if adjusted == 1 else "s")) if adjusted else "")
        extra = {"bhavcopy_days": len(daily), "adjustments": adjusted}
    hits, counts, last_date = scan_daily(data, symbols, now, a.min_price, a.min_volume)
    nfailed = len(symbols) - counts["fetched"]
    as_of = ("%s close" % last_date.isoformat()) if last_date else None
    doc = {"created_by": "trader-in-scanner", "market": "NSE", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "daily",
           "as_of": as_of, "universe": len(symbols), "scanned": counts["scanned"], "failed": nfailed,
           "source": source, "filters": {"min_price": a.min_price, "min_volume": a.min_volume},
           "note": NOTE, "hits": hits}
    doc.update(extra)
    if a.offline:
        doc["offline"] = os.path.basename(a.offline.rstrip("/"))
    if not a.no_write:
        write_json(a.out, doc)
    if a.json:
        print(json.dumps(dict(doc, counts=counts, seconds=round(time.time() - t0, 1)), indent=2))
        return 0 if hits else 1
    local = to_local(now)
    print("Daily scan, %s IST, closes through %s (%s)." % (
        local.strftime("%a %Y-%m-%d %H:%M"), last_date.isoformat() if last_date else "nothing", label))
    print("Fetched %s of %s charts%s. %s passed the liquidity filter (\u20b9%s+ and %s+ shares)%s; "
          "%s scanned." % ("{:,}".format(counts["fetched"]), "{:,}".format(len(symbols)),
                           (" (%s failed or had no data)" % "{:,}".format(nfailed)) if nfailed else "",
                           "{:,}".format(counts["fetched"] - counts["illiquid"]), _n(a.min_price),
                           "{:,}".format(a.min_volume),
                           (", %d had under %d days" % (counts["short"], MIN_DAILY_BARS)) if counts["short"] else "",
                           "{:,}".format(counts["scanned"])))
    if hits:
        per = [(k, sum(1 for h in hits if k in h["setups"])) for k, _ in SETUPS]
        print("%d chart%s matched a setup: %s." % (len(hits), "" if len(hits) == 1 else "s",
                                                  ", ".join("%d %s" % (n, LABEL[k]) for k, n in per if n)))
        print("Most traded first (price x volume):")
    else:
        print("No setups.")
    for h in hits[:a.show]:
        print("  %-11s %12s  RSI %5.1f  %s%s" % (h["symbol"], money(h["price"]), h["rsi"],
                                                  ", ".join(LABEL[t] for t in h["setups"]),
                                                  "  [F&O: closes 15:15]" if h.get("fno") else ""))
    if len(hits) > a.show:
        print("  ... and %d more in the watchlist (--show N for more)." % (len(hits) - a.show))
    if not a.no_write:
        print("Wrote %s (mode daily, %d hit%s)." % (a.out, len(hits), "" if len(hits) == 1 else "s"))
    print(NOTE + " Next: pick one chart, then /trader-in-news TICKER.")
    return 0 if hits else 1


def _n(x):
    x = float(x)
    return str(int(x)) if x == int(x) else "%.2f" % x


def cmd_orb(a):
    t0 = time.time()
    now = parse_now(a.now)
    at = parse_hhmm(a.at) if a.at else None
    cfg = read_config(a.config)
    until = parse_hhmm(a.until or cfg.get("no_entries_after") or "15:00", "--until")
    data = failed = None
    explicit_day = None
    offline_syms = None
    if a.offline:
        data, failed = load_offline(a.offline)
        offline_syms = sorted(set(data) | set(failed))
        if not a.now:
            days = [ts_to_local(s["t"][-1]).date() for s in data.values() if s["t"]]
            if days:
                explicit_day = max(days)
                if at is None:
                    raise ScanError("offline replay: give --at HH:MM or --now \"YYYY-MM-DD HH:MM\"")
    day, cutoff = orb_window(now, at, a.or_minutes, until, explicit_day)
    symbols = read_symbols(a, offline_syms)
    confirm = None
    if not a.offline:
        today = to_local(parse_now(None)).date()
        if (today - day).days > 6:
            raise ScanError("Yahoo's free 5-minute history is short: replay %s with --offline" % day.isoformat())
        rng = "1d" if day == today else "5d"
        progress(a, "Stage 1: 5-minute closes for %s symbols (%d spark requests)..."
                 % ("{:,}".format(len(symbols)), (len(symbols) + SPARK_MAX - 1) // SPARK_MAX))
        data, failed = fetch_spark(symbols, rng, "%dm" % BAR_MIN, a.pause, a)
        done = []

        def confirm(sym):
            if a.pause:
                SLEEP(a.pause)
            done.append(sym)
            if len(done) % 50 == 0:
                progress(a, "  stage 2: %d v8 charts so far" % len(done))
            return parse_chart(yahoo_get(chart_path(sym, rng, "%dm" % BAR_MIN)), sym)
    fno = frozenset(s for s in symbols if market_in.is_fno(s))
    hits, counts, failed2 = scan_orb(data, symbols, day, cutoff, a.or_minutes, a.min_price, a.min_volume, confirm,
                                     a.max_confirm, fno)
    failed = dict(failed or {})
    failed.update(failed2)
    nfailed = len([s for s in symbols if s in failed])
    as_of = "%s %s IST" % (day.isoformat(), cutoff.strftime("%H:%M"))
    doc = {"created_by": "trader-in-scanner", "market": "NSE", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "mode": "orb",
           "as_of": as_of, "universe": len(symbols), "scanned": counts["scanned"], "failed": nfailed,
           "unconfirmed": counts["unconfirmed"], "source": "yahoo", "or_minutes": a.or_minutes,
           "interval": "%dm" % BAR_MIN,
           "filters": {"min_price": a.min_price, "min_volume": a.min_volume}, "note": NOTE, "hits": hits}
    if a.offline:
        doc["offline"] = os.path.basename(a.offline.rstrip("/"))
    if not a.no_write:
        write_json(a.out, doc)
    if a.json:
        print(json.dumps(dict(doc, counts=counts, seconds=round(time.time() - t0, 1)), indent=2))
        return 0 if hits else 1
    print("Opening-range breakout scan, %s %s IST: %d-minute range (%s to %s), 5-minute bars, Yahoo."
          % (day_label(day), clock_label(cutoff), a.or_minutes, clock_label(OPEN),
             clock_label(slot(day, a.or_minutes // BAR_MIN))))
    print("Fetched %s of %s charts%s; %s usable%s; %s candidates, %s confirmed with real highs and lows."
          % ("{:,}".format(counts["fetched"]), "{:,}".format(len(symbols)),
             (" (%s failed or had no data)" % "{:,}".format(nfailed)) if nfailed else "",
             "{:,}".format(counts["scanned"]),
             (" (%s under the price / volume floor)" % "{:,}".format(counts["illiquid"])) if counts["illiquid"] else "",
             "{:,}".format(counts["candidates"]), "{:,}".format(counts["confirmed"])))
    if counts["unconfirmed"]:
        print("PARTIAL: %s more candidates were not checked (only the %s most traded are; --max-confirm 0 "
              "checks all)." % ("{:,}".format(counts["unconfirmed"]), "{:,}".format(a.max_confirm)))
    if hits:
        print("%d of %s charts closed above their opening-range high by %s:"
              % (len(hits), ("the %s checked" % "{:,}".format(counts["confirmed"])) if counts["unconfirmed"]
                 else "{:,}".format(counts["scanned"]), clock_label(cutoff)))
        for h in hits[:a.show]:
            print("  %8s  %-11s %12s  range %s to %s  %+.2f%% over%s" % (
                h["at"], h["symbol"], money(h["price"]), _p(h["or_low"]), _p(h["or_high"]), h["pct_over"],
                "  [F&O: closes 15:15]" if h.get("fno") else ""))
        if len(hits) > a.show:
            print("  ... and %d more in the watchlist (--show N for more)." % (len(hits) - a.show))
    else:
        print("No chart closed above its opening-range high by %s." % clock_label(cutoff))
    if not a.no_write:
        print("Wrote %s (mode orb, %d hit%s)." % (a.out, len(hits), "" if len(hits) == 1 else "s"))
    print(NOTE + " Next: pick one chart, then /trader-in-news TICKER and /trader-in-entry TICKER.")
    return 0 if hits else 1


def _p(x):
    return "{:,.2f}".format(x)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart Scanner (trader-in-scanner, NSE): daily setups and opening-range breakouts.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("universe", help="NSE EQ list x Zerodha MIS list -> trader/universe.txt")
    p.add_argument("--out", default=DEFAULT_UNIVERSE)
    p.add_argument("--offline", metavar="DIR", help="a folder with EQUITY_L.csv")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--pause", type=float, default=PAUSE)
    p.add_argument("--json", action="store_true")

    def common(p, min_price, min_volume):
        g = p.add_mutually_exclusive_group()
        g.add_argument("--symbols", help="comma-separated tickers instead of the universe")
        g.add_argument("--watchlist", metavar="FILE", help="a watchlist.json (hits) or a text file of tickers")
        p.add_argument("--universe", help="symbol list, one SYMBOL|Name a line (default %s)" % DEFAULT_UNIVERSE)
        p.add_argument("--limit", type=int, help="scan only the first N symbols")
        p.add_argument("--min-price", type=float, default=min_price)
        p.add_argument("--min-volume", type=int, default=min_volume)
        p.add_argument("--offline", metavar="PATH", help="fixture folder or file instead of the network")
        p.add_argument("--now", help='pretend it is this time ("2026-11-23 10:15" IST, or ...Z)')
        p.add_argument("--out", default="trader/watchlist.json")
        p.add_argument("--no-write", action="store_true")
        p.add_argument("--pause", type=float, default=PAUSE, help="seconds between requests (%.1f)" % PAUSE)
        p.add_argument("--show", type=int, default=50, help="hits to print (all are written)")
        p.add_argument("--quiet", action="store_true")
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("daily", help="pre-market setups from daily closes (NSE bhavcopy)")
    common(p, 50.0, 100000)
    p.add_argument("--source", choices=("nse", "yahoo"), default="nse",
                   help="nse = NSE's official bhavcopy files (default); yahoo = Yahoo spark")
    p.add_argument("--days", type=int, default=BHAV_DAYS, help="bhavcopy trading days to load (%d)" % BHAV_DAYS)
    p.add_argument("--bhav-dir", default=DEFAULT_BHAV_DIR, help="bhavcopy cache folder (%s)" % DEFAULT_BHAV_DIR)
    p.add_argument("--no-download", action="store_true", help="use cached bhavcopy files only")
    p = sub.add_parser("orb", help="opening-range breakouts so far today")
    common(p, 50.0, 0)
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--max-confirm", type=int, default=MAX_CONFIRM,
                   help="v8 charts to fetch in stage 2, most traded first (%d; 0 = all)" % MAX_CONFIRM)
    p.add_argument("--at", help="cut the clock at this India time, HH:MM")
    p.add_argument("--until", help="no new entries after HH:MM (default: config no_entries_after, 15:00)")
    p.add_argument("--config", default="trader/config.json")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"universe": cmd_universe, "daily": cmd_daily, "orb": cmd_orb}[a.cmd](a)
    except ScanError as e:
        print("scan.py: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("scan.py: stopped", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
