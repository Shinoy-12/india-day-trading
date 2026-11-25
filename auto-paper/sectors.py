"""Which sector a stock is in, which Nifty sector index tracks it, and whether that sector is rising.

Sector = the 'Industry' column of NSE's Nifty 500 list (nsearchives, refreshed weekly into trader/cache).
Banks are matched to Nifty Bank via NSE's Nifty Bank list. Index bars come from Yahoo.
"""
import csv, json, os, time, urllib.request
from datetime import datetime, timedelta, timezone

T = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(T, "cache")
IST = timezone(timedelta(hours=5, minutes=30))
LISTS = {"nifty500": "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
         "niftybank": "https://nsearchives.nseindia.com/content/indices/ind_niftybanklist.csv"}

INDUSTRY_INDEX = {
    "Financial Services": "NIFTY_FIN_SERVICE.NS",
    "Information Technology": "^CNXIT",
    "Automobile and Auto Components": "^CNXAUTO",
    "Healthcare": "NIFTY_HEALTHCARE.NS",
    "Fast Moving Consumer Goods": "^CNXFMCG",
    "Metals & Mining": "^CNXMETAL",
    "Oil Gas & Consumable Fuels": "NIFTY_OIL_AND_GAS.NS",
    "Power": "^CNXENERGY",
    "Realty": "^CNXREALTY",
    "Capital Goods": "^CNXINFRA",
    "Construction": "^CNXINFRA",
    "Construction Materials": "^CNXINFRA",
    "Chemicals": "NIFTY_CHEMICALS.NS",
    "Media Entertainment & Publication": "^CNXMEDIA",
    "Consumer Services": "^CNXCONSUM",
    "Consumer Durables": "^CNXCONSUM",
    "Textiles": "^CNXCONSUM",
    "Telecommunication": "^CNXSERVICE",
    "Services": "^CNXSERVICE",
    "Diversified": "^CNXCMDT",
    "Forest Materials": "^CNXCMDT",
}
INDEX_NAMES = {"^NSEBANK": "Nifty Bank", "NIFTY_FIN_SERVICE.NS": "Nifty Financial Services", "^CNXIT": "Nifty IT",
               "^CNXAUTO": "Nifty Auto", "NIFTY_HEALTHCARE.NS": "Nifty Healthcare", "^CNXFMCG": "Nifty FMCG",
               "^CNXMETAL": "Nifty Metal", "NIFTY_OIL_AND_GAS.NS": "Nifty Oil & Gas", "^CNXENERGY": "Nifty Energy",
               "^CNXREALTY": "Nifty Realty", "^CNXINFRA": "Nifty Infrastructure", "NIFTY_CHEMICALS.NS": "Nifty Chemicals",
               "^CNXMEDIA": "Nifty Media", "^CNXCONSUM": "Nifty Consumption", "^CNXSERVICE": "Nifty Services",
               "^CNXCMDT": "Nifty Commodities", "^NSEI": "Nifty 50"}


def _list(name):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name + ".csv")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > 7 * 86400:
        try:
            req = urllib.request.Request(LISTS[name], headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=30).read()
            open(path, "wb").write(data)
        except OSError:
            if not os.path.exists(path):
                return []
    return list(csv.DictReader(open(path, encoding="utf-8-sig")))


_ind, _banks = None, None


def industry(sym):
    global _ind
    if _ind is None:
        _ind = {r["Symbol"].strip(): r["Industry"].strip() for r in _list("nifty500")}
    return _ind.get(sym)


def sector_index(sym):
    global _banks
    if _banks is None:
        _banks = {r["Symbol"].strip() for r in _list("niftybank")}
    if sym in _banks:
        return "^NSEBANK"
    return INDUSTRY_INDEX.get(industry(sym) or "")


def _bars(ticker, rng="5d"):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=5m&range=%s" % (ticker, rng)
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20))
    r = r["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    days = {}
    for i, ts in enumerate(r.get("timestamp") or []):
        if None in (q["high"][i], q["low"][i], q["close"][i]):
            continue
        d = datetime.fromtimestamp(ts, IST)
        days.setdefault(d.date().isoformat(), []).append((d, q["high"][i], q["low"][i], q["close"][i]))
    return days


def index_now(ticker, now):
    """Today's state of an index at `now`: dict with above_or_mid, pct_today, or None if no data."""
    days = _bars(ticker)
    day = now.date().isoformat()
    bars = [b for b in days.get(day, []) if b[0] + timedelta(minutes=5) <= now]
    if len(bars) < 4:
        return None
    hi, lo = max(b[1] for b in bars[:3]), min(b[2] for b in bars[:3])
    prev = [d for d in sorted(days) if d < day]
    prev_close = days[prev[-1]][-1][3] if prev else None
    return {"ticker": ticker, "name": INDEX_NAMES.get(ticker, ticker), "last": bars[-1][3],
            "or_mid": (hi + lo) / 2, "above_or_mid": bars[-1][3] > (hi + lo) / 2,
            "pct_today": (bars[-1][3] / prev_close - 1) * 100 if prev_close else None}


def trend_20d(ticker, today):
    """True if the index's last close before `today` is above its 20-day average of daily closes."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=1d&range=3mo" % ticker
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20))
    r = r["chart"]["result"][0]
    closes = [c for ts, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0]["close"])
              if c is not None and datetime.fromtimestamp(ts, IST).date() < today]
    if len(closes) < 20:
        return None
    return closes[-1] > sum(closes[-20:]) / 20


def sector_check(sym, now):
    """The sector filter: the stock's sector index above its opening-range mid today AND above its
    20-day average. Returns (ok, text)."""
    t = sector_index(sym)
    if not t:
        return True, "%s: no sector index (not in Nifty 500), not filtered" % sym
    try:
        s, tr = index_now(t, now), trend_20d(t, now.date())
    except Exception as e:  # noqa: BLE001
        return True, "%s: sector data failed (%s), not filtered" % (sym, str(e)[:60])
    if s is None or tr is None:
        return True, "%s: %s has too little data, not filtered" % (sym, INDEX_NAMES.get(t, t))
    ok = s["above_or_mid"] and tr
    return ok, "%s (%s, %s %+.2f%% today, %s its range mid, %s its 20-day avg)" % (
        sym, industry(sym), INDEX_NAMES.get(t, t), s["pct_today"] or 0,
        "above" if s["above_or_mid"] else "below", "above" if tr else "below")


def sector_board(now, tickers=None):
    """Every sector index's move today, strongest first (for the morning/close report)."""
    out = []
    for t in tickers or sorted(set(INDUSTRY_INDEX.values()) | {"^NSEBANK"}):
        try:
            s = index_now(t, now)
        except Exception:  # noqa: BLE001
            s = None
        if s and s["pct_today"] is not None:
            out.append(s)
    return sorted(out, key=lambda s: -s["pct_today"])
