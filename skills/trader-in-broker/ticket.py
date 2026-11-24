#!/usr/bin/env python3
"""Order tickets and the decision log for trader-in-broker (Zerodha Kite). Standard library only.
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
  gtt-check finds leftover stop/target GTTs: an active MIS GTT whose SELL leg
            is bigger than your open MIS position in that stock. A GTT lives
            across days, so after Zerodha's auto square-off (or any close that
            skipped deleting it) its stop leg can fire on no shares and open a
            short. Reads Kite's gtt list and positions saved as JSON; prints
            the gtt delete inputs. It deletes nothing itself. GTTs on CNC or
            NRML (holdings, F&O) are left alone.

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
    python3 ticket.py gtt-check --gtts gtts.json --positions positions.json

Everything is written to trader/state/broker.json (append only). Dates are
India dates; --now "2026-11-23 10:15" pins the clock.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402


# The fields that define an order (same tuple in trader-in-risk/check.py: the fingerprint).
ORDER_FIELDS = ("symbol", "side", "qty", "type", "time_in_force", "limit_price", "stop_price",
                "exchange", "product", "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                "stop_loss_limit_price")
STRING_FIELDS = ("qty", "limit_price", "stop_price", "take_profit_limit_price", "stop_loss_stop_price",
                 "stop_loss_limit_price")
TIF_WORDS = {"day": "good for today", "ioc": "immediate or cancel"}
PRODUCT_WORDS = {"MIS": "intraday (MIS)", "CNC": "delivery (CNC)"}
YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if"}


class TicketError(Exception):
    pass


# ---------------------------------------------------------------- time (India, no tz files)

IST_HOURS = 5.5  # India Standard Time, UTC+5:30, no daylight saving


def local_offset(utc):
    """Hours from UTC for India: always +5.5 (no DST)."""
    return IST_HOURS


def to_local(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=IST_HOURS)


def local_to_utc(local):
    return local - datetime.timedelta(hours=IST_HOURS)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as India time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TicketError("--now wants a time like \"2026-11-23 10:15\" (India) or ...Z (UTC)")
    if dt.tzinfo is None:
        return local_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def local_iso(now_utc):
    """naive UTC -> "2026-11-23T10:15:00+05:30" (India wall clock with its offset)."""
    return "%s+05:30" % to_local(now_utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """The trading day a decision belongs to: its "date" (the day it was made under), else the day of "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

def fingerprint(order):
    """Same function as trader-in-risk/check.py: identifies the exact order."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def tool_input(order):
    """The exact input of the Kite `orders` tool for the entry (market_in.kite_entry).
    "why" and "plan" are ours and are never sent."""
    return market_in.kite_entry(order)


def exit_input(order, last_price=None):
    """For a bracket: the exact input of the Kite `gtt` tool (a two-leg OCO), placed
    once the entry has filled. None for an order without legs."""
    return market_in.kite_exit_gtt(order, last_price)


def _money(v):
    f = float(v)
    s = "{:,.2f}".format(f)
    return "\u20b9" + (s[:-3] if s.endswith(".00") else s)


def _p(v):
    return "%.2f" % float(v)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def max_loss(order):
    """(rupees, stop) lost if the stop fills exactly at the stop (with charges when the plan
    has them), or (None, stop)."""
    stop = _f(order.get("stop_loss_stop_price")) or _f((order.get("plan") or {}).get("stop"))
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop
    plan = order.get("plan") or {}
    if str(order.get("type", "market")) == "limit" and _f(order.get("limit_price")):
        entry = _f(order["limit_price"])
    elif _f(plan.get("max_loss")) is not None:
        return round(_f(plan["max_loss"]), 2), stop
    else:
        entry = _f(plan.get("entry"))
    if not entry:
        return None, stop
    risk = abs(entry - stop)
    return round(q * int(round(risk * 100)) / 100.0, 2), stop


def plain_parts(order):
    """The ticket in plain words, one part per line."""
    side = str(order.get("side", "")).upper()
    sym = order.get("symbol", "?")
    typ = str(order.get("type", "market"))
    tif = TIF_WORDS.get(str(order.get("time_in_force", "day")), order.get("time_in_force"))
    tif = "%s, %s, %s" % (order.get("exchange") or "NSE",
                          PRODUCT_WORDS.get(str(order.get("product") or "MIS").upper(), order.get("product")), tif)
    if is_bracket(order):
        how = "limit %s" % _p(order["limit_price"]) if typ == "limit" and order.get("limit_price") else typ
        parts = ["%s %s %s, %s, %s" % (side, _str_num(order.get("qty")), sym, how, tif)]
        if order.get("stop_loss_stop_price") is not None:
            leg = "stop-loss %s" % _p(order["stop_loss_stop_price"])
            if order.get("stop_loss_limit_price") is not None:
                leg += " (limit %s)" % _p(order["stop_loss_limit_price"])
            parts.append(leg)
        if order.get("take_profit_limit_price") is not None:
            parts.append("take-profit %s" % _p(order["take_profit_limit_price"]))
        loss, stop = max_loss(order)
        if loss is not None:
            parts.append("max loss about %s if the stop fills at %s, charges included (it can fill worse in a "
                         "fast market)" % (_money(loss), _p(stop)))
        return parts
    q = _str_num(order.get("qty"))
    what = "%s share%s of %s" % (q, "" if q == "1" else "s", sym)
    if typ == "limit":
        how = "limit order at %s" % _money(order.get("limit_price"))
    elif typ == "stop":
        how = "stop order at %s" % _money(order.get("stop_price"))
    elif typ == "stop_limit":
        how = "stop %s, limit %s" % (_money(order.get("stop_price")), _money(order.get("limit_price")))
    else:
        how = "%s order" % typ.replace("_", " ")
    return ["%s %s, %s, %s" % (side, what, how, tif)]


def plain(order):
    """BUY 10 shares of ITC, market order, NSE, delivery (CNC), good for today
    BUY 15 TCS, market, NSE, intraday (MIS), good for today / stop-loss 2419.30 (limit 2407.20) / ..."""
    return " / ".join(plain_parts(order))


def amount_numbers(order):
    nums = []
    for k in ("qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    loss, _ = max_loss(order)
    if loss is not None:
        nums.append(loss)
    return nums


def parse_yes(reply, order, batch_symbols=()):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-z']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" counts (not ok, sure, go, do it)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    sym = str(order.get("symbol", "")).upper()
    tokens = set(re.findall(r"[A-Z0-9][A-Z0-9&\-]{1,19}", raw.upper()))
    others = {s.upper() for s in batch_symbols} - {sym}
    named = tokens & others
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order)
        if not any(abs(n - w) < 0.005 for n in nums for w in want):
            return False, "the reply says %s, but this order is %s" % (
                ", ".join(_str_num(n) for n in nums), plain(order))
    return True, "explicit yes for %s" % plain(order)


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "broker state", required=False) or {"orders": []}


def latest(state, fp, today):
    """The latest decision recorded today for this fingerprint, or None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-in-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today):
    """(ready, label, risk_result)"""
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-in-risk: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        if st == "approved":
            return False, "APPROVED by you at %s, waiting for the Kite orders call" % rec.get("at"), rv
        return False, "DONE: %s at %s" % (st, rec.get("at")), rv
    return True, "READY: trader-in-risk PASS, waiting for your yes", rv


def kind_of(order, rv):
    """entry or exit, as trader-in-risk saw it (older checks: a buy is an entry)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def render(order, idx, total, cfg, risk, state, today):
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
        lines.append("  Reply \"yes\" to place this one order, or \"no\" to skip it.")
        if paper:
            lines.append("  Paper: nothing goes to Kite; the fill is simulated at the current price.")
        else:
            lines.append("  Kite then asks you to approve it in its own form or browser link before it goes to NSE.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    ready, label, rv = status_of(order, risk, state, today)
    loss, stop = max_loss(order)
    return {"index": idx, "ready": ready, "status": label, "plain": plain(order),
            "fingerprint": fingerprint(order), "paper": bool(cfg.get("paper", True)),
            "broker": "kite", "tool": "orders", "tool_input": tool_input(order),
            "exit_tool": "gtt" if is_bracket(order) else None, "exit_input": exit_input(order),
            "why": order.get("why", ""),
            "bracket": is_bracket(order), "max_loss": loss, "stop": stop}


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date):
    """Record a filled order in trader/portfolio.json: cash and shares, with a
    cost-basis lot per buy (oldest lots are relieved first on a sell)."""
    pf = read_json(portfolio_path, "portfolio", required=False)
    if pf is None:
        budget = cfg.get("budget")
        if not budget:
            raise TicketError("no %s yet and no budget in the config to start it from" % portfolio_path)
        pf = {"cash": float(budget), "positions": []}
    symbol = market_in.kite_symbol(symbol)[1]
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("a fill needs a positive qty and price")
    cost = round(qty * price, 2)
    pos = None
    for p in pf.setdefault("positions", []):
        if str(p.get("ticker", "")).upper() == symbol:
            pos = p
    if side == "buy":
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty, "cost": cost})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost, 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("cannot record selling %s %s: the portfolio holds %s"
                              % (_str_num(qty), symbol, pos.get("shares", 0) if pos else 0))
        left = qty
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost, 2)
    write_json(portfolio_path, pf)
    return pf


def log_fill(state_path, now, today, symbol, side, qty, price):
    """A fill in the log, so trader-in-risk sees what was bought and sold today."""
    state = load_state(state_path)
    state.setdefault("orders", []).append({
        "at": local_iso(now), "date": today, "status": "filled", "symbol": market_in.kite_symbol(symbol)[1], "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), market_in.kite_symbol(symbol)[1], _p(price))})
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a):
    now = parse_now(getattr(a, "now", None))
    today = getattr(a, "today", None) or to_local(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today wants a date like 2026-11-23")
    return now, today


def _load(a):
    doc = read_json(a.orders, "orders file (run trader-in-budget, or ticket.py flatten, first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("no orders in %s" % a.orders)
    cfg = read_json(a.config, "config", required=False) or {}
    risk = read_json(a.risk, "risk check", required=False)
    state = load_state(a.state)
    now, today = _clock(a)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("say which order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nOne order at a time: a yes covers one ticket, never the batch. Education and tooling, "
          "not financial advice.")
    return 0 if any_ready else 1


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    ready, label, rv = status_of(order, risk, state, today)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (a.index, label))
    ok, why = parse_yes(a.reply, order, [o.get("symbol", "") for o in orders])
    if not ok:
        print("Not recorded: %s. Ask the user again with the ticket for order %d." % (why, a.index))
        return 1
    loss, stop = max_loss(order)
    rec = {"at": local_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": loss, "stop": stop,
           "plain": plain(order), "status": "approved", "reply": a.reply,
           "paper": bool(cfg.get("paper", True)), "broker": "kite"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded your yes for order %d: %s." % (a.index, plain(order)))
    if cfg.get("paper", True):
        print("PAPER: nothing is sent to Kite. Simulate the fill at the current price (a Kite quote or")
        print("alerts.py quote %s), then: ticket.py result --index %d --status placed --filled-qty %s "
              "--filled-price P" % (order.get("symbol"), a.index, _str_num(order.get("qty"))))
    else:
        print("Now call the Kite orders tool with exactly:")
        print(json.dumps(tool_input(order), indent=2))
        print("Kite asks the user to approve it (its form or a browser link). Share the link; never approve it")
        print("for them. Then: ticket.py result --index %d --status placed|denied|failed --broker-id ORDER_ID"
              % a.index)
    return 0


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    rec = {"at": local_iso(now), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": str(order.get("symbol", "")).upper(), "side": order.get("side"),
           "plain": plain(order), "status": "declined", "reply": a.reply or "no"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded: you said no to order %d (%s). Nothing was sent." % (a.index, plain(order)))
    return 0


def cmd_result(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    fp = fingerprint(order)
    rec = latest(state, fp, today)
    if a.status == "exits-placed":
        if not rec or rec.get("status") not in ("placed", "exits-placed"):
            raise TicketError("order %d has no placed entry today; exits follow a filled entry" % a.index)
    elif not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no yes recorded today; a result can only follow an approval" % a.index)
    new = {"at": local_iso(now), "date": today, "index": a.index, "fingerprint": fp, "symbol": rec["symbol"],
           "side": rec["side"], "plain": rec["plain"], "status": a.status}
    for k in ("qty", "kind", "max_loss", "stop"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    if a.broker_id:
        new["broker_order_id"] = a.broker_id
    if a.note:
        new["note"] = a.note
    state["orders"].append(new)
    write_json(a.state, state)
    print("Recorded order %d as %s." % (a.index, a.status))
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
        print("When the stop-loss or the take-profit fills later, record that sell the same way.")
    return 0


def cmd_fill(a):
    cfg = read_json(a.config, "config", required=False) or {}
    now = parse_now(a.now)
    date = a.date or to_local(now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise TicketError("--date wants a date like 2026-11-23")
    pf = apply_fill(a.portfolio, cfg, a.symbol, a.side, a.qty, a.price, date)
    log_fill(a.state, now, date, a.symbol, a.side, a.qty, a.price)
    print("Recorded %s %s %s at %s on %s in %s. Cash now %s." % (a.side, a.qty, a.symbol.upper(),
                                                                _money(a.price), date, a.portfolio,
                                                                _money(pf["cash"])))
    return 0


def cmd_flatten(a):
    cfg = read_json(a.config, "config", required=False) or {}
    sym = market_in.kite_symbol(a.symbol.strip())[1]
    now, today = _clock(a)
    source = "Kite positions (portfolio mode=positions)"
    if a.qty is not None:
        qty = _f(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty wants the number of shares you hold, like --qty 8")
    else:
        pf = read_json(a.portfolio, "portfolio", required=False) or {}
        qty = sum(_f(p.get("shares", p.get("qty"))) or 0 for p in pf.get("positions", [])
                  if str(p.get("ticker") or p.get("symbol") or "").upper() == sym)
        source = a.portfolio
        if qty <= 1e-9:
            raise TicketError("nothing to flatten: no %s shares in %s. Check Kite (portfolio mode=positions) "
                              "and pass --qty if you do hold some" % (sym, a.portfolio))
    plan = read_json(a.plan, "plan", required=False) or {}
    flat_by = (plan.get("flat_by") if market_in.kite_symbol(str(plan.get("symbol", "")))[1] == sym else None) \
        or cfg.get("flat_by") or market_in.FLAT_BY.strftime("%H:%M")
    product = str(cfg.get("product") or "MIS").upper()
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "exchange": str(cfg.get("exchange") or "NSE").upper(), "product": product,
             "why": "flat by %s IST: closes the %s day trade before Zerodha's MIS square-off at %s (qty from %s)"
             % (flat_by, sym, market_in.square_off_time(market_in.is_fno(sym)).strftime("%H:%M"), source)}
    old = read_json(a.orders, "orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "trader-in-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "paper": bool(cfg.get("paper", True)),
           "note": "Flatten ticket. Nothing is placed until trader-in-risk passes it and you say yes in the chat.",
           "source": "ticket.py flatten %s on %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Flatten %s: %s (flat by %s India)." % (sym, plain(order), flat_by))
    print("Wrote it to %s%s." % (a.orders, (" (it replaced %d earlier proposal%s)"
                                             % (replaced, "" if replaced == 1 else "s")) if replaced else ""))
    if a.qty is None:
        print("The qty comes from %s. Check it against Kite (portfolio mode=positions) before you say yes." % source)
    print("Next:")
    print("  1. trader-in-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order.")
    print("  3. If the bracket's GTT (stop-loss / take-profit) is still active, delete it FIRST (gtt mode=list,")
    print("     then mode=delete with its trigger id), or it can fire after you are out and open a short.")
    print("     Then the Kite orders tool with the ticket. Zerodha auto squares off MIS at %s anyway, for a fee."
          % market_in.square_off_time(market_in.is_fno(sym)).strftime("%H:%M"))
    print("  4. After the close, run ticket.py gtt-check to catch any GTT left behind (for example after an auto")
    print("     square-off).")
    return 0


def _rows(doc, what):
    """Kite answers as saved: {"data": [...]}, a bare list, or {"net": [...], "day": [...]}."""
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        if isinstance(doc.get("data"), list):
            return doc["data"]
        if isinstance(doc.get("data"), dict):
            return _rows(doc["data"], what)
        if isinstance(doc.get("net"), list):
            return [dict(r, view="net") for r in doc["net"]]
    raise TicketError("%s: not a Kite %s answer" % (what, what))


def leftover_gtts(gtts, positions):
    """-> [{id, symbol, sell_qty, held, why, delete}] for active MIS GTTs bigger than the open MIS position."""
    held = {}
    for r in positions:
        if r.get("view") not in (None, "net"):
            continue  # view=day is today's activity, not what is open
        if str(r.get("product") or "").upper() != "MIS":
            continue
        key = (str(r.get("exchange") or "NSE").upper(), str(r.get("tradingsymbol") or "").upper())
        held[key] = held.get(key, 0) + int(float(r.get("quantity") or 0))
    out = []
    for g in gtts:
        status = str(g.get("status") or "active").lower()
        if status != "active":
            continue
        cond = g.get("condition") or {}
        exch = str(cond.get("exchange") or g.get("exchange") or "NSE").upper()
        sym = str(cond.get("tradingsymbol") or g.get("tradingsymbol") or "").upper()
        legs = g.get("orders") or []
        mis = [o for o in legs if str(o.get("product") or "").upper() == "MIS"]
        if not mis:
            continue  # CNC / NRML GTTs belong to holdings or F&O, not to a day trade
        sell = max([int(float(o.get("quantity") or 0)) for o in mis
                    if str(o.get("transaction_type") or "").upper() == "SELL"] or [0])
        if not sell:
            continue
        have = held.get((exch, sym), 0)
        if have >= sell:
            continue
        gid = g.get("id") or g.get("trigger_id")
        why = ("no open MIS position" if have <= 0 else "only %d shares open" % have)
        out.append({"id": gid, "symbol": sym, "exchange": exch, "sell_qty": sell, "held": have,
                    "triggers": cond.get("trigger_values"), "why": why,
                    "delete": {"mode": "delete", "trigger_id": gid}})
    return out


def cmd_gtt_check(a):
    gtts = _rows(read_json(a.gtts, "gtt list"), "gtt list")
    positions = _rows(read_json(a.positions, "positions"), "positions")
    left = leftover_gtts(gtts, positions)
    if a.json:
        print(json.dumps({"leftover": left}, indent=2))
        return 1 if left else 0
    if not left:
        print("No leftover GTTs: every active MIS stop/target GTT is covered by an open MIS position.")
        return 0
    print("LEFTOVER GTTs: %d. Each can fire with no shares behind it and open a short:" % len(left))
    for g in left:
        trig = ", ".join("%.2f" % float(t) for t in (g["triggers"] or []))
        print("  %s %s: GTT %s sells %d (%s), triggers %s" % (g["exchange"], g["symbol"], g["id"], g["sell_qty"],
                                                          g["why"], trig or "?"))
    print("Delete each with the Kite gtt tool, after the user's yes (one call per GTT):")
    for g in left:
        print("  " + json.dumps(g["delete"]))
    print("Nothing was deleted by this tool.")
    return 1


def cmd_log(a):
    state = load_state(a.state)
    now, today = _clock(a)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("No decisions recorded%s." % ("" if a.all else " today"))
        return 1
    for r in rows:
        extra = (" id " + r["broker_order_id"]) if r.get("broker_order_id") else ""
        reply = (' reply "%s"' % r["reply"]) if r.get("reply") and r["status"] in ("approved", "declined") else ""
        loss = (" max loss %s" % _money(r["max_loss"])) if r.get("max_loss") is not None and r["status"] == "placed" else ""
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-9s %s%s%s%s" % (r.get("at"), idx, r.get("status"), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d placed%s." % (placed, "" if a.all else " today"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order tickets and your yes (trader-in-broker, Zerodha Kite). Never places orders.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="pretend it is this India time, e.g. \"2026-11-23 10:15\"")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in India)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="render the tickets")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="record the user's explicit yes for one order")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word")
    p = sub.add_parser("decline", help="record a no")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("result", help="record what happened: placed, exits-placed, denied, failed")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", required=True, choices=["placed", "exits-placed", "denied", "failed"])
    p.add_argument("--broker-id")
    p.add_argument("--note")
    p.add_argument("--filled-qty")
    p.add_argument("--filled-price")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("fill", help="record a fill in trader/portfolio.json")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--date", help="YYYY-MM-DD (default: today in India)")
    p.add_argument("--now")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json")
    p = sub.add_parser("flatten", help="a sell ticket that closes a symbol's position by flat_by")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="shares you hold, from Kite positions (default: trader/portfolio.json)")
    p.add_argument("--orders", default="trader/orders.json", help="where the ticket is written")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p = sub.add_parser("log", help="today's decisions")
    p.add_argument("--state", default="trader/state/broker.json")
    clock(p)
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("gtt-check", help="find leftover MIS stop/target GTTs with no position behind them")
    p.add_argument("--gtts", required=True, help="Kite gtt mode=list answer, saved as JSON")
    p.add_argument("--positions", required=True, help="Kite portfolio mode=positions answer, saved as JSON")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
                "fill": cmd_fill, "flatten": cmd_flatten, "log": cmd_log,
                "gtt-check": cmd_gtt_check}[a.cmd](a)
    except TicketError as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
