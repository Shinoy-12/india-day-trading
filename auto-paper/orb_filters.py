#!/usr/bin/env python3
"""Do the proposed auto-paper fixes help? Walk-forward ORB backtest on ~60 days of Yahoo 5-minute bars.

Rules match the auto-paper pipeline: 15-min opening range, entry when a 5-min bar closes above the
range high (09:30-15:00), stop at the range midpoint, target 2R, out by the 15:00 bar's close (15:05),
stop assumed first if a bar touches both. Zerodha intraday charges are subtracted. Results are in R
(one R = the planned loss at the stop), so position size does not matter.

  python3 backtest-2026-11/orb_filters.py            # fetch (cached) and print the comparison
"""
import csv, gzip, io, json, math, os, statistics as stt, sys, time, urllib.request, zipfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, "cache5m")
IST = timezone(timedelta(hours=5, minutes=30))
sys.path.insert(0, os.path.join(ROOT, "trader"))
from sectors import sector_index, INDEX_NAMES  # noqa: E402


def fetch(ticker):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, ticker.replace("^", "_") + ".json.gz")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 12 * 3600:
        return json.load(gzip.open(path, "rt"))
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=5m&range=60d" % ticker.replace("&", "%26")
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))
    r = r["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    days = {}
    for i, ts in enumerate(r.get("timestamp") or []):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        d = datetime.fromtimestamp(ts, IST)
        days.setdefault(d.date().isoformat(), []).append(
            [d.strftime("%H:%M"), q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i] or 0])
    json.dump(days, gzip.open(path, "wt"))
    time.sleep(0.2)
    return days


def top_symbols(n=50):
    t = os.path.join(ROOT, "trader")
    zips = sorted(f for f in os.listdir(os.path.join(t, "bhavcopy")) if f.endswith(".zip"))
    uni = {l.split("|")[0] for l in open(os.path.join(t, "universe.txt")) if l.strip()}
    with zipfile.ZipFile(os.path.join(t, "bhavcopy", zips[-1])) as z:
        rows = csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0])))
        eq = [(float(r["TtlTrfVal"] or 0), r["TckrSymb"]) for r in rows if r["SctySrs"] == "EQ" and r["TckrSymb"] in uni]
    return [s for _, s in sorted(eq, reverse=True)[:n]]


def charges_per_share(buy, sell):
    turn = buy + sell
    brokerage = min(20, 0.0003 * buy) + min(20, 0.0003 * sell)  # per order; per-share approx below
    exch = 0.0000297 * turn
    sebi = 0.000001 * turn
    return 0.00025 * sell + exch + sebi + 0.00003 * buy + 0.18 * (exch + sebi), brokerage


def index_state(days, day, hm):
    """(above its own opening-range midpoint at time hm, prior close above its 20-day average)."""
    bars = days.get(day)
    if not bars or len(bars) < 4:
        return None, None
    orb = bars[:3]
    mid = (max(b[2] for b in orb) + min(b[3] for b in orb)) / 2
    last = [b for b in bars if b[0] <= hm]
    above_mid = last[-1][4] > mid if last else None
    prior = sorted(d for d in days if d < day)
    closes = [days[d][-1][4] for d in prior]
    trend = closes[-1] > sum(closes[-20:]) / 20 if len(closes) >= 20 else None
    return above_mid, trend


def trades_for(sym, days, nifty, sectors, sec_ticker):
    out = []
    for day in sorted(days):
        bars = days[day]
        if len(bars) < 10 or bars[0][0] != "09:15":
            continue
        orb = bars[:3]
        hi, lo = max(b[2] for b in orb), min(b[3] for b in orb)
        mid = (hi + lo) / 2
        orvol = sum(b[5] for b in orb) / 3 or 1
        prev = sorted(d for d in days if d < day)
        gap = (bars[0][1] / days[prev[-1]][-1][4] - 1) * 100 if prev else 0.0
        for i in range(3, len(bars) - 1):
            hm = bars[i][0]
            if hm > "14:55":
                break
            if bars[i][4] <= hi:
                continue
            trig_close = bars[i][4]
            next_open = bars[i + 1][1]
            res = {"sym": sym, "day": day, "time": hm, "gap": gap, "volx": bars[i][5] / orvol,
                   "nifty_mid": index_state(nifty, day, hm)[0],
                   "sector_mid": None, "sector_trend": None}
            if sec_ticker:
                res["sector_mid"], res["sector_trend"] = index_state(sectors[sec_ticker], day, hm)
            for label, entry, start in (("close", trig_close, i + 1), ("next", next_open, i + 1)):
                risk = entry - mid
                if risk <= entry * 0.001:      # stop too tight / entry already below the stop
                    res[label] = None
                    continue
                target = entry + 2 * risk
                exit_px = None
                for b in bars[start:]:
                    if label == "next" and b is bars[start]:
                        pass                    # entered at this bar's open; its range still counts
                    if b[3] <= mid:
                        exit_px = mid; break
                    if b[2] >= target:
                        exit_px = target; break
                    if b[0] >= "15:00":
                        exit_px = b[4]; break
                if exit_px is None:
                    exit_px = bars[-1][4]
                c, _ = charges_per_share(entry, exit_px)
                qty = max(1, int(200 / risk))   # ~₹200 risk, for the flat ₹20 brokerage cap
                brok = (min(20, 0.0003 * entry * qty) + min(20, 0.0003 * exit_px * qty)) * 1.18 / qty
                res[label] = ((exit_px - entry) - c - brok) / risk
            out.append(res)
            break                               # first breakout of the day only
    return out


def summary(name, rs):
    rs = [r for r in rs if r is not None]
    if not rs:
        return "%-44s n=0" % name
    m = stt.mean(rs)
    se = stt.stdev(rs) / math.sqrt(len(rs)) if len(rs) > 1 else float("nan")
    win = sum(r > 0 for r in rs) / len(rs)
    return "%-44s n=%4d  avg %+.3fR  (±%.3f)  win %3.0f%%  total %+6.1fR" % (name, len(rs), m, se, 100 * win, sum(rs))


def main():
    syms = top_symbols()
    nifty = fetch("^NSEI")
    sec_tickers = {sector_index(s) for s in syms} - {None}
    sectors = {t: fetch(t) for t in sec_tickers}
    allt = []
    for s in syms:
        try:
            allt += trades_for(s, fetch(s + ".NS"), nifty, sectors, sector_index(s))
        except Exception as e:  # noqa: BLE001
            print("skip", s, e, file=sys.stderr)
    days = sorted({t["day"] for t in allt})
    print("ORB backtest: %d stocks (top 50 by turnover), %d sessions %s to %s, %d first-breakouts.\n"
          % (len(syms), len(days), days[0], days[-1], len(allt)))
    # walk-forward "history" edge per stock (what the time machine's history part measures), prior days only
    for t in allt:
        prior = [u["next"] for u in allt if u["sym"] == t["sym"] and u["day"] < t["day"] and u["next"] is not None]
        t["hist"] = stt.mean(prior) if len(prior) >= 5 else None
    R = lambda ts, k="next": [t[k] for t in ts]
    print("Fill price (fix 3 is about honesty, not a filter):")
    print(summary("  fill at the breakout bar's close (old)", R(allt, "close")))
    print(summary("  fill at the next bar's open (realistic)", R(allt)))
    print("\nFilters, all with realistic fills:")
    base = allt
    print(summary("  baseline (no filter)", R(base)))
    f1 = [t for t in base if t["nifty_mid"]]
    print(summary("  fix 1: Nifty above its opening-range mid", R(f1)))
    print(summary("        (the other side: Nifty below)", R([t for t in base if t["nifty_mid"] is False])))
    f2 = [t for t in base if t["volx"] >= 1.5]
    print(summary("  fix 2: breakout volume >= 1.5x range avg", R(f2)))
    print(summary("        (the other side: < 1.5x)", R([t for t in base if t["volx"] < 1.5])))
    h = [t for t in base if t["hist"] is not None]
    print(summary("  fix 4 universe: stocks with >=5 prior trades", R(h)))
    print(summary("  fix 4: prior avg R >= +0.05 (walk-forward)", R([t for t in h if t["hist"] >= 0.05])))
    print(summary("        (the other side: prior avg < +0.05)", R([t for t in h if t["hist"] < 0.05])))
    s1 = [t for t in base if t["sector_mid"]]
    print(summary("  sector: sector index above its OR mid", R(s1)))
    print(summary("        (the other side)", R([t for t in base if t["sector_mid"] is False])))
    s2 = [t for t in base if t["sector_trend"]]
    print(summary("  sector: sector above its 20-day average", R(s2)))
    print(summary("        (the other side)", R([t for t in base if t["sector_trend"] is False])))
    print(summary("  sector both (intraday + 20-day)", R([t for t in base if t["sector_mid"] and t["sector_trend"]])))
    print("\nCombinations:")
    print(summary("  fix 1 + fix 2", R([t for t in f1 if t["volx"] >= 1.5])))
    print(summary("  fix 1 + sector intraday", R([t for t in f1 if t["sector_mid"]])))
    print(summary("  fix 1 + fix 2 + sector intraday", R([t for t in f1 if t["volx"] >= 1.5 and t["sector_mid"]])))
    print("\nContext (not proposed fixes):")
    print(summary("  breakout before 10:30", R([t for t in base if t["time"] < "10:30"])))
    print(summary("  breakout 10:30 or later", R([t for t in base if t["time"] >= "10:30"])))
    print(summary("  gap up over 1%", R([t for t in base if t["gap"] > 1])))
    print(summary("  gap under 1%", R([t for t in base if t["gap"] <= 1])))
    json.dump(allt, open(os.path.join(HERE, "orb_filters_trades.json"), "w"))


if __name__ == "__main__":
    main()
