"""One-off: broker (ticket.py) Alpaca -> Zerodha Kite, after port_common.py."""
import re, sys
p = sys.argv[1]; t = open(p).read()
def rep(a, b, c=1):
    global t
    assert t.count(a) == c, (t.count(a), a[:80]); t = t.replace(a, b)

s = t.index('"""Order tickets'); e = t.index('"""', s + 3) + 3
t = t[:s] + '''"""Order tickets and the decision log for trader-in-broker (Zerodha Kite). Standard library only.
Ported from day-trader-skill's US order executor (MIT).

This tool never talks to a broker and never places anything. It does its
work around the one moment that matters, your yes:

  show      renders each proposed order as a plain-English ticket plus the
            exact inputs Claude will send to the Kite MCP tools: the entry
            (orders, mode=place, MIS) and, for a bracket, the exits it places
            once the entry fills (gtt, mode=place, a two-leg OCO: stop-loss
            below, take-profit above; when one triggers the other is
            cancelled; Zerodha has no bracket orders). A bracket shows its
            stop-loss, take-profit and the max loss at the stop. An order is
            READY only if trader-in-risk passed THIS exact order today (matched
            by fingerprint) and nobody has decided on it yet.
  approve   records your explicit yes for ONE order, with your reply word for
            word. It refuses "yes to all", "sure", "ok", a yes that names a
            different stock or amount, and any order that is not READY.
  decline   records a no.
  result    records what happened next: placed (with Kite's order id),
            exits-placed (the GTT trigger id), denied, or failed.
  fill      records a fill in trader/portfolio.json (cash and shares).
  flatten   builds a sell ticket that closes a symbol's open position by
            flat_by (before Zerodha's MIS square-off). It still goes through
            trader-in-risk and your yes.
  log       prints today's decisions.

Paper ("paper": true, the default): Kite has no paper account, so paper mode
is a local simulation. Nothing is sent to Kite; you record a simulated fill at
the current price with ticket.py result --filled-qty/--filled-price.
Live ("paper": false): after your yes, Claude calls the Kite tool, and Kite's
own approval form or browser link asks you again before anything reaches NSE.

    python3 ticket.py show                    # every order, READY or not
    python3 ticket.py show --index 1 --json   # one ticket as JSON
    python3 ticket.py approve --index 1 --reply "yes"
    python3 ticket.py result --index 1 --status placed --broker-id 251123000123456
    python3 ticket.py result --index 1 --status exits-placed --broker-id 123456789
    python3 ticket.py fill --symbol TCS --side buy --qty 15 --price 2443.50
    python3 ticket.py flatten --symbol TCS --qty 15
    python3 ticket.py log

Everything is written to trader/state/broker.json (append only). Dates are
India dates; --now "2026-11-23 10:15" pins the clock.
"""''' + t[e:]
rep('''ALPACA_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                 "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                 "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price", "advanced_instructions")
STRING_FIELDS = ("qty", "notional", "limit_price", "stop_price", "trail_price", "trail_percent",
                 "take_profit_limit_price", "stop_loss_stop_price", "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "gtc": "good until canceled", "opg": "at the open",
             "cls": "at the close", "ioc": "immediate or cancel", "fok": "fill or kill"}''',
'''# The fields that define an order (same tuple in trader-in-risk/check.py: the fingerprint).
ORDER_FIELDS = ("symbol", "side", "qty", "type", "time_in_force", "limit_price", "stop_price",
                "exchange", "product", "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                "stop_loss_limit_price")
STRING_FIELDS = ("qty", "limit_price", "stop_price", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "ioc": "immediate or cancel"}
PRODUCT_WORDS = {"MIS": "intraday (MIS)", "CNC": "delivery (CNC)"}''')
rep('''raise TicketError("--now wants a time like \\"2026-10-19 10:15\\" (India) or ...Z (UTC)")''',
    '''raise TicketError("--now wants a time like \\"2026-11-23 10:15\\" (India) or ...Z (UTC)")''')
rep('''    """naive UTC -> "2026-10-19T10:15:00-04:00" (India wall clock with its offset)."""
    off = local_offset(now_utc)
    return "%s%+03d:00" % (to_local(now_utc).replace(microsecond=0).isoformat(), off)''',
'''    """naive UTC -> "2026-11-23T10:15:00+05:30" (India wall clock with its offset)."""
    return "%s+05:30" % to_local(now_utc).replace(microsecond=0).isoformat()''')
rep('''    """Same function as trader-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ALPACA_FIELDS if k in order and order[k] is not None}''',
'''    """Same function as trader-in-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}''')
rep('''def tool_input(order):
    """The exact arguments for place_stock_order: Alpaca's parameter names,
    numbers as strings (its signature types qty, notional and prices as str).
    "why" and "plan" are ours and are never sent."""
    out = {}
    for k in ALPACA_FIELDS:
        if k in order and order[k] is not None:
            out[k] = _str_num(order[k]) if k in STRING_FIELDS else order[k]
    return out''',
'''def tool_input(order):
    """The exact input of the Kite `orders` tool for the entry (market_in.kite_entry).
    "why" and "plan" are ours and are never sent."""
    return market_in.kite_entry(order)


def exit_input(order, last_price=None):
    """For a bracket: the exact input of the Kite `gtt` tool (a two-leg OCO), placed
    once the entry has filled. None for an order without legs."""
    return market_in.kite_exit_gtt(order, last_price)''')
rep('''    return "$" + (s[:-3] if s.endswith(".00") else s)''', '''    return "\\u20b9" + (s[:-3] if s.endswith(".00") else s)''')
rep('''    """(dollars, stop) lost if the stop fills exactly at the stop, or (None, stop)."""''',
    '''    """(rupees, stop) lost if the stop fills exactly at the stop (with charges when the plan
    has them), or (None, stop)."""''')
rep('''    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        parts = ["%s %s %s, %s, %s" % (side, _str_num(order.get("qty")), sym, how, tif)]''',
'''    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    tif = "%s, %s, %s" % (order.get("exchange") or "NSE",
                          PRODUCT_WORDS.get(str(order.get("product") or "MIS").upper(), order.get("product")), tif)
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        parts = ["%s %s %s, %s, %s" % (side, _str_num(order.get("qty")), sym, how, tif)]''')
rep('''            parts.append("max loss about %s if the stop fills at %s (it can fill worse in a fast market)"
                         % (_money(loss), _p(stop)))
        return parts
    if order.get("notional") is not None:
        what = "%s of %s" % (_money(order["notional"]), sym)
    else:
        q = _str_num(order.get("qty"))
        what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)''',
'''            parts.append("max loss about %s if the stop fills at %s, charges included (it can fill worse in a "
                         "fast market)" % (_money(loss), _p(stop)))
        return parts
    q = _str_num(order.get("qty"))
    what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)''')
rep('''    """BUY $1,250 of AAPL, market order, good for today
    BUY 8 TSLA, market, good for today / stop-loss 358.32 / take-profit 370.04 / max loss about $46.88 ..."""''',
    '''    """BUY 10 shares of ITC, market order, NSE, delivery (CNC), good for today
    BUY 15 TCS, market, NSE, intraday (MIS), good for today / stop-loss 2419.30 (limit 2407.20) / ..."""''')
rep('''    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",''',
    '''    for k in ("qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",''')
rep('''    tokens = set(re.findall(r"[A-Z][A-Z.\\-]{0,6}", raw.upper()))''', '''    tokens = set(re.findall(r"[A-Z0-9][A-Z0-9&\\-]{1,19}", raw.upper()))''')
rep('''        return None, "trader-risk has not checked these orders (run check.py)"''', '''        return None, "trader-in-risk has not checked these orders (run check.py)"''')
rep('''        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv''', '''        return False, "BLOCKED by trader-in-risk: " + "; ".join(rv.get("reasons", [])), rv''')
rep('''            return False, "APPROVED by you at %s, waiting for the place_stock_order call" % rec.get("at"), rv''',
    '''            return False, "APPROVED by you at %s, waiting for the Kite orders call" % rec.get("at"), rv''')
rep('''    return True, "READY: trader-risk PASS, waiting for your yes", rv''', '''    return True, "READY: trader-in-risk PASS, waiting for your yes", rv''')
rep('''    """entry or exit, as trader-risk saw it (older checks: a buy is an entry)."""''', '''    """entry or exit, as trader-in-risk saw it (older checks: a buy is an entry)."""''')
s = t.index("def render(order, idx, total, cfg, risk, state, today):"); e = t.index("def ticket_json(")
t = t[:s] + '''def render(order, idx, total, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    paper = cfg.get("paper", True)
    acct = "PAPER (simulated: nothing is sent to Kite)" if paper else "LIVE ZERODHA ACCOUNT, REAL MONEY"
    lines = ["ORDER %d of %d, %s, Zerodha Kite" % (idx, total, acct)]
    for part in plain_parts(order):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  why: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  note: " + w)
    lines.append("  %s the Kite orders tool with exactly:" % ("Live, Claude would call" if paper else "Claude will call"))
    for l in json.dumps(tool_input(order), indent=2).splitlines():
        lines.append("    " + l)
    if is_bracket(order):
        lines.append("  Once the entry fills, the exits go in as ONE Kite GTT (gtt tool), a two-leg OCO:")
        for l in json.dumps(exit_input(order), indent=2).splitlines():
            lines.append("    " + l)
        lines.append("  When the stop-loss or the take-profit triggers, Kite cancels the other. last_price is")
        lines.append("  set to the entry's fill price when it is placed.")
        if market_in.is_fno(order.get("symbol", "")):
            lines.append("  F&O stock: GTTs only trigger until 15:15 (closing auction), so flatten by flat_by.")
    if ready:
        lines.append("  Reply \\"yes\\" to place this one order, or \\"no\\" to skip it.")
        if paper:
            lines.append("  Paper: nothing goes to Kite; the fill is simulated at the current price.")
        else:
            lines.append("  Kite then asks you to approve it in its own form or browser link before it goes to NSE.")
    return "\\n".join(lines), ready


''' + t[e:]
rep('''            "fingerprint": fingerprint(order), "paper": bool(cfg.get("paper", True)),
            "broker": cfg.get("broker", "alpaca"), "tool": "place_stock_order",
            "tool_input": tool_input(order), "why": order.get("why", ""),''',
'''            "fingerprint": fingerprint(order), "paper": bool(cfg.get("paper", True)),
            "broker": "kite", "tool": "orders", "tool_input": tool_input(order),
            "exit_tool": "gtt" if is_bracket(order) else None, "exit_input": exit_input(order),
            "why": order.get("why", ""),''')
rep('''    symbol = symbol.upper()
    qty, price = float(qty), float(price)''', '''    symbol = market_in.kite_symbol(symbol)[1]
    qty, price = float(qty), float(price)''')
rep('''    """A fill in the log, so trader-risk can count day trades (a buy and a sell the same day)."""''',
    '''    """A fill in the log, so trader-in-risk sees what was bought and sold today."""''')
rep('''        "at": local_iso(now), "date": today, "status": "filled", "symbol": symbol.upper(), "side": side,''',
    '''        "at": local_iso(now), "date": today, "status": "filled", "symbol": market_in.kite_symbol(symbol)[1], "side": side,''')
rep('''        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), symbol.upper(), _p(price))})''',
    '''        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), market_in.kite_symbol(symbol)[1], _p(price))})''')
t = t.replace('raise TicketError("--today wants a date like 2026-10-19")', 'raise TicketError("--today wants a date like 2026-11-23")')
t = t.replace('raise TicketError("--date wants a date like 2026-10-19")', 'raise TicketError("--date wants a date like 2026-11-23")')
rep('''    doc = read_json(a.orders, "orders file (run trader-budget, or ticket.py flatten, first)")''',
    '''    doc = read_json(a.orders, "orders file (run trader-in-budget, or ticket.py flatten, first)")''')
rep('''           "paper": bool(cfg.get("paper", True)), "broker": cfg.get("broker", "alpaca")}''',
    '''           "paper": bool(cfg.get("paper", True)), "broker": "kite"}''')
rep('''    print("Recorded your yes for order %d: %s." % (a.index, plain(order)))
    if str(cfg.get("broker", "alpaca")).lower() == "ibkr":
        print("Now draft it with the Interactive Brokers connector; approve it in your IBKR account.")
    else:
        print("Now call place_stock_order with exactly:")
        print(json.dumps(tool_input(order), indent=2))
        print("Claude's card shows Allow once / Deny. Then: ticket.py result --index %d --status "
              "placed|denied|failed" % a.index)''',
'''    print("Recorded your yes for order %d: %s." % (a.index, plain(order)))
    if cfg.get("paper", True):
        print("PAPER: nothing is sent to Kite. Simulate the fill at the current price (a Kite quote or")
        print("alerts.py quote %s), then: ticket.py result --index %d --status placed --filled-qty %s "
              "--filled-price P" % (order.get("symbol"), a.index, _str_num(order.get("qty"))))
    else:
        print("Now call the Kite orders tool with exactly:")
        print(json.dumps(tool_input(order), indent=2))
        print("Kite asks the user to approve it (its form or a browser link). Share the link; never approve it")
        print("for them. Then: ticket.py result --index %d --status placed|denied|failed --broker-id ORDER_ID"
              % a.index)''')
rep('''    if not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no yes recorded today; a result can only follow an approval" % a.index)''',
'''    if a.status == "exits-placed":
        if not rec or rec.get("status") not in ("placed", "exits-placed"):
            raise TicketError("order %d has no placed entry today; exits follow a filled entry" % a.index)
    elif not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no yes recorded today; a result can only follow an approval" % a.index)''')
rep('''    print("Recorded order %d as %s." % (a.index, a.status))
    if a.status == "placed" and a.filled_qty and a.filled_price:
        apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], a.filled_qty, a.filled_price, today)
        log_fill(a.state, now, today, rec["symbol"], rec["side"], a.filled_qty, a.filled_price)
        print("Added the fill to %s." % a.portfolio)
    elif a.status == "placed":
        print("When it fills, record it: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (rec["symbol"], rec["side"]))
        if rec.get("kind") == "entry" and is_bracket(order):
            print("When the stop-loss or the take-profit fills later, record that sell the same way.")''',
'''    print("Recorded order %d as %s." % (a.index, a.status))
    if a.status == "placed" and a.filled_qty and a.filled_price:
        apply_fill(a.portfolio, cfg, rec["symbol"], rec["side"], a.filled_qty, a.filled_price, today)
        log_fill(a.state, now, today, rec["symbol"], rec["side"], a.filled_qty, a.filled_price)
        print("Added the fill to %s." % a.portfolio)
    elif a.status == "placed":
        print("When it fills, record it: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (rec["symbol"], rec["side"]))
    if a.status == "placed" and rec.get("kind") == "entry" and is_bracket(order):
        ex = exit_input(order, _f(a.filled_price))
        if cfg.get("paper", True):
            print("PAPER: the exits are simulated too. Watch them with trader-in-alerts (alerts.py add --from-plan);")
            print("when the stop or target is hit, record the sell: ticket.py fill --symbol %s --side sell" % rec["symbol"])
        else:
            print("Once the entry has FILLED (orders mode=trades), place the exits with the Kite gtt tool:")
            print(json.dumps(ex, indent=2))
            print("Then: ticket.py result --index %d --status exits-placed --broker-id TRIGGER_ID" % a.index)
        print("When the stop-loss or the take-profit fills later, record that sell the same way.")''')
rep('''    sym = a.symbol.strip().upper()
    now, today = _clock(a)
    source = "the broker, get_open_position"''', '''    sym = market_in.kite_symbol(a.symbol.strip())[1]
    now, today = _clock(a)
    source = "Kite positions (portfolio mode=positions)"''')
rep('''            raise TicketError("nothing to flatten: no %s shares in %s. Check the broker (get_open_position "
                              "%s) and pass --qty if you do hold some" % (sym, a.portfolio, sym))''',
    '''            raise TicketError("nothing to flatten: no %s shares in %s. Check Kite (portfolio mode=positions) "
                              "and pass --qty if you do hold some" % (sym, a.portfolio))''')
rep('''    flat_by = (plan.get("flat_by") if str(plan.get("symbol", "")).upper() == sym else None) \\
        or cfg.get("flat_by") or "15:55"
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "why": "flat by %s India: closes the %s day trade before the close (qty from %s)"
             % (flat_by, sym, source)}''',
'''    flat_by = (plan.get("flat_by") if market_in.kite_symbol(str(plan.get("symbol", "")))[1] == sym else None) \\
        or cfg.get("flat_by") or market_in.FLAT_BY.strftime("%H:%M")
    product = str(cfg.get("product") or "MIS").upper()
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "exchange": str(cfg.get("exchange") or "NSE").upper(), "product": product,
             "why": "flat by %s IST: closes the %s day trade before Zerodha's MIS square-off at %s (qty from %s)"
             % (flat_by, sym, market_in.square_off_time(market_in.is_fno(sym)).strftime("%H:%M"), source)}''')
rep('''           "note": "Flatten ticket. Nothing is placed until trader-risk passes it and you say yes in the chat.",''',
    '''           "note": "Flatten ticket. Nothing is placed until trader-in-risk passes it and you say yes in the chat.",''')
rep('''        print("The qty comes from %s. Check it against get_open_position %s before you say yes." % (source, sym))
    print("Next:")
    print("  1. trader-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order.")
    print("  3. If the bracket's stop-loss and take-profit are still open, Alpaca holds these shares for them")
    print("     and rejects a new sell. Cancel them first: get_orders (status open, nested true), then")
    print("     cancel_order_by_id for each open leg (Needs approval). Then place_stock_order with the ticket.")''',
'''        print("The qty comes from %s. Check it against Kite (portfolio mode=positions) before you say yes." % source)
    print("Next:")
    print("  1. trader-in-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order.")
    print("  3. If the bracket's GTT (stop-loss / take-profit) is still active, delete it FIRST (gtt mode=list,")
    print("     then mode=delete with its trigger id), or it can fire after you are out and open a short.")
    print("     Then the Kite orders tool with the ticket. Zerodha auto squares off MIS at %s anyway, for a fee."
          % market_in.square_off_time(market_in.is_fno(sym)).strftime("%H:%M"))''')
rep('''    ap = argparse.ArgumentParser(description="Order tickets and your yes (trader-broker). Never places orders.")''',
    '''    ap = argparse.ArgumentParser(description="Order tickets and your yes (trader-in-broker, Zerodha Kite). Never places orders.")''')
rep('''        p.add_argument("--now", help="pretend it is this India time, e.g. \\"2026-10-19 10:15\\"")''',
    '''        p.add_argument("--now", help="pretend it is this India time, e.g. \\"2026-11-23 10:15\\"")''')
rep('''    p = sub.add_parser("result", help="record what happened after the Allow once / Deny card")''',
    '''    p = sub.add_parser("result", help="record what happened: placed, exits-placed, denied, failed")''')
rep('''    p.add_argument("--status", required=True, choices=["placed", "denied", "failed"])''',
    '''    p.add_argument("--status", required=True, choices=["placed", "exits-placed", "denied", "failed"])''')
rep('''    p.add_argument("--qty", help="shares you hold, from get_open_position (default: trader/portfolio.json)")''',
    '''    p.add_argument("--qty", help="shares you hold, from Kite positions (default: trader/portfolio.json)")''')
t = t.replace('$%', '₹%')
open(p, "w").write(t); print("broker patched")
