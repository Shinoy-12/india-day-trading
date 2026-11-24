"""market_in: the Indian (NSE) market facts every trader-in-* skill shares.

Replaces the per-script copies of the NYSE clock, holiday list, cent rounding
and Yahoo symbol mapping in the US day-trader-skill. Standard library only.

Numbers that SEBI, NSE or brokers change live in india_rules.json and
nse_holidays.json, not here. Run `python3 market_in.py check` to see which
blocks are still unverified.
"""

import datetime
import json
import os
import sys
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "india_rules.json")
HOLIDAYS_PATH = os.path.join(HERE, "nse_holidays.json")
IST_OFFSET = datetime.timedelta(hours=5, minutes=30)  # India has no DST


class MarketError(Exception):
    pass


def _load(path):
    with open(path) as f:
        return json.load(f)


RULES = _load(RULES_PATH)
_HOL = _load(HOLIDAYS_PATH)
HOLIDAYS = _HOL.get("holidays", {})
SPECIAL = _HOL.get("special_sessions", {})


def _t(text):
    h, m = str(text).split(":")
    return datetime.time(int(h), int(m))


S = RULES["session"]
OPEN, CLOSE, PRE_OPEN = _t(S["open"]), _t(S["close"]), _t(S["pre_open"])
FLAT_BY, SQUARE_OFF = _t(S["default_flat_by"]), _t(S["broker_square_off"])
# F&O stocks are in SEBI's Closing Auction Session: continuous trading ends earlier.
CAS = S.get("cas", {})
CAS_CLOSE = _t(CAS["continuous_close"]) if CAS else CLOSE
CAS_SQUARE_OFF = _t(CAS["broker_square_off"]) if CAS else SQUARE_OFF


def square_off_time(fno_stock=False):
    """Broker's MIS auto square-off; no new MIS orders after it."""
    return CAS_SQUARE_OFF if fno_stock else SQUARE_OFF


# ---------------------------------------------------------------- clock

def now_ist():
    """Naive datetime in India time."""
    if ZoneInfo:
        return datetime.datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
    return datetime.datetime.utcnow() + IST_OFFSET


def _year_known(d):
    y = str(d.year)
    return any(k.startswith(y) for k in HOLIDAYS) or any(k.startswith(y) for k in SPECIAL)


def trading_day(d):
    """(is_trading_day, reason). Raises MarketError for a year with no holiday list."""
    key = d.isoformat()
    if key in SPECIAL:
        return True, "special session: " + SPECIAL[key].get("name", "")
    if d.weekday() >= 5:
        return False, "weekend"
    if not _year_known(d):
        raise MarketError("no NSE holiday list for %d in nse_holidays.json; add it from NSE's "
                          "official list before trusting the clock" % d.year)
    name = HOLIDAYS.get(key)
    if name:
        return False, "NSE holiday: " + name
    return True, ""


def session(d, fno_stock=False):
    """(open_time, close_time) of continuous trading in India time, or None if closed.
    fno_stock=True: F&O stocks stop continuous trading at the closing-auction start."""
    ok, _ = trading_day(d)
    if not ok:
        return None
    sp = SPECIAL.get(d.isoformat())
    if sp:
        return _t(sp["open"]), _t(sp["close"])
    return OPEN, (CAS_CLOSE if fno_stock else CLOSE)


def next_open(d):
    nd = d + datetime.timedelta(days=1)
    for _ in range(15):
        s = session(nd)
        if s:
            return "%s %02d:%02d" % (nd.isoformat(), s[0].hour, s[0].minute)
        nd += datetime.timedelta(days=1)
    return None


def is_open(dt=None, fno_stock=False):
    dt = dt or now_ist()
    s = session(dt.date(), fno_stock)
    return bool(s) and s[0] <= dt.time() < s[1]


# ---------------------------------------------------------------- prices

def tick_size(price, tick=None):
    """The stock's own tick (pass Kite's instrument tick_size) or, failing that,
    an approximate price-band fallback, which can be wrong near band edges."""
    if tick:
        return Decimal(str(tick))
    price = Decimal(str(price))
    for upper, tick in RULES["tick_bands"]["bands"]:
        if upper is None or price < Decimal(str(upper)):
            return Decimal(tick)
    raise MarketError("no tick band for %s" % price)


def _to_tick(price, rounding, tick=None):
    tick = tick_size(price, tick)
    return (Decimal(str(price)) / tick).to_integral_value(rounding=rounding) * tick


def floor_tick(price, tick=None):
    """Round down to a valid NSE price (use for long stops)."""
    return _to_tick(price, ROUND_DOWN, tick)


def ceil_tick(price, tick=None):
    """Round up to a valid NSE price (use for long entries' trigger)."""
    return _to_tick(price, ROUND_UP, tick)


def rupees(x):
    return "₹{:,.2f}".format(Decimal(str(x)))


# ---------------------------------------------------------------- symbols

def yahoo_symbol(sym, exchange="NSE"):
    """RELIANCE -> RELIANCE.NS (BSE: .BO). Leaves an existing suffix alone."""
    s = sym.strip().upper()
    if s.endswith((".NS", ".BO")) or s.startswith("^"):
        return s
    return s + (".BO" if exchange.upper() == "BSE" else ".NS")


def kite_symbol(sym):
    """RELIANCE.NS -> ('NSE', 'RELIANCE') for Kite's exchange + tradingsymbol."""
    s = sym.strip().upper()
    if s.endswith(".BO"):
        return "BSE", s[:-3]
    if s.endswith(".NS"):
        s = s[:-3]
    return "NSE", s


# ---------------------------------------------------------------- costs

def round_trip_costs(entry, exit_, qty, exchange="NSE"):
    """Estimated rupee costs of one intraday buy-then-sell, per india_rules.json."""
    c = {k: Decimal(v) for k, v in RULES["costs_intraday_equity"].items()
         if k not in ("verified", "source")}
    if exchange.upper() == "BSE":
        c["exchange_txn_pct"] = c["exchange_txn_pct_bse"]
    q = Decimal(qty)
    buy, sell = Decimal(str(entry)) * q, Decimal(str(exit_)) * q
    pct = lambda base, p: base * p / 100
    brokerage = (min(pct(buy, c["brokerage_pct"]), c["brokerage_cap"])
                 + min(pct(sell, c["brokerage_pct"]), c["brokerage_cap"]))
    stt = pct(sell, c["stt_sell_pct"])
    txn = pct(buy + sell, c["exchange_txn_pct"])
    sebi = (buy + sell) * c["sebi_per_crore"] / Decimal(10 ** 7)
    stamp = pct(buy, c["stamp_buy_pct"])
    gst = pct(brokerage + txn + sebi, c["gst_pct"])
    parts = dict(brokerage=brokerage, stt=stt, exchange=txn, sebi=sebi, stamp=stamp, gst=gst)
    parts = {k: v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for k, v in parts.items()}
    parts["total"] = sum(parts.values())
    return parts


# ---------------------------------------------------------------- MIS

_MIS = None


def mis_leverage(sym):
    """Zerodha MIS leverage for a stock as Decimal, or None if MIS isn't allowed."""
    global _MIS
    if _MIS is None:
        path = os.path.join(HERE, RULES["intraday_leverage"].get("per_stock_file", ""))
        _MIS = _load(path)["stocks"] if os.path.isfile(path) else {}
    row = _MIS.get(kite_symbol(sym)[1])
    return Decimal(row["leverage"]) if row else None


_FNO = None


def is_fno(sym):
    """True if the stock has F&O contracts, so it is in the closing auction (continuous
    trading ends at CAS_CLOSE). From nse_fno_stocks.json (refresh_data.py fno)."""
    global _FNO
    if _FNO is None:
        path = os.path.join(HERE, "nse_fno_stocks.json")
        _FNO = set(_load(path)["stocks"]) if os.path.isfile(path) else set()
    return kite_symbol(sym)[1] in _FNO


# ---------------------------------------------------------------- Kite order shapes
# trader/orders.json keeps broker-neutral fields (symbol, side, qty, type,
# limit_price, take_profit_limit_price, stop_loss_stop_price, product, exchange);
# these two functions turn one order into the exact inputs of the Kite MCP tools,
# so trader-in-risk and trader-in-broker build them the same way.

def _num(x):
    return None if x in (None, "") else float(x)


def kite_entry(order):
    """The entry: Kite `orders` tool, mode=place."""
    typ = str(order.get("type") or "market").upper()
    p = {"mode": "place", "variety": "regular", "exchange": order.get("exchange") or "NSE",
         "tradingsymbol": kite_symbol(order["symbol"])[1],
         "transaction_type": str(order.get("side") or "buy").upper(),
         "quantity": int(float(order["qty"])), "product": order.get("product") or "MIS",
         "order_type": typ, "validity": "DAY"}
    if typ in ("LIMIT", "SL"):
        p["price"] = _num(order.get("limit_price"))
    if typ in ("SL", "SL-M"):
        p["trigger_price"] = _num(order.get("stop_price"))
    return p


def kite_exit_gtt(order, last_price=None):
    """A bracket's exits: Kite `gtt` tool, mode=place, two-leg OCO (stop below,
    target above; whichever triggers first cancels the other). Placed once the
    entry has filled. The stop leg is a limit order a little under the trigger
    (stop_loss_limit_price) so a fast market still fills it."""
    if order.get("order_class") != "bracket":
        return None
    qty = int(float(order["qty"]))
    stop = _num(order["stop_loss_stop_price"])
    return {"mode": "place", "trigger_type": "two-leg", "exchange": order.get("exchange") or "NSE",
            "tradingsymbol": kite_symbol(order["symbol"])[1], "transaction_type": "SELL",
            "product": order.get("product") or "MIS",
            "last_price": _num(last_price if last_price is not None else
                               (order.get("limit_price") or (order.get("plan") or {}).get("entry"))),
            "lower_trigger_value": stop,
            "lower_limit_price": _num(order.get("stop_loss_limit_price") or stop),
            "lower_quantity": qty,
            "upper_trigger_value": _num(order["take_profit_limit_price"]),
            "upper_limit_price": _num(order["take_profit_limit_price"]),
            "upper_quantity": qty}


# ---------------------------------------------------------------- checks

def unverified():
    return [k for k, v in RULES.items() if isinstance(v, dict) and v.get("verified") is None]


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        bad = unverified()
        print("unverified rule blocks: " + (", ".join(bad) if bad else "none"))
        years = sorted({k[:4] for k in HOLIDAYS})
        print("holiday years loaded: " + (", ".join(years) if years else "none"))
        try:
            mis = _load(os.path.join(HERE, RULES["intraday_leverage"]["per_stock_file"]))
            print("MIS margin list: %d stocks, updated %s" % (len(mis["stocks"]), mis.get("_last_updated")))
        except (OSError, KeyError):
            print("MIS margin list: missing")
        sys.exit(1 if bad or not years else 0)
    print(__doc__)
