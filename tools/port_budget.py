"""One-off: budget (size.py) US -> NSE specifics, after port_common.py."""
import re, sys
p = sys.argv[1]; t = open(p).read()
def rep(a, b, c=1):
    global t
    assert t.count(a) == c, (t.count(a), a[:70]); t = t.replace(a, b)
s = t.index('"""Position sizing'); e = t.index('"""', s + 3) + 3
t = t[:s] + '''"""Position sizing for trader-in-budget (NSE). Standard library only, no network.
Ported from day-trader-skill's US budget manager (MIT).

Default mode: sizes ONE day trade from trader/plan.json (written by
trader-in-exit) to your budget and your max loss per trade, then writes one
bracket order (entry, stop-loss, take-profit) to trader/orders.json. The order
is broker-neutral; trader-in-broker turns it into Zerodha Kite tool inputs (an
MIS entry, then a GTT two-leg OCO for the stop and target once it fills; Zerodha
has no bracket orders). It never places anything: trader-in-risk checks the
order and trader-in-broker asks you yes or no.

    python3 size.py                                  # trader/plan.json + trader/config.json
    python3 size.py --write                          # write trader/orders.json
    python3 size.py --limit                          # a limit order at the plan's entry
    python3 size.py --limit 2443.50 --write          # a limit order at 2443.50
    python3 size.py --now "2026-11-23 10:15" --json  # pin the clock (India time)

How many shares. Whole shares only (NSE has no fractional shares).

    shares = floor of the smallest of
      max loss       max_loss_per_trade_inr / (risk per share + charges per share)
      position cap   budget x max_position_pct / entry
      max order      max_order_inr / entry
      cash           (budget minus the cash buffer) / entry, times the stock's
                     Zerodha MIS leverage when "allow_margin" is true
                     (and no more than the cash in trader/portfolio.json, if you have one)

Charges: with "include_charges" (default true) the max-loss limit counts the
round-trip Indian charges (brokerage, STT, exchange, SEBI, stamp duty, GST,
from market_in) on top of entry minus stop, so a stop-out costs no more than
your max loss. Product: "product" MIS (intraday, default) needs the stock on
Zerodha's MIS list; a stock that is not is refused.

The entry it sizes at: a limit order's limit price; for a market order the
plan's entry, or the price in trader/prices.json if that is fresh (under 15
minutes old) and higher, because a price that ran up since the plan means a
bigger loss at the same stop. Zero shares (the stop is too far away for your
max loss) is a plain refusal: no order is written. So is a reward:risk under
min_reward_risk (the price ran toward the target since the plan).

Weights mode (kept from v1, no longer the headline): split a budget across a
list of stocks by weight, as delivery (CNC) buys in whole shares.

    python3 size.py --weights RELIANCE=30,HDFCBANK=25,TCS=20,INFY=15,ITC=10 --prices trader/prices.json
    python3 size.py --targets my-weights.json --budget 100000 --write

  1. cash buffer   budget x cash_buffer_pct stays in cash, never invested
  2. weights       renormalised to 100 over the stocks you keep (blocked
                   tickers are dropped first; --top N keeps the N biggest)
  3. cap           no stock gets more than max_position_pct of the budget;
                   anything over the cap is shared out to the others by
                   weight, again and again until nobody is over
  4. min order     a slice under min_order_inr is dropped and its weight
                   shared out, so you never place a Rs 20 order
  5. rounding      whole rupees by default; the rounding rupee goes to the
                   biggest position that is not capped
  6. whole shares  always (Kite takes a quantity, not an amount); needs prices

Money that cannot be invested is reported as "left idle", never hidden.
"""''' + t[e:]
s = t.index("DEFAULTS = {"); e = t.index("}\n", s) + 2
t = t[:s] + '''DEFAULTS = {
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order_inr": 40000,
    "min_order_inr": 500,
    "max_loss_per_trade_inr": 500,
    "max_daily_loss_inr": 1500,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:30",
    "no_entries_after": "15:00",
    "flat_by": "15:05",
    "fractional": False,
    "broker": "kite",
    "paper": True,
    "exchange": "NSE",
    "product": "MIS",
    "weights_product": "CNC",
    "include_charges": True,
    "stop_limit_buffer_pct": 0.5,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
}
''' + t[e:]
t = t.replace("_usd", "_inr").replace('"usd": ', '"inr": ')
rep('''def round_cent(x):
    """Round a price to the cent (half up)."""
    return math.floor(float(x) * 100 + 0.5 + EPS) / 100.0''',
'''TICK = None  # the plan's tick (float); else market_in's price band


def round_cent(x):
    """Round a price to the NSE tick, half up (the name is kept from the US version)."""
    tk = TICK or float(market_in.tick_size(x))
    return round(math.floor(float(x) / tk + 0.5 + EPS) * tk, 2)


def floor_tick(x):
    tk = TICK or float(market_in.tick_size(x))
    return round(math.floor(float(x) / tk + EPS) * tk, 2)


def charges_per_share(entry, exit_price, qty, exchange="NSE"):
    """Round-trip Indian charges per share for qty shares (market_in's rates)."""
    if qty <= 0:
        qty = 1
    return float(market_in.round_trip_costs(entry, exit_price, qty, exchange)["total"]) / qty''')
rep('''    """358.32 -> "358.32": Alpaca wants prices as strings."""''', '''    """2419.30 -> "2419.30": prices are strings in trader/orders.json."""''')
rep('''    """1250 -> "1250", 1118.13 -> "1118.13" (Alpaca wants these as strings)."""''', '''    """1250 -> "1250", 1118.13 -> "1118.13" (strings in trader/orders.json)."""''')
rep('''def money(x):
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return "$" + "{:,.0f}".format(round(x))
    return "$" + "{:,.2f}".format(x)''', '''def money(x):
    x = float(x)
    if abs(x - round(x)) < 0.005:
        return "\\u20b9" + "{:,.0f}".format(round(x))
    return "\\u20b9" + "{:,.2f}".format(x)''')
rep('''    sym = str(plan.get("symbol") or "").strip().upper()
    if not sym:
        raise SizeError("the plan has no symbol (run trader-exit)")''',
'''    global TICK
    sym = market_in.kite_symbol(str(plan.get("symbol") or "").strip())[1]
    if not sym:
        raise SizeError("the plan has no symbol (run trader-in-exit)")
    TICK = _f(plan.get("tick"))''')
rep('''    blocked = {str(b).upper() for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)
''', '''    blocked = {str(b).upper() for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)
    product = str(c.get("product") or "MIS").upper()
    exchange = str(c.get("exchange") or "NSE").upper()
    lev = market_in.mis_leverage(sym)
    if product == "MIS" and lev is None:
        raise SizeError("%s is not on Zerodha's MIS list (shared/zerodha_mis_margins.json), so it cannot be "
                        "traded intraday: skip it, or refresh the list with refresh_data.py" % sym)
''')
rep('''    risk_c = int(round((ref - stop) * 100))
    reward_c = int(round((target - ref) * 100))
    risk = risk_c / 100.0
''', '''    risk_c = int(round((ref - stop) * 100))
    reward_c = int(round((target - ref) * 100))
    risk = risk_c / 100.0
    with_charges = bool(c.get("include_charges", True))
''')
rep('''    available = max(round(available, 2), 0.0)
''', '''    available = max(round(available, 2), 0.0)
    if c.get("allow_margin") and product == "MIS" and lev and float(lev) > 1:
        cash_note += ", x %s MIS leverage" % _num(float(lev))
        available = round(available * float(lev), 2)
''')
rep('''    max_loss = _f(c.get("max_loss_per_trade_inr"))
    if max_loss:
        limits.append({"name": "max loss", "inr": max_loss, "per": risk, "shares": shares_for(max_loss, risk),
                       "how": "%s max loss / %s risk a share" % (money(max_loss), _price(risk))})''',
'''    max_loss = _f(c.get("max_loss_per_trade_inr"))
    cps = 0.0
    if max_loss:
        q = shares_for(max_loss, risk)
        if with_charges:  # charges depend on the size: settle on a size whose loss + charges fit
            for _ in range(6):
                cps = charges_per_share(ref, stop, max(q, 1), exchange)
                q2 = shares_for(max_loss, risk + cps)
                if q2 == q:
                    break
                q = q2
            while q > 0 and q * risk + charges_per_share(ref, stop, q, exchange) * q > max_loss + 0.005:
                q -= 1
            cps = charges_per_share(ref, stop, max(q, 1), exchange)
        limits.append({"name": "max loss", "inr": max_loss, "per": round(risk + cps, 2), "shares": q,
                       "how": ("%s max loss / (%s risk + %s charges) a share" % (money(max_loss), _price(risk), _price(cps))
                               if with_charges else "%s max loss / %s risk a share" % (money(max_loss), _price(risk)))})''')
rep('''    cost = round(qty * ref, 2)
    loss = round(qty * risk_c / 100.0, 2)''', '''    cost = round(qty * ref, 2)
    charges = round(charges_per_share(ref, stop, qty, exchange) * qty, 2) if qty else 0.0
    loss = round(qty * risk_c / 100.0 + (charges if with_charges else 0.0), 2)''')
rep('''            refusal = ("one share risks %s (entry %s minus stop %s), more than your %s max loss per trade. "
                       "No order. Skip this trade, or plan a closer stop with trader-exit."''',
'''            refusal = ("one share risks %s (entry %s minus stop %s, plus charges), more than your %s max loss per "
                       "trade. No order. Skip this trade, or plan a closer stop with trader-in-exit."''')
t = t.replace("trader-exit", "trader-in-exit").replace("trader-in-in-exit", "trader-in-exit")
rep('''        "cost": cost, "max_loss": loss, "flat_by": plan.get("flat_by") or c.get("flat_by"),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
    }''', '''        "cost": cost, "max_loss": loss, "charges": charges, "include_charges": with_charges,
        "flat_by": plan.get("flat_by") or c.get("flat_by"), "fno": market_in.is_fno(sym),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
        "product": product, "exchange": exchange, "mis_leverage": float(lev) if lev else None,
        "tick": TICK or float(market_in.tick_size(ref)),
        "stop_limit_buffer_pct": float(c.get("stop_limit_buffer_pct") or 0),
    }''')
rep('''    """The one proposed order, Alpaca place_stock_order fields (strings) plus why and plan."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    o = {"symbol": s["symbol"], "side": "buy", "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day"}''',
'''    """The one proposed order: broker-neutral fields (strings) plus why and plan.
    market_in.kite_entry / kite_exit_gtt turn it into Kite tool inputs."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    o = {"symbol": s["symbol"], "side": "buy", "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day", "exchange": s["exchange"], "product": s["product"]}''')
rep('''    why = ("%s on %s: %d shares, bound by your %s (%d x %s = %s at the stop)"''',
    '''    why = ("%s on %s: %d shares, bound by your %s (%d x %s%s = %s at the stop)"''')
rep('''              s["qty"], _price(s["risk_per_share"]), money(s["max_loss"])))
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _price(s["target"]),
        "stop_loss_stop_price": _price(s["stop"]),
        "why": why,
        "plan": {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"], "setup": s["setup"],
                 "entry_time": s["entry_time"], "flat_by": s["flat_by"]},
    })''',
'''              s["qty"], _price(s["risk_per_share"]), " + charges" if s["include_charges"] else "", money(s["max_loss"])))
    stop_limit = floor_tick(s["stop"] * (1 - s["stop_limit_buffer_pct"] / 100.0))
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _price(s["target"]),
        "stop_loss_stop_price": _price(s["stop"]),
        "stop_loss_limit_price": _price(stop_limit),
        "tick": s["tick"],
        "why": why,
        "plan": {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"], "charges": s["charges"],
                 "setup": s["setup"], "entry_time": s["entry_time"], "flat_by": s["flat_by"], "fno": s["fno"]},
    })''')
rep('''    lines.append("Size: %d shares of %s = %s at %s. Max loss at the stop: %d x %s = %s."
                 % (s["qty"], s["symbol"], money(s["cost"]), _price(s["entry"]), s["qty"],
                    _price(s["risk_per_share"]), money(s["max_loss"])))''',
'''    lines.append("Size: %d shares of %s = %s at %s (%s, %s). Max loss at the stop: %d x %s%s = %s."
                 % (s["qty"], s["symbol"], money(s["cost"]), _price(s["entry"]), s["product"], s["exchange"],
                    s["qty"], _price(s["risk_per_share"]),
                    (" + %s charges" % money(s["charges"])) if s["include_charges"] else "", money(s["max_loss"])))''')
rep('''    lines.append("Proposed bracket order (place_stock_order arguments, nothing has been placed):")
    how = "limit %s" % order["limit_price"] if order["type"] == "limit" else "market"
    lines.append("  buy %s %s, %s, day, take-profit %s, stop-loss %s"
                 % (order["qty"], order["symbol"], how, order["take_profit_limit_price"],
                    order["stop_loss_stop_price"]))''',
'''    lines.append("Proposed bracket order (nothing has been placed):")
    how = "limit %s" % order["limit_price"] if order["type"] == "limit" else "market"
    lines.append("  entry   buy %s %s on %s, %s, %s, day" % (order["qty"], order["symbol"], order["exchange"],
                                                             order["product"], how))
    lines.append("  exits   once filled, one GTT OCO: stop-loss trigger %s (limit %s), take-profit %s"
                 % (order["stop_loss_stop_price"], order["stop_loss_limit_price"], order["take_profit_limit_price"]))''')
rep('''        lines.append("Flat by %s India: anything still open then gets closed (trader-alerts rings, "
                     "trader-broker flatten)." % s["flat_by"])''',
'''        lines.append("Flat by %s IST: anything still open then gets closed (trader-in-alerts rings, "
                     "trader-in-broker flatten), before Zerodha's MIS square-off at %s%s."
                     % (s["flat_by"], market_in.square_off_time(s["fno"]).strftime("%H:%M"),
                        " (F&O stock)" if s["fno"] else ""))''')
for a, b in (("trader-risk", "trader-in-risk"), ("trader-broker", "trader-in-broker"), ("trader-alerts", "trader-in-alerts")):
    t = t.replace(a, b)
rep('''    if whole is None:
        whole = not cfg.get("fractional", True)''', '''    whole = True  # Kite takes a quantity: NSE has no fractional shares or notional orders''')
rep('''        o = {"symbol": p["ticker"], "side": "buy"}
        if result["whole_shares"]:
            o["qty"] = str(int(p["shares"]))
        else:
            o["notional"] = _num(p["dollars"])
        o.update({"type": "market", "time_in_force": "day", "why": why})''',
'''        if not p.get("shares"):
            continue
        o = {"symbol": p["ticker"], "side": "buy", "qty": str(int(p["shares"])),
             "exchange": result.get("exchange", "NSE"), "product": result.get("product", "CNC")}
        o.update({"type": "market", "time_in_force": "day", "why": why})''')
rep('''        "min_order_inr": min_order, "whole_shares": bool(whole),''', '''        "min_order_inr": min_order, "whole_shares": bool(whole),
        "exchange": str(cfg.get("exchange") or "NSE"), "product": str(cfg.get("weights_product") or "CNC"),''')
rep('''    lines.append("Proposed orders (place_stock_order arguments, nothing has been placed):")
    for o in orders:
        amount = ("notional \\"%s\\"" % o["notional"]) if "notional" in o else ("qty \\"%s\\"" % o["qty"])
        lines.append("  %s %s %s, %s, %s" % (o["side"], o["symbol"], amount, o["type"], o["time_in_force"]))''',
'''    lines.append("Proposed orders (nothing has been placed):")
    for o in orders:
        lines.append("  %s %s %s on %s, %s, %s, %s" % (o["side"], o["qty"], o["symbol"], o["exchange"], o["product"],
                                                     o["type"], o["time_in_force"]))''')
t = t.replace('''    sym = str((plan or {}).get("symbol") or "").upper()''', '''    sym = market_in.kite_symbol(str((plan or {}).get("symbol") or ""))[1]''')
t = t.replace('''raise SizeError("--limit wants a price, like --limit 364.00")''', '''raise SizeError("--limit wants a price, like --limit 2443.50")''')
t = t.replace('''description="Size a day trade to your budget and max loss (trader-budget)."''', '''description="Size a day trade to your budget and max loss (trader-in-budget, NSE)."''')
t = t.replace('2026-10-19 10:15', '2026-11-23 10:15')
t = t.replace('''help="inline weights: AAPL=22.04,AXP=17.14"''', '''help="inline weights: RELIANCE=30,HDFCBANK=25"''')
t = t.replace('''help="whole shares only (needs --prices)"''', '''help="whole shares (always on for NSE; kept for compatibility)"''')
t = t.replace('''help="size to the cent instead of whole dollars"''', '''help="size slices to the paisa instead of whole rupees"''')
t = re.sub(r"\bdollars\b", "rupees", t)
t = t.replace('$%', '₹%').replace("($%s)", "(₹%s)")
open(p, "w").write(t); print("budget patched")
