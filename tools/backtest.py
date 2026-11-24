#!/usr/bin/env python3
"""Walk-forward backtest of the trader-in-* pipeline, with no look-ahead.

For each stock and each test day it replays the session 5 minutes at a time.
At every step the repo only sees bars that had CLOSED by then (the data file
is cut at that moment and handed to the skill), so no decision can use the
future. The pipeline is the repo's own code, run as the CLIs a user runs:

  entry.py evaluate  -> first close above the 15-minute opening range (orb)
  exit.py plan       -> stop at the range midpoint, target 2R, flat by 15:05
  timemachine.py run -> 10,000 replays from the 60 days BEFORE that day
  size.py            -> shares for the capital, with Indian charges
  check.py           -> the risk check at the decision time

Only after a decision is frozen does the scorer look at the rest of the day
to see what the order would have done:
  fill   the next bar's open (a market order sent when the trigger bar closes)
  stop   a bar whose low reaches the stop exits at the stop (at the open if it
         gapped below); a bar that touches both stop and target counts as the
         stop (conservative)
  target a bar whose high reaches the target exits at the target
  flat   still open at flat_by (15:05): out at the close of the 15:00 bar
  P&L    qty x (exit - fill) - Indian round-trip charges (market_in)

Two ways to use the repo are scored:
  all-signals   every trigger that passes trader-in-risk
  tm-filter     the same, skipping trades the Time Machine rates "toward the stop"

    python3 tools/backtest.py --data DIR --out DIR --capital 5000 \\
        --stocks HDFCBANK:0.05 RELIANCE:0.10 ETERNAL:0.05 ICICIBANK:0.10 \\
        --days 2026-11-03,2026-11-04,...
"""

import argparse
import datetime as D
import json
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(REPO, "skills")
sys.path.insert(0, os.path.join(REPO, "shared"))
sys.path.insert(0, os.path.join(SK, "trader-in-entry"))
import market_in  # noqa: E402
import entry  # noqa: E402

IST = D.timedelta(hours=5, minutes=30)
EPOCH = D.datetime(1970, 1, 1)
BAR = 300


def utc_of_ist(day, hh, mm):
    return D.datetime.combine(day, D.time(hh, mm)) - IST


def epoch(utc):
    return int((utc - EPOCH).total_seconds())


def truncate(doc, cut_epoch):
    """The chart JSON with only bars that had closed by cut_epoch (start + 5 min <= cut)."""
    r = json.loads(json.dumps(doc["chart"]["result"][0]))
    ts = r["timestamp"]
    keep = [i for i, t in enumerate(ts) if t + BAR <= cut_epoch]
    r["timestamp"] = [ts[i] for i in keep]
    q = r["indicators"]["quote"][0]
    for k in list(q):
        q[k] = [q[k][i] for i in keep]
    m = r.setdefault("meta", {})
    if keep:
        m["regularMarketTime"] = ts[keep[-1]] + BAR
        last = next((q["close"][i] for i in range(len(keep) - 1, -1, -1) if q["close"][i] is not None), None)
        if last is not None:
            m["regularMarketPrice"] = last
    return {"chart": {"result": [r], "error": None}}


def day_bars(doc, day):
    """[(start IST, o, h, l, c)] of the day's bars, sorted."""
    r = doc["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        st = EPOCH + D.timedelta(seconds=t) + IST
        if st.date() == day and t % BAR == 0:
            out.append((st, q["open"][i], q["high"][i], q["low"][i], q["close"][i]))
    return sorted(out)


def run(cmd, cwd):
    p = subprocess.run([sys.executable, "-I"] + cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def score(bars, fill_after, qty, stop, target, flat_by):
    """What the bracket did after the decision. Returns (fill, exit, reason, exit_time)."""
    after = [b for b in bars if b[0] >= fill_after]
    if not after:
        return None, None, "no bars after the signal", None
    fill = after[0][1]
    flat_start = D.datetime.combine(after[0][0].date(), flat_by) - D.timedelta(minutes=5)
    for st, o, h, l, c in after:
        if st > flat_start:
            break
        if o <= stop:
            return fill, o, "stop (gapped)", st
        if l <= stop:
            return fill, stop, "stop", st
        if o >= target:
            return fill, o, "target (gapped)", st
        if h >= target:
            return fill, target, "target", st
        if st == flat_start:
            return fill, c, "flat by %s" % flat_by.strftime("%H:%M"), st + D.timedelta(minutes=5)
    last = [b for b in after if b[0] <= flat_start][-1]
    return fill, last[4], "flat by %s" % flat_by.strftime("%H:%M"), last[0] + D.timedelta(minutes=5)


def one_day(sym, tick, day, doc, capital, outdir, leverage=1):
    rec = {"symbol": sym, "date": day.isoformat(), "status": "no signal"}
    work = os.path.join(outdir, "work", sym, day.isoformat())
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(os.path.join(work, "trader"))
    # leverage > 1: Zerodha MIS margin. The capital is the margin; the position can be up to
    # capital x the stock's MIS leverage (trader-in-budget's "allow_margin"), capped at `leverage`.
    cfg = {"budget": capital, "cash_buffer_pct": 0, "max_position_pct": 100 * leverage,
           "max_order_inr": capital * leverage,
           "min_order_inr": 500, "max_loss_per_trade_inr": 500, "max_daily_loss_inr": 1500,
           "max_trades_per_day": 3, "max_orders_per_day": 10, "min_reward_risk": 1.0, "require_stop": True,
           "no_entries_before": "09:30", "no_entries_after": "15:00", "flat_by": "15:05", "paper": True,
           "product": "MIS", "exchange": "NSE", "include_charges": True, "allow_margin": leverage > 1}
    json.dump(cfg, open(os.path.join(work, "trader", "config.json"), "w"), indent=2)

    # 1. entry: bar by bar, the data cut at each moment
    trig = None
    t = D.datetime.combine(day, D.time(9, 35))
    end = D.datetime.combine(day, D.time(15, 0))
    while t <= end:
        cut = epoch(t - IST)
        chart = entry.parse_chart(json.dumps(truncate(doc, cut)), sym)
        res = entry.evaluate(chart, t - IST, setup="orb", or_minutes=15, interval="5m", cfg=dict(entry.DEFAULTS))
        if res["status"] == "triggered":
            trig = (t, res)
            break
        if res["status"] == "expired":
            break
        t += D.timedelta(minutes=5)
    if not trig:
        rec["reason"] = "no close above the opening range by 15:00"
        return rec
    t, res = trig
    now_s = t.strftime("%Y-%m-%d %H:%M")
    cutfile = os.path.join(work, "chart.json")
    json.dump(truncate(doc, epoch(t - IST)), open(cutfile, "w"))
    rc, out = run([os.path.join(SK, "trader-in-entry", "entry.py"), "check", sym, "--now", now_s,
                   "--offline", cutfile, "--write"], work)
    rec.update(status="signal", signal_time=t.strftime("%H:%M"),
               trigger_price=res["trigger"]["price"] if res.get("trigger") else None,
               or_high=(res.get("opening_range") or {}).get("high"), or_low=(res.get("opening_range") or {}).get("low"))
    if rc != 0:
        rec.update(status="error", reason="entry.py: " + out.strip()[-200:])
        return rec

    # 2. exit plan
    rc, out = run([os.path.join(SK, "trader-in-exit", "exit.py"), "plan", "--tick", str(tick), "--now", now_s,
                   "--write"], work)
    if rc != 0:
        rec.update(status="no trade", reason="exit plan refused: " + out.strip().splitlines()[-1][:200])
        return rec
    plan = json.load(open(os.path.join(work, "trader", "plan.json")))
    rec.update(entry=plan["entry"], stop=plan["stop"], target=plan["target"], risk_per_share=plan["risk_per_share"])

    # 3. time machine (history strictly before this day, in the cut file)
    rc, out = run([os.path.join(SK, "trader-in-timemachine", "timemachine.py"), "run", "--offline", cutfile,
                   "--now", now_s, "--write"], work)
    tm_path = os.path.join(work, "trader", "timemachine.json")
    if rc == 0 and os.path.exists(tm_path):
        tm = json.load(open(tm_path))
        mc = tm["mc"]
        rec.update(tm_verdict=tm["verdict"].split(":")[0], tm_p_target=mc["p_target"], tm_p_stop=mc["p_stop"],
                   tm_avg_R_net=mc.get("avg_R_net"), tm_sessions=mc.get("pool_sessions"))
    else:
        rec.update(tm_verdict="not run: " + out.strip().splitlines()[-1][:160] if out.strip() else "not run")

    # 4. budget
    rc, out = run([os.path.join(SK, "trader-in-budget", "size.py"), "--now", now_s, "--write"], work)
    if rc != 0:
        last = [l for l in out.splitlines() if l.startswith("No order") or "size.py:" in l]
        rec.update(status="no trade", reason="budget: " + (last[-1] if last else out.strip()[-160:]))
        return rec
    order = json.load(open(os.path.join(work, "trader", "orders.json")))["orders"][0]
    qty = int(order["qty"])

    # 5. risk
    rc, out = run([os.path.join(SK, "trader-in-risk", "check.py"), "--now", now_s], work)
    risk = json.load(open(os.path.join(work, "trader", "state", "risk.json")))["results"][0]
    rec.update(qty=qty, risk_verdict=risk["verdict"], risk_reasons=risk["reasons"],
               planned_max_loss=risk.get("max_loss"))
    if risk["verdict"] != "PASS":
        rec.update(status="blocked", reason="; ".join(risk["reasons"]))
        return rec

    # 6. score with the rest of the day (the decision is frozen now)
    fill, exit_px, why, when = score(day_bars(doc, day), t, qty, plan["stop"], plan["target"],
                                     D.time(*map(int, plan["flat_by"].split(":"))))
    if fill is None:
        rec.update(status="no trade", reason=why)
        return rec
    costs = float(market_in.round_trip_costs(fill, exit_px, qty)["total"])
    gross = round(qty * (exit_px - fill), 2)
    rec.update(status="traded", fill=round(fill, 2), exit=round(exit_px, 2), exit_reason=why,
               exit_time=when.strftime("%H:%M") if when else None, invested=round(qty * fill, 2),
               gross_pnl=gross, charges=round(costs, 2), net_pnl=round(gross - costs, 2),
               r_multiple=round((exit_px - fill) / plan["risk_per_share"], 2) if plan["risk_per_share"] else None,
               tm_skip=("toward the stop" in (rec.get("tm_verdict") or "").lower()))
    return rec


def main():
    ap = argparse.ArgumentParser(description="Walk-forward backtest of the trader-in-* pipeline")
    ap.add_argument("--data", required=True, help="folder with <SYMBOL>.json Yahoo 60d 5m charts")
    ap.add_argument("--out", required=True)
    ap.add_argument("--capital", type=float, default=5000)
    ap.add_argument("--leverage", type=float, default=1, help="MIS leverage cap (5 = Zerodha's 5x); 1 = cash only")
    ap.add_argument("--stocks", nargs="+", required=True, help="SYMBOL:TICK")
    ap.add_argument("--days", required=True, help="comma-separated YYYY-MM-DD")
    a = ap.parse_args()
    days = [D.date.fromisoformat(x) for x in a.days.split(",")]
    rows = []
    for s in a.stocks:
        sym, tick = s.split(":")
        doc = json.load(open(os.path.join(a.data, sym + ".json")))
        for d in days:
            r = one_day(sym, float(tick), d, doc, a.capital, a.out, a.leverage)
            rows.append(r)
            print("%s %s %-9s %s" % (sym, d, r["status"], r.get("exit_reason") or r.get("reason") or ""), flush=True)
    json.dump({"capital_per_stock": a.capital, "leverage": a.leverage, "days": [d.isoformat() for d in days], "rows": rows,
               "generated": D.datetime.now().isoformat(timespec="seconds")},
              open(os.path.join(a.out, "results.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
