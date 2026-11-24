"""One-off: alerts (alerts.py) US -> NSE specifics, after port_common.py."""
import re, sys
p = sys.argv[1]; t = open(p).read()
def rep(a, b, c=1):
    global t
    assert t.count(a) == c, (t.count(a), a[:80]); t = t.replace(a, b)
def cut(name):
    global t
    m = re.search(r"^def %s\(.*?(?=^\S)" % name, t, re.S | re.M); assert m, name
    t = t[:m.start()] + t[m.end():]

s = t.index('"""Price alerts'); e = t.index('"""', s + 3) + 3
t = t[:s] + '''"""Price alerts and the NSE clock for trader-in-alerts. Standard library only.
Ported from day-trader-skill's US price alerts (MIT).

    python3 alerts.py clock                          # is the NSE open? next open / close
    python3 alerts.py quote TCS --write              # quotes -> trader/prices.json
    python3 alerts.py quote --kite kite_quote.json --write   # official Kite quotes + circuit limits
    python3 alerts.py quote --holdings --write       # every ticker in your portfolio and plan
    python3 alerts.py add --from-plan                # stop, target and flat-by from trader/plan.json
    python3 alerts.py add --symbol TCS --stop 2419.30
    python3 alerts.py add --symbol TCS --target 2491.90
    python3 alerts.py add --at 15:05 --label "flat by" --before-close
    python3 alerts.py add --symbol ITC --pct 3
    python3 alerts.py add --opening-bell
    python3 alerts.py check                          # rings what hit, once; exit 1 if nothing rang
    python3 alerts.py check --now "2026-11-23 15:05" --offline tests/fixtures/trader-in-alerts
    python3 alerts.py list
    python3 alerts.py reset tcs-plan-stop

Rule types:
  above / target  the price is at or above "price"
  below / stop    the price is at or below "price"
  pct_move        the price moved "pct" percent or more from the previous close
                  (or from "ref" if you give one); "direction": "up" or "down"
  opening_bell    the NSE opened today, 9:15 IST (rings once per trading day)
  time            the India clock passed "at" (HH:MM) on a trading day
                  (rings once per trading day); "before_close": true keeps it
                  at least 5 minutes before Zerodha's MIS auto square-off for
                  the rule's stock (15:25, or 15:12 for an F&O stock)

A rule with "date" is only watched on that India date (rules from a plan
are for the plan's day only). An above / below alert rings ONCE and then stays
quiet until you reset it, unless the rule has "rearm": true (it re-arms when
the price crosses back). A pct_move alert rings at most once per day.

Quotes (for alerts only, never for timing an order):
  yahoo   https://query2.finance.yahoo.com/v8/finance/chart/TCS.NS (free,
          delayed, unofficial; falls back to query1 on a 429 or a 5xx; one
          retry with a pause on a 429; one request per ticker, half a second
          apart; the default)
  kite    --kite FILE: a Kite MCP quote response Claude saved (market tool,
          mode=quote, e.g. instruments ["NSE:TCS"]). Official prices, and the
          circuit limits go into trader/prices.json for trader-in-risk.
  --offline DIR reads DIR/yahoo-<TICKER>.json (or .json.gz) instead.

NSE calendar: market_in (shared/nse_holidays.json). A year missing there stops
the clock rather than guess.
"""''' + t[e:]
rep('''    st = {"now_new_york": local.strftime("%Y-%m-%d %H:%M"), "date": d.isoformat(),
          "weekday": local.strftime("%A"), "calendar_known": d.year in CALENDAR_YEARS,
          "open": False, "reason": reason, "early_close": EARLY_CLOSE.get(d.isoformat())}''',
'''    st = {"now_ist": local.strftime("%Y-%m-%d %H:%M"), "date": d.isoformat(),
          "weekday": local.strftime("%A"), "calendar_known": d.year in CALENDAR_YEARS,
          "open": False, "reason": reason}''')
rep('''            st["next_open"] = "%s 09:30" % nd.isoformat()''', '''            st["next_open"] = "%s %s" % (nd.isoformat(), OPEN.strftime("%H:%M"))''')
t = t.replace('status["now_new_york"]', 'status["now_ist"]').replace('st["now_new_york"]', 'st["now_ist"]')
cut("stooq_url"); cut("parse_stooq")
rep('''    return {"symbol": sym.upper(), "price": float(price), "open": opens[0] if opens else None,''',
    '''    return {"symbol": market_in.kite_symbol(sym)[1], "price": float(price), "open": opens[0] if opens else None,''')
rep('''def _offline_text(folder, source, sym):
    ext = "csv" if source == "stooq" else "json"
    base = os.path.join(folder, "%s-%s.%s" % (source, sym, ext))''',
'''def parse_kite(doc):
    """A Kite MCP quote response ({"data": {"NSE:TCS": {...}}}) -> {SYM: quote}, with the
    circuit limits. Kite's ohlc.close is the previous session's close."""
    data = (doc or {}).get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict) or not data:
        raise AlertError("the Kite file has no quotes (save the market tool's mode=quote response)")
    out = {}
    for key, q in data.items():
        if not isinstance(q, dict) or q.get("last_price") is None:
            continue
        sym = market_in.kite_symbol(key.split(":")[-1])[1]
        ohlc = q.get("ohlc") or {}
        when = ""
        ts = q.get("timestamp") or q.get("last_trade_time")
        if ts:
            try:
                dt = datetime.datetime.fromisoformat(str(ts))
                if dt.tzinfo is None:
                    dt = local_to_utc(dt)
                else:
                    dt = (dt - dt.utcoffset()).replace(tzinfo=None)
                when = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                pass
        out[sym] = {"symbol": sym, "price": float(q["last_price"]), "open": ohlc.get("open"),
                    "high": ohlc.get("high"), "low": ohlc.get("low"), "prev_close": ohlc.get("close"),
                    "time": when, "lower_circuit": q.get("lower_circuit_limit"),
                    "upper_circuit": q.get("upper_circuit_limit"), "source": "kite"}
    return out


def _offline_text(folder, source, sym):
    base = os.path.join(folder, "%s-%s.json" % (source, sym))''')
rep('''def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE):
    """{SYM: quote} and [errors]. One request per ticker, with a pause between."""
    quotes, errors = {}, []
    for i, sym in enumerate(symbols):
        sym = sym.upper()
        try:
            if offline:
                text = _offline_text(offline, source, sym)
            else:
                if i and pause:
                    _sleep(pause)
                text = fetch(stooq_url(sym)) if source == "stooq" else fetch_yahoo(sym)
            quotes[sym] = parse_stooq(text, sym) if source == "stooq" else parse_yahoo(text, sym)
        except AlertError as e:
            errors.append(str(e))
    return quotes, errors''',
'''def get_quotes(symbols, source="yahoo", offline=None, pause=PAUSE, kite=None):
    """{SYM: quote} and [errors]. Yahoo: one request per ticker, with a pause between.
    kite: a saved Kite quote response; symbols missing from it are errors."""
    quotes, errors = {}, []
    if kite:
        try:
            with open(kite, encoding="utf-8") as fh:
                got = parse_kite(json.load(fh))
        except (OSError, ValueError) as e:
            raise AlertError("cannot read the Kite quote file %s: %s" % (kite, e))
        for sym in symbols:
            s = market_in.kite_symbol(sym)[1]
            if s in got:
                quotes[s] = got[s]
            else:
                errors.append("%s is not in %s (add NSE:%s to the Kite quote request)" % (s, kite, s))
        return quotes, errors
    for i, sym in enumerate(symbols):
        sym = market_in.kite_symbol(sym)[1]
        try:
            if offline:
                text = _offline_text(offline, source, sym)
            else:
                if i and pause:
                    _sleep(pause)
                text = fetch_yahoo(sym)
            quotes[sym] = parse_yahoo(text, sym)
        except AlertError as e:
            errors.append(str(e))
    return quotes, errors''')
rep('''        detail[s] = {"prev_close": q.get("prev_close"), "time": q.get("time"), "source": q.get("source"),
                     "fetched": stamp}''',
'''        detail[s] = {"prev_close": q.get("prev_close"), "time": q.get("time"), "source": q.get("source"),
                     "fetched": stamp}
        if q.get("upper_circuit") or q.get("lower_circuit"):
            detail[s].update(lower_circuit=q.get("lower_circuit"), upper_circuit=q.get("upper_circuit"))''')
rep('''           "note": ("Delayed quotes for alerts and sizing checks. Your broker's price is the one that fills. "
                    "detail.fetched is when each price was read."),''',
'''           "note": ("Quotes for alerts and sizing checks (Yahoo's are delayed). Your broker's price is the one "
                    "that fills. detail.fetched is when each price was read; Kite quotes add circuit limits."),''')
rep('''def ring_time(rule, status):
    """The time a time rule rings today, moved 3 hours earlier on an early close if "before_close"."""
    at = _hhmm(rule.get("at"))
    if rule.get("before_close") and status.get("early_close"):
        at = (datetime.datetime.combine(datetime.date(2000, 1, 1), at) - datetime.timedelta(hours=3)).time()
    return at''',
'''def ring_time(rule, status):
    """The time a time rule rings today. With "before_close" it is kept at least 5 minutes
    before Zerodha's MIS auto square-off for the rule's stock (15:25; 15:12 for F&O)."""
    at = _hhmm(rule.get("at"))
    if rule.get("before_close"):
        sym = str(rule.get("symbol") or "")
        sq = market_in.square_off_time(market_in.is_fno(sym) if sym else False)
        latest = (datetime.datetime.combine(datetime.date(2000, 1, 1), sq) - datetime.timedelta(minutes=5)).time()
        at = min(at, latest)
    return at''')
rep('''                rings.append({"id": rid, "symbol": "", "message": "Opening bell: the NSE is open (%s India)%s."
                              % (status["now_ist"], (", early close at 1:00 p.m. today, "
                                                          + status["early_close"]) if status.get("early_close") else "")})''',
'''                rings.append({"id": rid, "symbol": "", "message": "Opening bell: the NSE is open (%s IST)."
                              % status["now_ist"]})''')
rep('''                    msg += (" If %s is still open, close it: trader-broker flatten --symbol %s builds the sell "
                            "ticket, then trader-risk and your yes." % (sym, sym))''',
'''                    msg += (" If %s is still open, close it: trader-in-broker flatten --symbol %s builds the sell "
                            "ticket, then trader-in-risk and your yes. Zerodha squares off MIS at %s anyway, for a fee."
                            % (sym, sym, market_in.square_off_time(market_in.is_fno(sym)).strftime("%H:%M")))''')
rep('''        sym = r["symbol"].upper()
        q = quotes.get(sym)''', '''        sym = market_in.kite_symbol(r["symbol"])[1]
        q = quotes.get(sym)''')
rep('''                rings.append({"id": rid, "symbol": sym, "message": "%s %s $%.2f: %s your %s $%s%s."''',
    '''                rings.append({"id": rid, "symbol": sym, "message": "%s %s \\u20b9%.2f: %s your %s \\u20b9%s%s."''')
rep('''                rings.append({"id": rid, "symbol": sym, "message": "%s moved %+.2f%% to $%.2f (from $%.2f)."''',
    '''                rings.append({"id": rid, "symbol": sym, "message": "%s moved %+.2f%% to \\u20b9%.2f (from \\u20b9%.2f)."''')
rep('''        raise AlertError("the plan has no symbol (run trader-exit first)")
    sym = str(plan["symbol"]).upper()''', '''        raise AlertError("the plan has no symbol (run trader-in-exit first)")
    sym = market_in.kite_symbol(str(plan["symbol"]))[1]''')
rep('''            raise AlertError("the plan has no %s (run trader-exit)" % key)''', '''            raise AlertError("the plan has no %s (run trader-in-exit)" % key)''')
rep('''    flat = plan.get("flat_by") or cfg_flat_by or "15:55"
    if _hhmm(flat) is None:
        raise AlertError("the plan's flat_by %r is not a time like 15:55" % flat)
    out.append({"id": "%s-flat-by" % sym.lower(), "symbol": sym, "type": "time", "at": flat,
                "label": "flat by close", "before_close": True})''',
'''    flat = plan.get("flat_by") or cfg_flat_by or market_in.FLAT_BY.strftime("%H:%M")
    if _hhmm(flat) is None:
        raise AlertError("the plan's flat_by %r is not a time like 15:05" % flat)
    out.append({"id": "%s-flat-by" % sym.lower(), "symbol": sym, "type": "time", "at": flat,
                "label": "flat by (before the MIS square-off)", "before_close": True})''')
rep('''        syms.append(str(p.get("ticker") or p.get("symbol") or "").upper())''', '''        syms.append(market_in.kite_symbol(str(p.get("ticker") or p.get("symbol") or ""))[1])''')
rep('''        syms.append(str(plan["symbol"]).upper())''', '''        syms.append(market_in.kite_symbol(str(plan["symbol"]))[1])''')
rep('''        print("India %s (%s): NSE %s, %s." % (st["now_ist"], st["weekday"],''', '''        print("India %s IST (%s): NSE %s, %s." % (st["now_ist"], st["weekday"],''')
rep('''            print("Today's session: %s to %s%s." % (st["opens"], st["closes"],
                                                    (" (early close: %s)" % st["early_close"]) if st.get("early_close") else ""))''',
'''            print("Today's session: %s to %s (F&O stocks: continuous trading to %s, then the closing auction)."
                  % (st["opens"], st["closes"], market_in.CAS_CLOSE.strftime("%H:%M")))''')
rep('''            print("Holiday list covers %s only: check nyse.com for this date." % " and ".join(map(str, CALENDAR_YEARS)))''',
    '''            print("Holiday list covers %s only: add this year to shared/nse_holidays.json." % " and ".join(map(str, CALENDAR_YEARS)))''')
rep('''    syms = _dedupe([s.upper() for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms:
        raise AlertError("which tickers? alerts.py quote TSLA KO, or --holdings")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, a.source, a.offline)
    if a.write and quotes:
        write_prices(a.write, quotes, now, a.source)''',
'''    syms = _dedupe([market_in.kite_symbol(s)[1] for s in a.symbols] + (holdings(a) if a.holdings else []))
    if not syms and a.kite:
        with open(a.kite, encoding="utf-8") as fh:
            syms = sorted(parse_kite(json.load(fh)))
    if not syms:
        raise AlertError("which tickers? alerts.py quote TCS ITC, or --holdings, or --kite FILE")
    now = parse_now(a.now)
    quotes, errors = get_quotes(syms, a.source, a.offline, kite=a.kite)
    src = "kite" if a.kite else a.source
    if a.write and quotes:
        write_prices(a.write, quotes, now, src)''')
rep('''                    chg = " (%+.2f%% vs prev close $%.2f)" % (100.0 * (q["price"] / q["prev_close"] - 1), q["prev_close"])
                print("%-6s $%.2f%s  %s  [%s]" % (s, q["price"], chg, q.get("time", ""), q["source"]))''',
'''                    chg = " (%+.2f%% vs prev close \\u20b9%.2f)" % (100.0 * (q["price"] / q["prev_close"] - 1), q["prev_close"])
                circ = ""
                if q.get("upper_circuit"):
                    circ = "  circuit %.2f-%.2f" % (q.get("lower_circuit") or 0, q["upper_circuit"])
                print("%-11s \\u20b9%.2f%s%s  %s  [%s]" % (s, q["price"], chg, circ, q.get("time", ""), q["source"]))''')
rep('''        print("Quotes are free, delayed and unofficial: for alerts only. Your broker's price is the one that fills.")''',
    '''        print("Yahoo quotes are free, delayed and unofficial; Kite's are official. For alerts only: your "
              "broker's price is the one that fills.")''')
rep('''    syms = _dedupe([str(r.get("symbol", "")).upper() for r in watched if r.get("type") not in NO_QUOTE])
    quotes, errors = (get_quotes(syms, a.source, a.offline) if syms else ({}, []))''',
'''    syms = _dedupe([market_in.kite_symbol(str(r.get("symbol", "")))[1] for r in watched
                    if r.get("type") not in NO_QUOTE])
    quotes, errors = (get_quotes(syms, a.source, a.offline, kite=a.kite) if syms else ({}, []))''')
rep('''            write_prices(a.prices_out, quotes, now, a.source)''', '''            write_prices(a.prices_out, quotes, now, "kite" if a.kite else a.source)''')
rep('''                len(watched), (", " + ", ".join("%s $%.2f" % (s, quotes[s]["price"]) for s in syms if s in quotes))''',
    '''                len(watched), (", " + ", ".join("%s \\u20b9%.2f" % (s, quotes[s]["price"]) for s in syms if s in quotes))''')
rep('''            print("An alert is information, not an order. A bracket's stop-loss and take-profit already sit at "
                  "the broker: check get_open_position and record any fill (ticket.py fill). To close a "
                  "position yourself: ticket.py flatten, then trader-risk and your yes.")''',
'''            print("An alert is information, not an order. A live bracket's stop-loss and take-profit already sit "
                  "at Kite as a GTT: check Kite positions and orders and record any fill (ticket.py fill). On "
                  "paper, record the simulated exit the same way. To close a position yourself: ticket.py "
                  "flatten, then trader-in-risk and your yes.")''')
rep('''    ap = argparse.ArgumentParser(description="Price alerts and the NSE clock (trader-alerts).")''',
    '''    ap = argparse.ArgumentParser(description="Price alerts and the NSE clock (trader-in-alerts).")''')
rep('''        p.add_argument("--source", default="yahoo", choices=["yahoo", "stooq"])
        p.add_argument("--offline", metavar="DIR", help="read <source>-<TICKER>.json|csv files, no network")''',
'''        p.add_argument("--source", default="yahoo", choices=["yahoo"])
        p.add_argument("--kite", metavar="FILE", help="a saved Kite quote response (market tool, mode=quote)")
        p.add_argument("--offline", metavar="DIR", help="read yahoo-<TICKER>.json files, no network")''')
rep('''    p.add_argument("--label", help="what a time alert says, e.g. \\"flat by close\\"")
    p.add_argument("--before-close", action="store_true",
                   help="a time alert that moves 3 hours earlier on a 1:00 p.m. early close")''',
'''    p.add_argument("--label", help="what a time alert says, e.g. \\"flat by\\"")
    p.add_argument("--before-close", action="store_true",
                   help="keep a time alert at least 5 minutes before Zerodha's MIS square-off")''')
t = t.replace('$%', '₹%')
open(p, "w").write(t); print("alerts patched")
