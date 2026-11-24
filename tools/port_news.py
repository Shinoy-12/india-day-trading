"""One-off: news (news.py) SEC EDGAR -> NSE corporate filings RSS, after port_common.py."""
import re, sys
p = sys.argv[1]; t = open(p).read()
def rep(a, b, c=1):
    global t
    assert t.count(a) == c, (t.count(a), a[:80]); t = t.replace(a, b)
def cut(name):
    global t
    m = re.search(r"^def %s\(.*?(?=^\S)" % name, t, re.S | re.M); assert m, name
    t = t[:m.start()] + t[m.end():]

s = t.index('"""News monitor'); e = t.index('"""', s + 3) + 3
t = t[:s] + '''"""News monitor for trader-in-news (NSE). Standard library only.
Ported from day-trader-skill's US news monitor (MIT).

Watches headlines and NSE corporate filings for the stocks you watch or hold
and prints only what is new since the last check, newest first, with how far
each stock has moved today and a flag on anything that touches your tickers.

    python3 news.py                                  # watchlist + plan + portfolio tickers
    python3 news.py --tickers TCS INFY RELIANCE
    python3 news.py --tickers TCS --all --hours 72   # everything in the last 3 days, seen or not
    python3 news.py --no-nse                         # headlines only
    python3 news.py --no-moves                       # skip the price line per ticker

Your tickers, when --tickers is not given: every hit in trader/watchlist.json
(trader-in-scanner), the symbol in trader/plan.json (trader-in-exit) and the
positions in trader/portfolio.json.

Sources:
  - Yahoo Finance headline RSS, one request per ticker:
    https://feeds.finance.yahoo.com/rss/2.0/headline?s=<TICKER>.NS&region=IN&lang=en-IN
  - NSE corporate filings, NSE's public RSS feeds (one request per feed for
    the whole market, filtered to your tickers): announcements, financial
    results, board meetings and corporate actions (dividends, splits, bonus):
    https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml
    These feeds roll: they hold the latest filings only, so run news.py
    often while you trade. A filing is matched to your ticker by the symbol in
    its document link, or by the company name from NSE's equity list
    (EQUITY_L.csv, cached in trader/cache/ for a day).
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<TICKER>.NS?range=1d&interval=5m

Times print in India time (IST). State: trader/state/news.json remembers
what you have seen (30 days), so an item shows once. Offline: --offline DIR
reads yahoo-<TICKER>.xml, chart-<TICKER>.json, nse-<feed>.xml and
EQUITY_L.csv from DIR. The tests use it.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""''' + t[e:]
rep('''YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"''',
    '''YAHOO = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=IN&lang=en-IN"''')
s = t.index('SEC_FEED = ('); e = t.index('KEEP_DAYS = 30')
t = t[:s] + '''NSE_RSS = "https://nsearchives.nseindia.com/content/RSS/%s.xml"
NSE_FEEDS = {"announcements": "Online_announcements", "results": "Financial_Results",
             "board": "Board_Meetings", "actions": "Corporate_action"}
EQUITY_L_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
EQUITY_L_CACHE = "trader/cache/EQUITY_L.csv"
BROWSER_UA = "Mozilla/5.0 (compatible; india-day-trader-skill)"
''' + t[e:]
s = t.index('ITEMS_8K = {'); e = t.index('KEYWORDS = [')
t = t[:s] + '''# NSE filing subjects that move a stock: flagged "!" like the US 8-K items were.
IMPORTANT = re.compile(r"financial result|outcome of board|acquisition|amalgamation|merger|resignation|"
                       r"insolvency|NCLT|default|delay in payment|credit rating|fraud|pledge|"
                       r"buyback|bonus|split|delisting|trading window|SEBI order", re.I)
''' + t[e:]
rep('''    ("earnings", r"\\bearnings\\b|\\bresults\\b|\\bEPS\\b|\\bguidance\\b|\\bforecast\\b"),
    ("analyst", r"\\bupgrade[sd]?\\b|\\bdowngrade[sd]?\\b|price target|\\boutperform\\b|\\bunderperform\\b"),
    ("legal", r"\\blawsuit\\b|\\bsued\\b|\\bprobe\\b|\\binvestigation\\b|\\bSEC charges\\b|\\bantitrust\\b|\\bjudge\\b|\\bcourt\\b"),
    ("deal", r"\\bacqui(?:re|res|red|sition)\\b|\\bmerger\\b|\\bbuyout\\b|\\btakeover\\b|\\bdeal\\b"),
    ("capital", r"\\bdividend\\b|\\bbuyback\\b|\\brepurchase\\b|\\bstock split\\b|\\boffering\\b"),
    ("people", r"\\bCEO\\b|\\bCFO\\b|\\bresign|\\bsteps down\\b|\\bappoint"),
    ("risk", r"\\brecall\\b|\\bbankrupt|\\bdefault\\b|\\bdelist|\\bhack|\\bbreach\\b|\\boutage\\b"),
    ("halt", r"\\bhalt(?:s|ed)?\\b|\\btrading (?:pause|suspen)"),
    ("regulatory", r"\\bFDA\\b|\\bapproval\\b|\\bapproves\\b|\\bclinical\\b|\\bFTC\\b|\\bDOJ\\b"),
    ("macro", r"\\bFed\\b|\\bFOMC\\b|\\bCPI\\b|\\binflation\\b|\\bjobs report\\b|\\bpayrolls\\b|\\btariffs?\\b|\\bfutures\\b"),''',
'''    ("earnings", r"\\bearnings\\b|\\bresults\\b|\\bEPS\\b|\\bguidance\\b|\\bprofit\\b|\\bQ[1-4]\\b|\\bPAT\\b"),
    ("analyst", r"\\bupgrade[sd]?\\b|\\bdowngrade[sd]?\\b|target price|price target|\\boutperform\\b|\\bunderperform\\b|\\bbuy rating\\b|\\bsell rating\\b"),
    ("legal", r"\\blawsuit\\b|\\bprobe\\b|\\binvestigation\\b|\\bNCLT\\b|\\bcourt\\b|\\bED\\b raid|\\bCBI\\b|\\btax demand\\b|\\bpenalty\\b"),
    ("deal", r"\\bacqui(?:re|res|red|sition)\\b|\\bmerger\\b|\\bamalgamation\\b|\\btakeover\\b|\\bdeal\\b|\\border win\\b|\\bbags order\\b"),
    ("capital", r"\\bdividend\\b|\\bbuyback\\b|\\bbonus\\b|\\bsplit\\b|\\brights issue\\b|\\bQIP\\b|\\bOFS\\b|\\bpledge\\b"),
    ("people", r"\\bCEO\\b|\\bCFO\\b|\\bMD\\b|\\bresign|\\bsteps down\\b|\\bappoint"),
    ("risk", r"\\bdefault\\b|\\binsolvency\\b|\\bdelist|\\bfraud\\b|\\bdowngrade of rating\\b|\\bcredit rating\\b|\\boutage\\b"),
    ("halt", r"\\btrading (?:halt|suspen)|\\bsuspension of trading\\b|\\bcircuit\\b"),
    ("surveillance", r"\\bASM\\b|\\bGSM\\b|\\bsurveillance\\b|\\bF&O ban\\b"),
    ("regulatory", r"\\bSEBI\\b|\\bRBI\\b|\\bCCI\\b|\\bUSFDA\\b|\\bFDA\\b|\\bapproval\\b|\\bwarning letter\\b"),
    ("macro", r"\\bRBI policy\\b|\\brepo rate\\b|\\bCPI\\b|\\binflation\\b|\\bGDP\\b|\\bUnion Budget\\b|\\bGST\\b|\\bFIIs?\\b|\\bFPIs?\\b|\\bcrude\\b|\\brupee\\b"),''')
t = t.replace("datetime.timedelta(hours=IST_HOURS)", "_dt.timedelta(hours=IST_HOURS)")
rep('''            out[sym.upper()] = h.get("name")''', '''            out[market_in.kite_symbol(sym)[1]] = h.get("name")''')
rep('''        out.setdefault(pl["symbol"].upper(), pl.get("name"))''', '''        out.setdefault(market_in.kite_symbol(pl["symbol"])[1], pl.get("name"))''')
rep('''            out[sym.upper()] = p.get("name") or out.get(sym.upper())''',
    '''            s = market_in.kite_symbol(sym)[1]
            out[s] = p.get("name") or out.get(s)''')
cut("sec_user_agent")
rep('''    def __init__(self, sec_ua=None, offline=None, pause=0.15):
        self.sec_ua = sec_ua
        self.offline = offline''', '''    def __init__(self, offline=None, pause=0.15):
        self.offline = offline''')
rep('''    def get(self, url, name, sec=False):''', '''    def get(self, url, name):''')
rep('''        if sec and not self.sec_ua:
            raise NewsError("no SEC User-Agent set")
''', '')
rep('''        headers = {"User-Agent": self.sec_ua if sec else BROWSER_UA, "Accept-Encoding": "gzip"}''',
    '''        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"}''')
s = t.index("def cik_map(fetcher, state):"); e = t.index("# ---------------------------------------------------------------- parsing")
t = t[:s] + '''def _norm_name(name):
    """'Tata Consultancy Services Limited' -> 'tata consultancy services'."""
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\\b(limited|ltd|the|india|co|company|corporation|corp|inc)\\b", " ", n)
    return " ".join(n.split())


def nse_names(fetcher, cache=EQUITY_L_CACHE):
    """{SYMBOL: company name} from NSE's EQUITY_L.csv, cached for a day."""
    import csv
    import io
    text = None
    if fetcher.offline:
        text = fetcher.get(EQUITY_L_URL, "EQUITY_L.csv").decode("utf-8", "replace")
    elif cache and os.path.isfile(cache) and time.time() - os.path.getmtime(cache) < 86400:
        with open(cache, encoding="utf-8") as fh:
            text = fh.read()
    if text is None:
        text = fetcher.get(EQUITY_L_URL, "EQUITY_L.csv").decode("utf-8", "replace")
        if cache:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache, "w", encoding="utf-8") as fh:
                fh.write(text)
    rows = list(csv.reader(io.StringIO(text.lstrip("\\ufeff"))))
    if not rows:
        return {}
    hdr = [h.strip() for h in rows[0]]
    si, ni = hdr.index("SYMBOL"), hdr.index("NAME OF COMPANY")
    return {r[si].strip(): r[ni].strip() for r in rows[1:] if len(r) > max(si, ni)}


''' + t[e:]
cut("parse_sec_atom")
rep('''def parse_chart(data, ticker):''', '''def parse_nse_rss(data, feed, watch, names):
    """An NSE filings RSS feed (the whole market) -> items for your tickers only."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("NSE %s feed is not valid XML: %s" % (feed, exc))
    by_name = {}
    for sym in watch:
        n = _norm_name(watch.get(sym) or names.get(sym))
        if n:
            by_name[n] = sym
    out = []
    for it in root.iter("item"):
        company = _text(it, "title")
        link = _text(it, "link")
        desc = _text(it, "description")
        m = re.search(r"/corporate/([A-Z0-9&\\-]+?)_\\d", link)
        sym = m.group(1) if m and m.group(1) in watch else by_name.get(_norm_name(company))
        if not sym:
            continue
        subject = desc.split("SUBJECT:", 1)[1].strip() if "SUBJECT:" in desc else desc[:160]
        title = "%s: %s" % (company.strip(), subject)
        guid = _text(it, "guid") or ("%s|%s|%s" % (link, company, _text(it, "pubDate")))
        out.append({"id": "nse:%s:%s" % (feed, guid), "source": "NSE filing", "kind": "filing", "form": feed,
                    "ticker": sym, "title": title, "summary": desc, "important": bool(IMPORTANT.search(desc)),
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_chart(data, ticker):''')
rep('''                r"\\b(?:NSE|NASDAQ|Nasdaq)\\s*:\\s*%s\\b" % re.escape(t)]''', '''                r"\\b(?:NSE|BSE)\\s*:\\s*%s\\b" % re.escape(t)]''')
rep('''        if it["kind"] == "filing" and "2.02" in it.get("items", []) and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")''', '''        if it["kind"] == "filing" and it.get("form") == "results" and "earnings" not in it["tags"]:
            it["tags"].insert(0, "earnings")''')
s = t.index("def collect(fetcher, watch, state, sec=True"); e = t.index("def select(")
t = t[:s] + '''def collect(fetcher, watch, state, nse=True, feeds=tuple(NSE_FEEDS), errors=None):
    errors = [] if errors is None else errors
    items = []
    for t in sorted(watch):
        try:
            items += parse_rss(fetcher.get(YAHOO % yahoo_symbol(t), "yahoo-%s.xml" % t), t)
        except NewsError as exc:
            errors.append("headlines for %s: %s" % (t, exc))
    if nse:
        try:
            names = nse_names(fetcher)
        except NewsError as exc:
            errors.append("NSE equity list (company names): %s" % exc)
            names = {}
        for feed in feeds:
            try:
                data = fetcher.get(NSE_RSS % NSE_FEEDS[feed], "nse-%s.xml" % feed)
                items += parse_nse_rss(data, feed, watch, names)
            except NewsError as exc:
                if not (fetcher.offline and "no file" in str(exc)):
                    errors.append("NSE %s feed: %s" % (feed, exc))
    return items


''' + t[e:]
rep('''        out.append("%-6s %s %+.2f%% vs yesterday's close %s%s  %s" % (''', '''        out.append("%-11s %s %+.2f%% vs yesterday's close %s%s  %s" % (''')
rep('''        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"]))''',
    '''        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"][:160]))''')
rep('''    ap.add_argument("--forms", default="8-K", help="SEC forms to watch, comma separated")
    ap.add_argument("--no-sec", action="store_true", help="headlines only")''',
'''    ap.add_argument("--feeds", default=",".join(NSE_FEEDS),
                    help="NSE filing feeds, comma separated (%s)" % ", ".join(NSE_FEEDS))
    ap.add_argument("--no-nse", action="store_true", help="headlines only")''')
rep('''    ap.add_argument("--user-agent", help="SEC User-Agent: \\"Your Name you@example.com\\"")
    ap.add_argument("--config", default="trader/config.json")
''', '')
rep('''        watch = {t.upper(): None for t in args.tickers}''', '''        watch = {market_in.kite_symbol(t)[1]: None for t in args.tickers}''')
rep('''    ua = sec_user_agent(args.user_agent, args.config)
    sec = not args.no_sec
    if sec and not ua and not args.offline:
        errors.append("SEC filings skipped: set sec_user_agent in trader/config.json or "
                      "SEC_USER_AGENT (\\"Your Name you@example.com\\") to include them")
        sec = False
    fetcher = Fetcher(ua, offline=args.offline)
    forms = [f.strip().upper() for f in args.forms.split(",") if f.strip()]
    items = collect(fetcher, watch, state, sec=sec, forms=forms, errors=errors)''',
'''    fetcher = Fetcher(offline=args.offline)
    feeds = [f.strip().lower() for f in args.feeds.split(",") if f.strip()]
    bad = [f for f in feeds if f not in NSE_FEEDS]
    if bad:
        print("news: unknown feed(s) %s; use %s" % (", ".join(bad), ", ".join(NSE_FEEDS)), file=sys.stderr)
        return 2
    items = collect(fetcher, watch, state, nse=not args.no_nse, feeds=feeds, errors=errors)''')
open(p, "w").write(t); print("news patched")
