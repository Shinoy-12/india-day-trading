"""One-off: risk (check.py) US -> NSE specifics, after port_common.py."""
import re, sys
p = sys.argv[1]; t = open(p).read()
t = t.replace("_u" + "sd", "_inr")  # every *_usd name and key -> *_inr first
def rep(a, b, c=1):
    global t
    assert t.count(a) == c, (t.count(a), a[:80]); t = t.replace(a, b)
def cut(name):
    global t
    m = re.search(r"^def %s\(.*?(?=^\S)" % name, t, re.S | re.M); assert m, name
    t = t[:m.start()] + t[m.end():]

# ---- docstring rules
rep('"""Pre-trade risk check for trader-risk. Standard library only, no network.',
    '"""Pre-trade risk check for trader-in-risk (NSE, Zerodha). Standard library only, no network.\nPorted from day-trader-skill\'s US risk manager (MIT).')
rep('''    python3 check.py --now "2026-10-19 10:15"        # pin the clock (India time)''',
    '''    python3 check.py --now "2026-11-23 10:15"        # pin the clock (India time)''')
s = t.index("What blocks an order (every order):"); e = t.index("Exit code 0 when every order passes")
t = t[:s] + '''What blocks an order (every order):

  format        missing symbol or side, no whole-share qty (NSE has no
                fractional shares or amount orders), an unknown type (market,
                limit, stop = SL-M, stop_limit = SL) or time_in_force (day,
                ioc), a limit order without a limit price, a product other than
                MIS / CNC, an exchange other than NSE / BSE, a price off the
                stock's tick; a bracket that misses a leg
  asset         F&O contracts (options CE/PE, futures FUT) unless
                "allow_options": true; anything that is not an NSE/BSE symbol
  short         selling more than you hold, unless "allow_short": true

What blocks an entry (on top):

  blocked       a ticker on your "blocked" list
  mis           product MIS on a stock Zerodha does not allow for intraday
                (not in shared/zerodha_mis_margins.json)
  size          under min_order_inr, over max_order_inr
  position      the stock would be over max_position_pct of the account
  cash          the buy would dip into your cash buffer, or need margin; with
                "allow_margin": true an MIS buy may use the stock's Zerodha
                MIS leverage
  duplicate     the same symbol and side twice in this batch, or already
                placed today (trader/state/broker.json)
  daily limit   max_orders_per_day orders placed today
  stop          no stop while "require_stop": true (a bracket stop_loss_stop_price
                or the order's plan stop); a stop on the wrong side of the entry
  loss          qty x (entry - stop), plus the round-trip Indian charges when
                "include_charges" is true, over max_loss_per_trade_inr. The
                entry is the limit price for a limit order, else the HIGHER of
                the plan's entry and a fresh price (under 15 minutes old), so a
                stale plan cannot understate the risk
  reward:risk   (target - entry) / (entry - stop) under min_reward_risk
  daily loss    the max losses at the stops of today's entries plus this one
                over max_daily_loss_inr (win or lose, each counts in full)
  trades        max_trades_per_day entries already placed today
  window        before no_entries_before or after no_entries_after (India
                time), the market is closed (weekend, NSE holiday, outside
                9:15 to 15:30), an F&O stock after 15:15 (closing auction), or
                an MIS entry at or after Zerodha's auto square-off (15:25,
                15:12 for F&O stocks)
  circuit       when trader/prices.json carries the stock's circuit limits
                (detail.SYM.upper_circuit / lower_circuit, e.g. from Kite): a
                buy within 1% of the upper circuit (it can lock, and a stop
                below may never fill) or a stop under the lower circuit

''' + t[e:]
t = t.replace("so trader-broker only shows", "so trader-in-broker only shows")
s = t.index("DEFAULTS = {"); e = t.index("}\n", s) + 2
t = t[:s] + '''DEFAULTS = {
    "budget": None, "cash_buffer_pct": 10, "max_position_pct": 75, "max_order_inr": 40000,
    "min_order_inr": 500, "max_loss_per_trade_inr": 500, "max_daily_loss_inr": 1500, "max_trades_per_day": 3,
    "max_orders_per_day": 10, "min_reward_risk": 1.0, "require_stop": True,
    "no_entries_before": "09:30", "no_entries_after": "15:00", "flat_by": "15:05",
    "paper": True, "blocked": [], "allow_options": False, "allow_margin": False, "allow_short": False,
    "include_charges": True, "product": "MIS", "exchange": "NSE",
}
''' + t[e:]
rep('''ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions")
PRICE_FIELDS = ("qty", "notional", "limit_price", "stop_price", "take_profit_limit_price",
                "stop_loss_stop_price", "stop_loss_limit_price")
TYPES = {"market", "limit", "stop", "stop_limit", "trailing_stop"}
TIFS = {"day", "gtc", "opg", "cls", "ioc", "fok"}
OCC = re.compile(r"^[A-Z]{1,6}\\d{6}[CP]\\d{8}$")
TICKER = re.compile(r"^[A-Z]{1,5}([.\\-][A-Z]{1,2})?$")''',
'''# The fields that define an order (same tuple in trader-in-broker/ticket.py: the fingerprint).
ORDER_FIELDS = ("symbol", "side", "qty", "type", "time_in_force", "limit_price", "stop_price",
                "exchange", "product", "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                "stop_loss_limit_price")
PRICE_FIELDS = ("qty", "limit_price", "stop_price", "take_profit_limit_price",
                "stop_loss_stop_price", "stop_loss_limit_price")
TICK_FIELDS = ("limit_price", "stop_price", "take_profit_limit_price", "stop_loss_stop_price",
               "stop_loss_limit_price")
TYPES = {"market", "limit", "stop", "stop_limit"}   # Kite: MARKET, LIMIT, SL-M, SL
TIFS = {"day", "ioc"}
PRODUCTS = {"MIS", "CNC"}
EXCHANGES = {"NSE", "BSE"}
DERIV = re.compile(r"^[A-Z&\\-]+\\d{2}[A-Z0-9]{1,3}\\d*(CE|PE|FUT)$")
TICKER = re.compile(r"^[A-Z0-9][A-Z0-9&\\-]{0,19}$")
CIRCUIT_NEAR = 0.01  # a buy within 1% of the upper circuit is blocked''')
rep('''raise RiskError("%s must be a India time like \\"09:45\\", got %r" % (key, value))''',
    '''raise RiskError("%s must be an India time like \\"09:30\\", got %r" % (key, value))''')
rep('''        warns.append("the holiday list covers %s only: check nyse.com for %s"''',
    '''        warns.append("the holiday list covers %s only: add %s's year to shared/nse_holidays.json"''')
rep('''    close = EARLY if d.isoformat() in EARLY_CLOSE else CLOSE
    if t < OPEN or now_et.time() >= close:
        return ["window: the market is closed (%s India; the session is %s to %s)"
                % (stamp, OPEN.strftime("%H:%M"), close.strftime("%H:%M"))], warns
    if close == EARLY and after is not None:
        after = _shift(after, 3)
        warns.append("early close at 1:00 p.m. today (%s): no new entries after %s"
                     % (EARLY_CLOSE[d.isoformat()], after.strftime("%H:%M")))''',
'''    close = CLOSE
    if t < OPEN or now_et.time() >= close:
        return ["window: the market is closed (%s India; the session is %s to %s)"
                % (stamp, OPEN.strftime("%H:%M"), close.strftime("%H:%M"))], warns''')
cut("_shift"); cut("business_days"); cut("day_trades")
rep('''    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}''',
    '''    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}''')
rep('''"""Same function in trader-broker/ticket.py: the exact order that was checked."""''',
    '''"""Same function in trader-in-broker/ticket.py: the exact order that was checked."""''')
rep('''    return "$" + "{:,.2f}".format(float(x)).replace(".00", "")''', '''    return "\\u20b9" + "{:,.2f}".format(float(x)).replace(".00", "")''')
rep('''    """A price to the cent, half up (366.475 -> 366.48)."""''', '''    """A price to the paisa, half up (2443.475 -> 2443.48)."""''')
rep('''def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None, price_times=None):''',
    '''def on_tick(x, tick):
    """True when price x is a whole number of ticks."""
    n = float(x) / float(tick)
    return abs(n - round(n)) < 1e-6


def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None, price_times=None,
          circuits=None):''')
rep('''    price_times  {SYM: naive UTC time of that price}; None = every price counts as fresh"""''',
    '''    price_times  {SYM: naive UTC time of that price}; None = every price counts as fresh
    circuits     {SYM: (lower, upper)} circuit limits, when known"""''')
rep('''    pdt_n, pdt_list = day_trades(state, today) if c.get("pdt_guard") else (0, [])\n''', '')
rep('''        sym = str(o.get("symbol", "")).strip().upper()''', '''        sym = market_in.kite_symbol(str(o.get("symbol", "")).strip())[1] if o.get("symbol") else ""''')
rep('''        qty, notional = o.get("qty"), o.get("notional")''', '''        qty, notional = o.get("qty"), None
        product = str(o.get("product") or c.get("product") or "MIS").upper()
        exch = str(o.get("exchange") or c.get("exchange") or "NSE").upper()
        fno = market_in.is_fno(sym) if sym else False''')
rep('''        if (qty is None) == (notional is None):
            reasons.append("format: give exactly one of qty or notional")''',
'''        if o.get("notional") is not None:
            reasons.append("format: NSE orders take a whole-share qty; amount (notional) orders do not exist")
        if qty is None:
            reasons.append("format: no qty")
        elif _f(qty) is not None and abs(_f(qty) - round(_f(qty))) > 1e-9:
            reasons.append("format: whole shares only, got qty %r" % qty)
        if product not in PRODUCTS:
            reasons.append("format: product must be MIS (intraday) or CNC (delivery), got %r" % product)
        if exch not in EXCHANGES:
            reasons.append("format: exchange must be NSE or BSE, got %r" % exch)''')
rep('''                    warns.append("send %s as a string (\\"%s\\"), the way place_stock_order types it"
                                 % (k, o.get(k)))''',
'''                    warns.append("write %s as a string (\\"%s\\"), the way trader/orders.json types it"
                                 % (k, o.get(k)))''')
rep('''        if notional is not None and (typ != "market" or tif != "day"):
            reasons.append("format: a notional (dollar) order must be a market order with time_in_force day")
''', '''        tick = _f(o.get("tick")) or None
        for k in TICK_FIELDS:
            v = _f(o.get(k))
            if v and v > 0:
                tk = tick or float(market_in.tick_size(v))
                if not on_tick(v, tk):
                    reasons.append("format: %s %s is not on the tick (%s)%s" % (
                        k, _p(v), _num(tk), "" if tick else ": price-band table; give the order's tick from Kite"))
''')
rep('''        if o.get("extended_hours") and not (typ == "limit" and tif in ("day", "gtc")):
            reasons.append("format: extended hours needs a limit order with time_in_force day or gtc")
''', '')
rep('''            if notional is not None:
                reasons.append("format: a bracket order needs a whole-share qty, not a notional amount")
            elif _f(qty) is not None and abs(_f(qty) - round(_f(qty))) > 1e-9:
                reasons.append("format: a bracket order takes whole shares only, got qty %r" % qty)
            if tif not in ("day", "gtc"):
                reasons.append("format: a bracket order needs time_in_force day or gtc, got %r" % tif)''',
'''            if tif != "day":
                reasons.append("format: a bracket order needs time_in_force day, got %r" % tif)''')
rep('''        elif oc or o.get("advanced_instructions"):
            warns.append("advanced order (%s): check every leg before you say yes"
                         % (oc or "advanced_instructions"))''',
'''        elif oc:
            warns.append("advanced order (%s): check every leg before you say yes" % oc)''')
rep('''        if sym and OCC.match(sym.replace(" ", "")):
            if not c.get("allow_options"):
                reasons.append("asset: %s is an option contract; options are off "
                               "(\\"allow_options\\": false)" % sym)
            else:
                warns.append("option order: options can lose 100%% of what you pay")
        elif sym and ("/" in sym or not TICKER.match(sym)):
            reasons.append("asset: %s does not look like a US stock or ETF ticker; "
                           "this pack trades stocks and ETFs only" % sym)''',
'''        if sym and DERIV.match(sym.replace(" ", "")):
            if not c.get("allow_options"):
                reasons.append("asset: %s is an F&O contract; derivatives are off "
                               "(\\"allow_options\\": false)" % sym)
            else:
                warns.append("F&O order: options can lose 100%% of what you pay, futures more than you put in")
        elif sym and ("/" in sym or not TICKER.match(sym)):
            reasons.append("asset: %s does not look like an NSE/BSE stock symbol; "
                           "this pack trades stocks and ETFs only" % sym)''')
rep('''                         "trader/prices.json (trader-alerts: alerts.py quote %s --write)" % (sym, qty, sym))''',
    '''                         "trader/prices.json (trader-in-alerts: alerts.py quote %s --write)" % (sym, qty, sym))''')
rep('''        if sym in blocked:
            later.append("blocked: %s is on your blocked list" % sym)''',
'''        if sym in blocked:
            later.append("blocked: %s is on your blocked list" % sym)
        lev = market_in.mis_leverage(sym) if sym else None
        if product == "MIS" and side in ("buy", "sell") and sym and lev is None:
            later.append("mis: %s is not on Zerodha's MIS list, so it cannot be traded intraday "
                         "(refresh shared/zerodha_mis_margins.json with refresh_data.py if it should be)" % sym)''')
rep('''        buffer_inr = total * float(c.get("cash_buffer_pct") or 0) / 100.0
        if value is not None and side == "buy" and kind == "entry":
            after_cash = cash - value
            if after_cash < -CENT and not c.get("allow_margin"):
                later.append("cash: needs %s but only %s cash; that would be margin (borrowed money)"
                             % (money(value), money(cash)))
            elif after_cash < buffer_inr - CENT:
                later.append("cash: leaves %s cash, under your %s%% buffer of %s"
                             % (money(max(after_cash, 0)), _pct(c["cash_buffer_pct"]), money(buffer_inr)))''',
'''        buffer_inr = total * float(c.get("cash_buffer_pct") or 0) / 100.0
        if value is not None and side == "buy" and kind == "entry":
            lev_ok = c.get("allow_margin") and product == "MIS" and lev and float(lev) > 1
            need = value / float(lev) if lev_ok else value   # the margin Zerodha blocks for the trade
            after_cash = cash - need
            if after_cash < -CENT:
                later.append("cash: needs %s%s but only %s cash; that would be borrowed money"
                             % (money(need), (" margin (%s at %sx MIS)" % (money(value), _num(float(lev))))
                                if lev_ok else "", money(cash)))
            elif after_cash < buffer_inr - CENT:
                later.append("cash: leaves %s cash, under your %s%% buffer of %s"
                             % (money(max(after_cash, 0)), _pct(c["cash_buffer_pct"]), money(buffer_inr)))''')
rep('''                               "If you bought it, record the fill first (ticket.py fill)" % (sym, _num(held)))''',
    '''                               "If you bought it, record the fill first (ticket.py fill)" % (sym, _num(held)))
        if side == "sell" and kind == "entry" and c.get("allow_short") and product != "MIS":
            reasons.append("short: only intraday (MIS) short sells exist for NSE stocks; this one is %s" % product)''')
rep('''                warns.append("the stop %s is in the plan only, not at the broker: set a stop alert "
                             "(trader-alerts: alerts.py add --from-plan)" % _p(stop))''',
    '''                warns.append("the stop %s is in the plan only, not at the broker: set a stop alert "
                             "(trader-in-alerts: alerts.py add --from-plan)" % _p(stop))''')
rep('''                    later.append("stop: no stop. Every entry needs one (\\"require_stop\\": true): a bracket "
                                 "stop_loss_stop_price, from trader-exit and trader-budget")''',
    '''                    later.append("stop: no stop. Every entry needs one (\\"require_stop\\": true): a bracket "
                                 "stop_loss_stop_price, from trader-in-exit and trader-in-budget")''')
rep('''                    max_loss = round(shares * risk_ps, 2)
                    cap = _f(c.get("max_loss_per_trade_inr"))
                    if cap and max_loss > cap + CENT:
                        later.append("loss: %s shares x %s risk a share = %s at the stop, over your %s max loss "
                                     "per trade" % (_num(shares), _p(risk_ps), money(max_loss), money(cap)))''',
'''                    charges = 0.0
                    if c.get("include_charges", True) and shares:
                        charges = float(market_in.round_trip_costs(ref, stop, int(round(shares)), exch)["total"])
                    max_loss = round(shares * risk_ps + charges, 2)
                    cap = _f(c.get("max_loss_per_trade_inr"))
                    if cap and max_loss > cap + CENT:
                        later.append("loss: %s shares x %s risk a share%s = %s at the stop, over your %s max loss "
                                     "per trade" % (_num(shares), _p(risk_ps),
                                                    (" + %s charges" % money(charges)) if charges else "",
                                                    money(max_loss), money(cap)))''')
rep('''            later.extend(win_reasons)
            if c.get("pdt_guard") and pdt_n >= 3:
                later.append("pdt: %d day trades in the last 5 business days (%s); a 4th trips the "
                             "pattern-day-trader rule your broker applies (\\"pdt_guard\\": true)"
                             % (pdt_n, ", ".join(pdt_list)))''',
'''            later.extend(win_reasons)
            if not win_reasons and trading_day(now_et.date())[0]:
                tnow = now_et.time()
                if fno and tnow >= market_in.CAS_CLOSE:
                    later.append("window: %s is an F&O stock; continuous trading ended at %s (closing auction)"
                                 % (sym, market_in.CAS_CLOSE.strftime("%H:%M")))
                sq = market_in.square_off_time(fno)
                if product == "MIS" and tnow >= sq:
                    later.append("window: Zerodha auto squares off MIS at %s%s; no new MIS entries after it"
                                 % (sq.strftime("%H:%M"), " for F&O stocks" if fno else ""))
            lim = (circuits or {}).get(sym)
            if lim and ref:
                lo_c, up_c = lim
                if long and up_c and ref >= up_c * (1 - CIRCUIT_NEAR):
                    later.append("circuit: %s at %s is within 1%% of its upper circuit %s; a locked stock may "
                                 "not let you out" % (sym, _p(ref), _p(up_c)))
                if long and lo_c and stop and stop < lo_c:
                    later.append("circuit: the stop %s is under the lower circuit %s, so it can never trigger "
                                 "today" % (_p(stop), _p(lo_c)))''')
rep('''                            % (money(max_loss), (" (limit %s)" % money(c["max_loss_per_trade_inr"]))''',
    '''                            % (money(max_loss), (" incl. charges (limit %s)" % money(c["max_loss_per_trade_inr"]))''')
rep('''            "value_inr": round(value, 2) if value is not None else None,''',
    '''            "value_inr": round(value, 2) if value is not None else None, "product": product, "exchange": exch,''')
rep('''        "now_new_york": now_et.strftime("%Y-%m-%d %H:%M"),''', '''        "now_ist": now_et.strftime("%Y-%m-%d %H:%M"),''')
rep('''                  "loss_at_risk": round(loss_today, 2), "day_trades_5d": pdt_n if c.get("pdt_guard") else None},''',
    '''                  "loss_at_risk": round(loss_today, 2)},''')
rep('''                 % (res["pass"], res["block"], res["now_new_york"], money(res["cash_after"]),''',
    '''                 % (res["pass"], res["block"], res["now_ist"], money(res["cash_after"]),''')
rep('''        lines.append("Every order passed. trader-broker still asks you yes or no for each one.")''',
    '''        lines.append("Every order passed. trader-in-broker still asks you yes or no for each one.")''')
rep('''def load_prices(pdoc):
    """prices.json -> ({SYM: price}, {SYM: price time as naive UTC or None}).''',
'''def load_circuits(pdoc):
    """prices.json detail.SYM.lower_circuit / upper_circuit -> {SYM: (lower, upper)}."""
    out = {}
    for s, d in ((pdoc or {}).get("detail") or {}).items():
        if isinstance(d, dict) and (d.get("upper_circuit") or d.get("lower_circuit")):
            out[market_in.kite_symbol(str(s))[1]] = (_f(d.get("lower_circuit")), _f(d.get("upper_circuit")))
    return out


def load_prices(pdoc):
    """prices.json -> ({SYM: price}, {SYM: price time as naive UTC or None}).''')
rep('''        s = str(s).upper()
        out[s] = float(p)
        d = detail.get(s) or {}''', '''        d = detail.get(s) or detail.get(str(s).upper()) or {}
        s = market_in.kite_symbol(str(s))[1]
        out[s] = float(p)''')
rep('''description="Check proposed orders against your limits (trader-risk)."''', '''description="Check proposed orders against your limits (trader-in-risk, NSE)."''')
rep('''help="what trader-broker placed today")''', '''help="what trader-in-broker placed today")''')
rep('''help="pretend it is this India time, e.g. \\"2026-10-19 10:15\\"")''', '''help="pretend it is this India time, e.g. \\"2026-11-23 10:15\\"")''')
rep('''            raise RiskError("--today wants a date like 2026-10-19")''', '''            raise RiskError("--today wants a date like 2026-11-23")''')
rep('''        doc = read_json(a.orders, "orders file (run trader-budget first)")''', '''        doc = read_json(a.orders, "orders file (run trader-in-budget first)")''')
rep('''        res = check(orders, cfg, portfolio, prices, state, a.today, now, times)''',
    '''        res = check(orders, cfg, portfolio, prices, state, a.today, now, times, load_circuits(pdoc))''')
rep('''        t = str(p.get("ticker") or p.get("symbol") or "").upper()''', '''        t = market_in.kite_symbol(str(p.get("ticker") or p.get("symbol") or ""))[1] if (p.get("ticker") or p.get("symbol")) else ""''')
t = t.replace('$%', '₹%')
open(p, "w").write(t); print("risk patched")
