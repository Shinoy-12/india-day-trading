#!/usr/bin/env python3
"""Kite candles for the trader-in-* tools. Standard library only.

Yahoo's free 5-minute bars for NSE stocks sometimes skip a bar. Kite's
historical candles (the Kite MCP's market tool, mode=historical) do not. Two ways
to use them:

  add   Patch only the bars Yahoo is missing (the cheap way). When entry.py or
        timemachine.py says a bar is missing, fetch just that window from Kite,
        save the answer, and add it:
            python3 kite_bars.py add RELIANCE raw.json
        The candles go to trader/bars/kite-RELIANCE-<date>.json, and from then
        on entry.py and timemachine.py fill Yahoo's gaps from it by themselves
        (each slot is fetched from Kite once a day). Yahoo's own bars are never
        replaced. A candle that had not closed when it was fetched is not kept.

  file  Make a whole chart file from Kite candles alone:
            python3 kite_bars.py file RELIANCE raw.json      # -> trader/bars/RELIANCE.json
            python3 entry.py check RELIANCE --offline trader/bars

Input: Kite's answer, {"data": [{"date": "2026-11-23T09:15:00+05:30", "open": ..,
"high": .., "low": .., "close": .., "volume": ..}, ...]} (or the bare list).
"""

import argparse
import datetime
import glob
import json
import os
import sys

STEPS = {"1m": 60, "5m": 300}
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
CACHE_DIR = "trader/bars"


class KiteBarsError(Exception):
    pass


def _epoch(text):
    """"2026-11-23T09:15:00+05:30" -> UTC epoch seconds."""
    try:
        d = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise KiteBarsError("not a Kite candle time: %r" % text)
    if d.tzinfo is None:  # Kite's times are India time
        d = d.replace(tzinfo=IST)
    return int(d.timestamp())


def _ist(t):
    return datetime.datetime.fromtimestamp(t, IST)


def _candles(kite, interval):
    """Kite answer -> sorted [(epoch, row)], checked to be on the interval's grid."""
    if interval not in STEPS:
        raise KiteBarsError("--interval is 5m or 1m")
    rows = kite.get("data") if isinstance(kite, dict) else kite
    if not rows:
        raise KiteBarsError("no candles in the Kite answer")
    bars = sorted(((_epoch(r["date"]), r) for r in rows), key=lambda x: x[0])
    if any(t % STEPS[interval] for t, _ in bars):
        raise KiteBarsError("these are not %s candles: fetch with interval=%s" % (
            interval, "5minute" if interval == "5m" else "minute"))
    return bars


def _clean(sym):
    return sym.upper().replace(".NS", "").replace("NSE:", "")


# ---------------------------------------------------------------- file: a whole chart from Kite

def convert(kite, sym, interval="5m", prev_close=None, fetched=None):
    """Kite historical answer -> (Yahoo v8 chart doc, [missing slot epochs])."""
    step = STEPS.get(interval)
    bars = _candles(kite, interval)
    ts = [t for t, _ in bars]
    missing = []
    for a, b in zip(ts, ts[1:]):
        if step < b - a < 6 * 3600:  # inside one day's run of candles, not overnight
            missing.extend(range(a + step, b, step))
    fetched = int(fetched if fetched is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
    meta = {"symbol": _clean(sym) + ".NS", "exchangeName": "NSI", "currency": "INR",
            "dataGranularity": interval, "regularMarketTime": fetched, "source": "kite"}
    if prev_close is not None:
        meta["previousClose"] = meta["chartPreviousClose"] = float(prev_close)
    quote = {k: [r[k] for _, r in bars] for k in ("open", "high", "low", "close", "volume")}
    doc = {"chart": {"result": [{"meta": meta, "timestamp": ts, "indicators": {"quote": [quote]}}],
                     "error": None}}
    return doc, missing


# ---------------------------------------------------------------- add / patch: fill Yahoo's gaps

def cache_path(sym, day, interval="5m", base=CACHE_DIR):
    return os.path.join(base, "kite-%s-%s%s.json" % (_clean(sym), day, "" if interval == "5m" else "-" + interval))


def add(kite, sym, interval="5m", fetched=None, base=CACHE_DIR):
    """Store Kite's closed candles in the per-day cache. -> (kept, skipped_unclosed)."""
    step = STEPS.get(interval)
    fetched = int(fetched if fetched is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
    kept, skipped, by_day = 0, 0, {}
    for t, r in _candles(kite, interval):
        if t + step > fetched:
            skipped += 1  # still forming when fetched: Kite's numbers would change
            continue
        by_day.setdefault(_ist(t).date().isoformat(), {})[str(t)] = [
            r["open"], r["high"], r["low"], r["close"], r.get("volume") or 0]
    os.makedirs(base, exist_ok=True)
    for day, rows in by_day.items():
        path = cache_path(sym, day, interval, base)
        old = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                old = json.load(fh).get("candles", {})
        old.update(rows)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"symbol": _clean(sym), "date": day, "interval": interval, "source": "kite",
                       "candles": old}, fh)
        kept += len(rows)
    return kept, skipped


def patch_text(text, sym, interval="5m", base=CACHE_DIR):
    """Yahoo chart JSON text -> (text, [patched epochs]). Fills only the slots Yahoo lacks
    (no bar, or a bar with no close) from the Kite cache. Unchanged text when nothing applies."""
    files = glob.glob(cache_path(sym, "*", interval, base))
    if not files:
        return text, []
    try:
        doc = json.loads(text)
        r = doc["chart"]["result"][0]
    except (ValueError, KeyError, TypeError, IndexError):
        return text, []
    if (r.get("meta") or {}).get("source") == "kite":
        return text, []
    kite = {}
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                c = json.load(fh)
            if c.get("interval", "5m") == interval:
                kite.update({int(k): v for k, v in c.get("candles", {}).items()})
        except (OSError, ValueError):
            continue
    ts = list(r.get("timestamp") or [])
    q = ((r.setdefault("indicators", {}).setdefault("quote", [{}]))[0])
    keys = ("open", "high", "low", "close", "volume")
    cols = {k: list(q.get(k) or []) for k in keys}
    for k in keys:
        cols[k] += [None] * (len(ts) - len(cols[k]))
    if ts:
        lo, hi = min(ts) - 86400, max(ts) + 86400  # only days the Yahoo chart covers
        kite = {t: v for t, v in kite.items() if lo <= t <= hi}
    index = {t: i for i, t in enumerate(ts) if t is not None}
    patched = []
    for t in sorted(kite):
        i = index.get(t)
        if i is not None and cols["close"][i] is not None:
            continue  # Yahoo has this bar: keep it
        if i is None:
            ts.append(t)
            for k in keys:
                cols[k].append(None)
            i = len(ts) - 1
        for k, v in zip(keys, kite[t]):
            cols[k][i] = v
        patched.append(t)
    if not patched:
        return text, []
    order = sorted(range(len(ts)), key=lambda i: (ts[i] is None, ts[i] or 0))
    r["timestamp"] = [ts[i] for i in order]
    for k in keys:
        q[k] = [cols[k][i] for i in order]
    r.setdefault("meta", {})["kite_patched"] = sorted(patched)
    return json.dumps(doc), sorted(patched)


def patched_label(patched, limit=6):
    """[epochs] -> "11:35, 12:40" (with the date when they span days)."""
    days = {_ist(t).date() for t in patched}
    fmt = "%H:%M" if len(days) == 1 else "%d %b %H:%M"
    out = ", ".join(_ist(t).strftime(fmt) for t in patched[:limit])
    return out + (" ..." if len(patched) > limit else "")


# ---------------------------------------------------------------- command line

def main(argv=None):
    p = argparse.ArgumentParser(description="Kite candles for the trader-in-* tools")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, helptext in (("add", "store candles that fill Yahoo's missing bars"),
                           ("file", "write a whole chart file from Kite candles")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("symbol", help="NSE symbol, e.g. RELIANCE")
        s.add_argument("input", help="saved Kite historical answer (JSON), or - for stdin")
        s.add_argument("--interval", default="5m", help="5m (default) or 1m")
        s.add_argument("--fetched", type=int, help="UTC epoch the candles were fetched (default now)")
        s.add_argument("--out", default=CACHE_DIR, help="folder (default trader/bars)")
        if name == "file":
            s.add_argument("--prev-close", type=float, help="yesterday's close, for the %% move")
    a = p.parse_args(argv)
    sym = _clean(a.symbol)
    try:
        text = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8").read()
        try:
            kite = json.loads(text)
        except ValueError:
            raise KiteBarsError("%s is not JSON" % a.input)
        if a.cmd == "add":
            kept, skipped = add(kite, sym, a.interval, a.fetched, a.out)
            print("kept %d closed %s candle(s) from Kite for %s in %s%s" % (
                kept, a.interval, sym, a.out,
                "; left out %d still forming" % skipped if skipped else ""))
            return 0
        doc, missing = convert(kite, sym, a.interval, getattr(a, "prev_close", None), a.fetched)
    except (KiteBarsError, OSError) as e:
        print("kite_bars: %s" % e, file=sys.stderr)
        return 1
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, sym + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print("wrote %s: %d %s candles from Kite" % (path, len(doc["chart"]["result"][0]["timestamp"]), a.interval))
    if missing:
        print("WARNING: %d slot(s) have no candle: %s" % (len(missing), patched_label(missing, 10)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
