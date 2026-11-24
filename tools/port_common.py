#!/usr/bin/env python3
"""One-off porting helper: the mechanical US -> NSE changes shared by every
trader-in-* script. Script-specific changes (orders, costs, data sources) are
made by hand afterwards. Kept in the repo so the port is reproducible.

    python3 tools/port_common.py skills/trader-in-entry/entry.py EntryError
"""

import re
import sys

IMPORT_BLOCK = '''
_HERE = os.path.dirname(os.path.abspath(__file__))
# installed: market_in.py sits next to this script (install.sh); repo checkout: ../../shared
for _p in (os.path.join(_HERE, "..", "..", "shared"), _HERE):
    if os.path.isfile(os.path.join(_p, "market_in.py")):
        sys.path.insert(0, _p)
import market_in  # noqa: E402
'''

TIME_BLOCK = '''IST_HOURS = 5.5  # India Standard Time, UTC+5:30, no daylight saving


def local_offset(utc):
    """Hours from UTC for India: always +5.5 (no DST)."""
    return IST_HOURS


def to_local(utc):
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=IST_HOURS)


def local_to_utc(local):
    return local - datetime.timedelta(hours=IST_HOURS)


'''

CALENDAR_BLOCK = '''# NSE calendar, hours and holidays come from market_in (shared/). India has no
# early closes; F&O stocks stop continuous trading at 15:15 (closing auction).
EARLY_CLOSE = {}
CALENDAR_YEARS = tuple(sorted({int(k[:4]) for k in market_in.HOLIDAYS}))
OPEN = market_in.OPEN
CLOSE = market_in.CLOSE
EARLY = market_in.CLOSE
'''


def trading_day_block(err):
    return '''def trading_day(d):
    """(is_trading_day, reason). Weekends and the NSE holiday list (market_in)."""
    try:
        return market_in.trading_day(d)
    except market_in.MarketError as e:
        raise %s(str(e))


def session(d, fno=False):
    """(open_time, close_time) of continuous trading in India time, or None if closed.
    fno=True: F&O stocks stop at the closing-auction start (15:15)."""
    try:
        return market_in.session(d, fno)
    except market_in.MarketError as e:
        raise %s(str(e))


''' % (err, err)


def cut_def(t, name):
    """Remove `def name(...)` and its body (to the next top-level statement)."""
    m = re.search(r"^def %s\(.*?(?=^\S)" % re.escape(name), t, re.S | re.M)
    if not m:
        return t, False
    return t[:m.start()] + t[m.end():], True


def port(path, err):
    t = open(path, encoding="utf-8").read()
    did = []

    # user agent: honest, no URL (NSE refuses the long one)
    t, n = re.subn(r'^UA = ".*"$', 'UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"', t, flags=re.M)
    did.append("UA" if n else "no UA")

    # market_in import after the last top-level stdlib import
    if "import market_in" not in t:
        imps = list(re.finditer(r"^(import \w[\w.]*|from \w[\w.]* import .*)$", t, re.M))
        if "import os" not in t:
            t = t[:imps[0].start()] + "import os\n" + t[imps[0].start():]
            imps = list(re.finditer(r"^(import \w[\w.]*|from \w[\w.]* import .*)$", t, re.M))
        if "import sys" not in t:
            t = t[:imps[0].start()] + "import sys\n" + t[imps[0].start():]
            imps = list(re.finditer(r"^(import \w[\w.]*|from \w[\w.]* import .*)$", t, re.M))
        last = imps[-1]
        t = t[:last.end()] + "\n" + IMPORT_BLOCK + t[last.end():]
        did.append("import")

    # NYSE holiday / early-close tables and session constants
    m = re.search(r"^NYSE_HOLIDAYS = \{.*?^\}\n", t, re.S | re.M)
    if m:
        t = t[:m.start()] + t[m.end():]
        did.append("holidays")
    m = re.search(r"^NYSE_EARLY_CLOSE = \{.*?^\}\n", t, re.S | re.M)
    if m:
        t = t[:m.start()] + CALENDAR_BLOCK + t[m.end():]
        did.append("calendar")
    for pat in (r"^CALENDAR_YEARS = \(.*\)\n", r"^OPEN = datetime\.time\(9, 30\)\n",
                r"^CLOSE = datetime\.time\(16, 0\)\n", r"^EARLY = datetime\.time\(13, 0\)\n"):
        if "EARLY_CLOSE = {}" in t:
            t = re.sub(pat, "", t, flags=re.M)
    t = t.replace("NYSE_EARLY_CLOSE", "EARLY_CLOSE").replace("NYSE_HOLIDAYS", "market_in.HOLIDAYS")

    # New York clock -> IST
    t, a = cut_def(t, "_nth_sunday")
    m = re.search(r"^def eastern_offset\(.*?(?=^\S)", t, re.S | re.M)
    if m:
        t = t[:m.start()] + TIME_BLOCK + t[m.end():]
        did.append("tz")
    for name in ("to_eastern", "eastern_to_utc"):
        t, _ = cut_def(t, name)
    for a_, b_ in (("ts_to_eastern", "ts_to_local"), ("eastern_offset", "local_offset"),
                   ("to_eastern", "to_local"), ("eastern_to_utc", "local_to_utc"),
                   ("ny_iso", "local_iso"), ("ny_now", "local_now")):
        t = re.sub(r"\b%s\b" % a_, b_, t)

    # trading_day / session from market_in
    m0 = re.search(r"^def trading_day\(", t, re.M)
    if m0:
        pos = m0.start()
        t, _ = cut_def(t, "trading_day")
        m = re.search(r"^def session\(.*?(?=^\S)", t, re.S | re.M)
        if m:
            t = t[:m.start()] + trading_day_block(err) + t[m.end():]
        else:  # no session() in this script: put both where trading_day() was
            t = t[:pos] + trading_day_block(err) + t[pos:]
        did.append("session")

    # next_open: the opening time is 09:15
    t = t.replace('return "%s 09:30" % nd.isoformat()', 'return "%s %s" % (nd.isoformat(), OPEN.strftime("%H:%M"))')

    # Yahoo symbols: RELIANCE -> RELIANCE.NS, never the US dot-to-dash
    t = re.sub(r'(def yahoo_symbol\((\w+)\):\n(?:    """[^\n]*"""\n)?)    return [^\n]*\n',
               lambda m: m.group(1) + "    return market_in.yahoo_symbol(%s)\n" % m.group(2), t)
    t = re.sub(r"(\w+)\.upper\(\)\.replace\(\"\.\", \"-\"\)", r"market_in.yahoo_symbol(\1)", t)

    # words
    for a_, b_ in (("New York time", "India time"), ("New York", "India"), ("(ET)", "(IST)"),
                   ("NYSE holiday", "NSE holiday"), ("NYSE", "NSE"),
                   ("/trader-scanner", "/trader-in-scanner"), ("/trader-news", "/trader-in-news"),
                   ("/trader-entry", "/trader-in-entry"), ("/trader-exit", "/trader-in-exit"),
                   ("/trader-timemachine", "/trader-in-timemachine"), ("/trader-budget", "/trader-in-budget"),
                   ("/trader-risk", "/trader-in-risk"), ("/trader-broker", "/trader-in-broker"),
                   ("/trader-alerts", "/trader-in-alerts"), ("/trader-analyst", "/trader-in-analyst")):
        t = t.replace(a_, b_)
    t = re.sub(r"(?<=\d|M) ET\b|(?<=%s) ET\b", " IST", t)   # "10:15 ET", "AM ET", "%s ET" (not "as ET")
    t = re.sub(r'"(created_by)": "trader-(\w+)"', r'"\1": "trader-in-\2"', t)

    open(path, "w", encoding="utf-8").write(t)
    print("%s: %s" % (path, ", ".join(did)))


if __name__ == "__main__":
    port(sys.argv[1], sys.argv[2])
