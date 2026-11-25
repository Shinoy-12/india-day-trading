#!/usr/bin/env python3
"""Auto-paper: one fast, rule-based pass of the trader-in-* pipeline (PAPER ONLY).

  python3 trader/auto_paper.py tick    # manage open paper trades, then look for one new entry
  python3 trader/auto_paper.py close   # 15:05: close everything, write the day summary
  python3 trader/auto_paper.py morning # 09:10: news on the top stocks, writes "Avoid today"
  python3 trader/auto_paper.py ledger  # paper P&L per stock across all days (trader/paper_ledger.csv)

Calls the skill scripts directly (no LLM steps), so a tick takes about a minute.
Never calls Kite. Stops if config.json is not paper-only.
Standing instruction from the user, 2026-11-24 ("option 1"): record trades that PASS
trader-in-risk as simulated paper fills while they are away. Paper only.
"""
import csv, io, json, os, re, subprocess, sys, time, urllib.request, zipfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "trader")
SK = os.path.expanduser("~/.claude/skills")
IST = timezone(timedelta(hours=5, minutes=30))
STATE = os.path.join(T, "state", "auto_paper.json")
LEDGER = os.path.join(T, "paper_ledger.csv")
LEDGER_COLS = ["date", "symbol", "qty", "entry", "exit", "exit_why", "gross_pnl", "charges", "net_pnl"]
AVOID_TAGS = {"earnings", "risk", "surveillance", "regulatory"}
REPLY = "AUTO-PAPER: standing instruction 2026-11-24 'option 1' (paper only)"
TOP_N = 50           # most-traded stocks to scan
MAX_CANDIDATES = 5   # entry checks per tick
FRESH_MIN = 20       # a breakout older than this is stale

# Entry filters. Tested in backtest-2026-11/orb_filters.py (60 sessions, top 50 stocks, 1,718 breakouts):
# base ORB lost -0.12R a trade after charges. Only the sector filter moved it the right way, so only it is on.
FILTERS = {
    "realistic_fill": True,       # fix 3: fill at the latest closed bar's close when the run happens
    "sector_trend": True,         # sector index above its range mid today AND above its 20-day avg (+0.017R vs -0.067R)
    "nifty_above_or_mid": False,  # fix 1: tested, no help (-0.125R vs -0.119R)
    "min_volume_x": 0,            # fix 2: 1.5 tested, worse (-0.153R); 0 = off
    "tm_min_avg_r_net": 0.0,      # fix 4: 0.05 on the history tested worse (-0.233R); keep the plain not-negative rule
}

sys.path.insert(0, os.path.join(SK, "trader-in-scanner"))
import market_in  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "trader"))
import sectors  # noqa: E402

# AUTO_PAPER_NOW="2026-11-25 11:20" replays a past moment of a session (for testing).
NOW_ARG = os.environ.get("AUTO_PAPER_NOW")
now = datetime.strptime(NOW_ARG, "%Y-%m-%d %H:%M").replace(tzinfo=IST) if NOW_ARG else datetime.now(IST)
today = now.date().isoformat()
REPORT = os.path.join(T, "reports", today + ".md")


def log(line):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    new = not os.path.exists(REPORT)
    with open(REPORT, "a") as f:
        if new:
            f.write("# Paper trading report: %s\n" % today)
        f.write(line + "\n")
    print(line)


def run(script, *args, js=False):
    if NOW_ARG:
        args = (*args, "--now", NOW_ARG)
    p = subprocess.run([sys.executable, os.path.join(SK, script), *args], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    if js:
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {"error": (p.stderr or p.stdout).strip()[-400:]}
    return p.returncode, (p.stdout + p.stderr).strip()


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(st, f, indent=1)


def bars(sym):
    """Today's 5-minute Yahoo bars: list of (datetime IST, high, low, close)."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s.NS?interval=5m&range=1d" % sym.replace("&", "%26")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=20))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(r.get("timestamp") or []):
        if None in (q["high"][i], q["low"][i], q["close"][i]):
            continue
        d = datetime.fromtimestamp(ts, IST)
        if d + timedelta(minutes=5) <= now:  # closed bars only
            out.append((d, q["high"][i], q["low"][i], q["close"][i]))
    return out


def guard():
    cfg = load(os.path.join(T, "config.json"), {})
    if cfg.get("paper") is not True or any(cfg.get(k) for k in ("allow_margin", "allow_short", "allow_options")):
        log("- %s STOPPED: config.json is not paper-only. Nothing recorded." % now.strftime("%H:%M"))
        sys.exit(2)
    if not market_in.trading_day(now.date()):
        print("NSE closed today.")
        sys.exit(0)
    return cfg


def state():
    st = load(STATE, {})
    if st.get("date") != today:
        st = {"date": today, "trades": [], "skipped": []}
    return st


def avoid_list():
    try:
        text = open(REPORT).read()
    except OSError:
        return set()
    m = re.search(r"### Avoid today\n(.*?)(\n#|\Z)", text, re.S)
    return set(re.findall(r"\*\*([A-Z0-9&-]+)\*\*", m.group(1))) if m else set()


def top_symbols():
    zips = sorted(f for f in os.listdir(os.path.join(T, "bhavcopy")) if f.endswith(".zip"))
    uni = {l.split("|")[0] for l in open(os.path.join(T, "universe.txt")) if l.strip()}
    with zipfile.ZipFile(os.path.join(T, "bhavcopy", zips[-1])) as z:
        rows = csv.DictReader(io.TextIOWrapper(z.open(z.namelist()[0])))
        eq = [(float(r["TtlTrfVal"] or 0), r["TckrSymb"]) for r in rows
              if r["SctySrs"] == "EQ" and r["TckrSymb"] in uni]
    return [s for _, s in sorted(eq, reverse=True)[:TOP_N]]


def exit_trade(st, t, price, why):
    rc, out = run("trader-in-broker/ticket.py", "fill", "--symbol", t["symbol"], "--side", "sell",
                  "--qty", str(t["qty"]), "--price", "%.2f" % price)
    t.update(open=False, exit_price=round(price, 2), exit_why=why, exit_time=now.strftime("%H:%M"),
             pnl=round((price - t["entry"]) * t["qty"] - t.get("charges", 0), 2))
    if rc == 0:
        ledger_add(t)
    log("- %s EXIT %s %d @ %.2f (%s). P&L after est. charges: Rs %.2f%s" %
        (now.strftime("%H:%M"), t["symbol"], t["qty"], price, why, t["pnl"], "" if rc == 0 else " [fill error: %s]" % out))


def ledger_add(t):
    new = not os.path.exists(LEDGER)
    with open(LEDGER, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LEDGER_COLS)
        gross = round((t["exit_price"] - t["entry"]) * t["qty"], 2)
        w.writerow([today, t["symbol"], t["qty"], t["entry"], t["exit_price"], t["exit_why"],
                    gross, t.get("charges", 0), round(gross - t.get("charges", 0), 2)])


def ledger_report():
    """Per-stock totals across every paper day, biggest winner first."""
    try:
        rows = list(csv.DictReader(open(LEDGER)))
    except OSError:
        return "No paper trades in the ledger yet."
    by = {}
    for r in rows:
        b = by.setdefault(r["symbol"], [0, 0, 0, 0.0])
        net = float(r["net_pnl"])
        b[0] += 1; b[1] += net > 0; b[2] += net <= 0; b[3] += net
    lines = ["| Stock | Trades | Wins | Losses | Net P&L (Rs) |", "|---|---|---|---|---|"]
    for sym, (n, w, l, net) in sorted(by.items(), key=lambda kv: -kv[1][3]):
        lines.append("| %s | %d | %d | %d | %+.2f |" % (sym, n, w, l, net))
    tot = sum(b[3] for b in by.values())
    days = len({r["date"] for r in rows})
    lines.append("| **Total** | %d | %d | %d | **%+.2f** |" % (len(rows), sum(b[1] for b in by.values()),
                                                              sum(b[2] for b in by.values()), tot))
    return "%s\n\n%d paper trading day(s) with trades, since %s." % ("\n".join(lines), days, rows[0]["date"])


def morning():
    syms = [s for s in top_symbols()]
    rc, d = run("trader-in-news/news.py", "--tickers", *syms, "--hours", "24", "--json", js=True)
    log("\n## Morning news (%s)" % now.strftime("%H:%M"))
    if "error" in d:
        log("- news check failed: %s" % d["error"])
        return
    bad = {}
    for it in d.get("items", []):
        tags = set(it.get("tags") or []) & AVOID_TAGS
        for sym in it.get("touches") or [it.get("ticker")]:
            if tags and sym in syms:
                bad.setdefault(sym, set()).update(tags)
    log("- %d news items on the top %d stocks." % (len(d.get("items", [])), len(syms)))
    up, down = [], []
    for t in sorted(set(sectors.INDUSTRY_INDEX.values()) | {"^NSEBANK"}):
        try:
            tr = sectors.trend_20d(t, now.date())
        except Exception:  # noqa: BLE001
            tr = None
        if tr is not None:
            (up if tr else down).append(sectors.INDEX_NAMES.get(t, t))
    log("- Sectors above their 20-day average (longs allowed): %s" % (", ".join(up) or "none"))
    log("- Sectors below it (longs skipped today): %s" % (", ".join(down) or "none"))
    log("### Avoid today")
    for sym, tags in sorted(bad.items()):
        log("- **%s**: %s" % (sym, ", ".join(sorted(tags))))
    if not bad:
        log("- none")


def manage(st):
    for t in [t for t in st["trades"] if t["open"]]:
        try:
            bs = [b for b in bars(t["symbol"]) if b[0] >= datetime.fromisoformat(t["entry_bar_end"])]
        except Exception as e:  # noqa: BLE001
            log("- %s could not fetch bars for %s: %s" % (now.strftime("%H:%M"), t["symbol"], e))
            continue
        for ts, hi, lo, _ in bs:
            if lo <= t["stop"]:
                exit_trade(st, t, t["stop"], "stop hit in the %s bar" % ts.strftime("%H:%M"))
                break
            if hi >= t["target"]:
                exit_trade(st, t, t["target"], "target hit in the %s bar" % ts.strftime("%H:%M"))
                break


def try_entry(st, cfg):
    hm = now.strftime("%H:%M")
    if not (cfg.get("no_entries_before", "09:30") <= hm <= cfg.get("no_entries_after", "15:00")) or hm < "09:35":
        return
    done = [t for t in st["trades"]]
    loss = -sum(min(t.get("pnl", 0), 0) for t in done)
    if len(done) >= cfg.get("max_trades_per_day", 3) or loss >= cfg.get("max_daily_loss_inr", 600):
        print("Daily trade or loss limit reached; no new entries.")
        return
    if any(t["open"] for t in done):
        print("A paper trade is open; one at a time.")
        return
    skip = avoid_list() | {t["symbol"] for t in done}
    syms = [s for s in top_symbols() if s not in skip]
    orb_out = os.path.join(T, "state", "orb_latest.json")
    t0 = time.time()
    rc, out = run("trader-in-scanner/scan.py", "orb", "--symbols", ",".join(syms), "--out", orb_out,
                  "--quiet", "--pause", "0.1", "--max-confirm", "40")
    hits = load(orb_out, {}).get("hits", [])
    rank = {s: i for i, s in enumerate(syms)}
    def fresh(h):
        try:
            at = datetime.strptime(today + " " + h["at"], "%Y-%m-%d %I:%M %p").replace(tzinfo=IST)
        except (KeyError, ValueError):
            return True  # let the entry check decide
        return (now - at).total_seconds() / 60 <= FRESH_MIN
    all_hits = [h for h in hits if h["symbol"] in rank]
    hits = sorted((h for h in all_hits if fresh(h)), key=lambda h: rank[h["symbol"]])
    notes = []
    for h in hits[:MAX_CANDIDATES]:
        sym = h["symbol"]
        rc, ent = run("trader-in-entry/entry.py", "check", sym, "--write", "--json", js=True)
        if ent.get("status") != "triggered":
            notes.append("%s %s" % (sym, ent.get("status") or ent.get("error", "?")))
            continue
        ttime = ent.get("time") or (ent.get("trigger") or {}).get("time")
        trig = datetime.strptime(today + " " + ttime, "%Y-%m-%d %I:%M %p").replace(tzinfo=IST)
        age = (now - trig).total_seconds() / 60
        if age > FRESH_MIN:
            notes.append("%s stale (broke out %s)" % (sym, ttime))
            continue
        if FILTERS["min_volume_x"]:
            rc, ent = run("trader-in-entry/entry.py", "check", sym, "--write", "--json",
                          "--min-volume-x", str(FILTERS["min_volume_x"]), js=True)
            if ent.get("status") != "triggered":
                notes.append("%s volume too light" % sym)
                continue
        if FILTERS["nifty_above_or_mid"]:
            nf = sectors.index_now("^NSEI", now)
            if nf and not nf["above_or_mid"]:
                notes.append("%s skipped: Nifty below its range mid" % sym)
                continue
        if FILTERS["sector_trend"]:
            ok, why = sectors.sector_check(sym, now)
            if not ok:
                notes.append("skipped, sector weak: " + why)
                continue
        else:
            why = sym
        plan_args = ["plan", "--write", "--json"]
        if FILTERS["realistic_fill"]:
            last = bars(sym)
            if last:
                end = last[-1][0] + timedelta(minutes=5)
                plan_args += ["--entry", "%.2f" % last[-1][3], "--time", end.strftime("%I:%M %p").lstrip("0")]
        rc, plan = run("trader-in-exit/exit.py", *plan_args, js=True)
        if rc or "stop" not in plan:
            notes.append("%s exit plan refused: %s" % (sym, str(plan.get("error", plan))[:120]))
            continue
        rc, tm = run("trader-in-timemachine/timemachine.py", "run", "--plan", os.path.join(T, "plan.json"), "--json", "--write", js=True)
        r_net = (tm.get("mc") or {}).get("avg_R_net")
        if r_net is None or r_net < FILTERS["tm_min_avg_r_net"]:
            notes.append("%s skipped: time machine avg R after charges %s" % (sym, r_net))
            continue
        run("trader-in-budget/size.py", "--write")
        rc, risk = run("trader-in-risk/check.py", "--json", js=True)
        res = (risk.get("results") or [{}])[0]
        if res.get("verdict") != "PASS":
            notes.append("%s BLOCKED by risk: %s" % (sym, "; ".join(res.get("reasons", [])) or risk.get("error")))
            continue
        qty = int(float(str(res["amount"]).split()[0]))
        entry = plan["entry"]
        # Paper only: no "yes" is faked through ticket.py approve. The fill is recorded under the
        # user's standing paper instruction (REPLY) and noted in the report.
        rc2, o2 = run("trader-in-broker/ticket.py", "fill", "--symbol", sym, "--side", "buy",
                      "--qty", str(qty), "--price", "%.2f" % entry)
        if rc2:
            log("- %s ERROR recording %s (nothing recorded): %s" % (hm, sym, o2[-200:]))
            return
        bar_end = datetime.strptime(today + " " + plan["entry_time"], "%Y-%m-%d %I:%M %p").replace(tzinfo=IST) \
            if plan.get("entry_time") else trig  # manage bars that start at/after the fill
        st["trades"].append({"symbol": sym, "qty": qty, "entry": entry, "stop": plan["stop"],
                             "target": plan["target"], "entry_bar_end": bar_end.isoformat(),
                             "charges": round(plan.get("est_costs_per_share", 0) * qty, 2), "open": True,
                             "tm_avg_R_net": r_net})
        log("  sector: " + why)
        log("- %s ENTRY (auto-paper, standing instruction) %s %d @ %.2f, stop %.2f, target %.2f (risk PASS, max loss Rs %s; time machine "
            "target-first %.0f%%, stop-first %.0f%%, avg R after charges %+.3f)" %
            (hm, sym, qty, entry, plan["stop"], plan["target"], res.get("max_loss"),
             100 * tm["mc"]["p_target"], 100 * tm["mc"]["p_stop"], r_net))
        break
    else:
        log("- %s no entry. ORB scan of %d stocks (%.0fs) found %d hits, %d fresh. %s" %
            (hm, len(syms), time.time() - t0, len(all_hits), len(hits), "; ".join(notes) or "Nothing fresh."))
        return
    if notes:
        log("  (passed over first: %s)" % "; ".join(notes))


def close(st):
    log("\n## Close (%s)" % now.strftime("%H:%M"))
    board = sectors.sector_board(now)
    if board:
        log("Sectors today (strongest first): " + ", ".join("%s %+.2f%%" % (b["name"], b["pct_today"]) for b in board))
    for t in [t for t in st["trades"] if t["open"]]:
        manage({"trades": [t]})
        if t["open"]:
            run("trader-in-broker/ticket.py", "flatten", "--symbol", t["symbol"])
            exit_trade(st, t, bars(t["symbol"])[-1][3], "flat by 15:05")
    total = sum(t.get("pnl", 0) for t in st["trades"])
    log("\n## Day summary\n%d paper trade(s). Total P&L after est. charges: Rs %.2f" % (len(st["trades"]), total))
    for t in st["trades"]:
        log("- %s %d: in %.2f, out %s (%s), P&L Rs %s" % (t["symbol"], t["qty"], t["entry"], t.get("exit_price"),
                                                       t.get("exit_why"), t.get("pnl")))
    log("\n```\n%s\n```" % run("trader-in-broker/ticket.py", "log")[1])
    log("\n## Paper P&L by stock, all days (trader/paper_ledger.csv)\n" + ledger_report())


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tick"
    if cmd == "ledger":
        print(ledger_report())
        return
    cfg = guard()
    if cmd == "morning":
        morning()
        return
    st = state()
    try:
        if cmd == "close":
            close(st)
        else:
            manage(st)
            try_entry(st, cfg)
    finally:
        save_state(st)


if __name__ == "__main__":
    main()
