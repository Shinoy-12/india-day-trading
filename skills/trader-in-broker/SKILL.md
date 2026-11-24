---
name: trader-in-broker
description: >-
  Order Executor for Zerodha Kite. Sends approved orders to your broker, paper (a local
  simulation, since Kite has no paper account) by default, never without your yes. Shows
  each order as a plain ticket (a bracket shows its stop-loss, take-profit and the max
  loss at the stop, charges included) plus the exact Kite tool inputs: an MIS entry,
  then a GTT two-leg OCO for the stop and target once it fills (Zerodha has no bracket
  orders). Records your yes word for word; in live mode Kite's own approval asks again.
  Builds the sell ticket that closes a day trade before the MIS square-off, records
  fills, and logs each trade's max loss so trader-in-risk can hold the daily limit. Use
  when the user says "place the order", "buy it", "execute", "send it to Kite", "close
  my position", "flatten", "get me out", "connect Zerodha", "set up paper trading", or
  after /trader-in-risk passes.
---

# trader-in-broker

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Leftover GTTs (check every trading day)
A bracket's stop and target sit in a Kite GTT, and a GTT lives across days. The `flatten` steps delete it before closing, but if a position was closed any other way (Zerodha's auto square-off at 15:25, a manual exit in the Kite app), the GTT stays. Its stop leg can then fire with no shares behind it and open a short under MIS.

Run the check after the market closes and again before the first entry of the next day:
1. Kite `gtt` with `mode=list`, and `portfolio` with `mode=positions`. Save each answer as JSON (`trader/state/gtts.json`, `trader/state/positions.json`).
2. `python3 ticket.py gtt-check --gtts trader/state/gtts.json --positions trader/state/positions.json`
3. If it lists LEFTOVER GTTs, show them to the user and ask before deleting. With their yes, call Kite `gtt` with the printed `{"mode": "delete", "trigger_id": ...}`, one call per GTT. Never delete without that yes. GTTs on CNC or NRML (long-term holdings, F&O) are not touched.

## Porting checklist
- [x] Replace Alpaca `place_stock_order` JSON with Kite order params: `exchange`, `tradingsymbol` (via `kite_symbol()`), `transaction_type`, `quantity`, `product: MIS`, `order_type`, `price`/`trigger_price`, `variety`.
- [x] No bracket orders at Zerodha: entry + separate SL-M stop + limit target (or GTT OCO; check whether it supports MIS today). Cancel the other leg when one fills.
- [x] Add a local paper mode (log simulated fills) as the default; Kite has no sandbox.
- [x] Replace the Alpaca MCP setup notes (`claude_desktop_config.example.json`) with the Kite MCP connector; set order tools to "Needs approval".
- [x] Flatten ticket must go out before `SQUARE_OFF`.
- [x] Kite MCP (`market`, `orders`, `gtt`, `portfolio`) replaces Alpaca; refresh `zerodha_mis_margins.json` from zerodha.com/margin-calculator/Equity/ regularly.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
