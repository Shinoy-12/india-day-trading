---
name: trader-in-broker
description: >-
  Order Executor for Zerodha Kite. Shows each order as a plain ticket and the exact Kite order parameters, records your yes word for word, and never sends without it. Simulated (paper) mode by default because Kite has no paper account.
---

# trader-in-broker

**Status: ported to NSE / Zerodha Kite (2026-11-24), tested on 23 Nov 2026 data.** The script's docstring (`--help`) is the reference; the checklist below records what was changed.

## Porting checklist
- [x] Replace Alpaca `place_stock_order` JSON with Kite order params: `exchange`, `tradingsymbol` (via `kite_symbol()`), `transaction_type`, `quantity`, `product: MIS`, `order_type`, `price`/`trigger_price`, `variety`.
- [x] No bracket orders at Zerodha: entry + separate SL-M stop + limit target (or GTT OCO; check whether it supports MIS today). Cancel the other leg when one fills.
- [x] Add a local paper mode (log simulated fills) as the default; Kite has no sandbox.
- [x] Replace the Alpaca MCP setup notes (`claude_desktop_config.example.json`) with the Kite MCP connector; set order tools to "Needs approval".
- [x] Flatten ticket must go out before `SQUARE_OFF`.
- [x] Kite MCP (`market`, `orders`, `gtt`, `portfolio`) replaces Alpaca; refresh `zerodha_mis_margins.json` from zerodha.com/margin-calculator/Equity/ regularly.
- [x] Ported and tested on replayed NSE data (23 Nov 2026). Still to do: a paper run through a live NSE session.
