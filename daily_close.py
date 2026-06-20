"""End-of-day position flatten.

Scheduled at 15:30 ET (30 min before close):
  1. Cancel all open orders. This includes any unfilled bracket entries
     from late-day strategy ticks — without this, an unfilled order could
     get triggered after close-out and re-open the position overnight.
  2. Close all positions. Alpaca handles the side flip (longs → sell,
     shorts → buy-to-cover) so we don't have to track which is which.

Order matters: cancel orders FIRST, then close positions. Otherwise a
stop-loss leg from an open bracket could fire DURING the close-out and
fight the close orders we're submitting.
"""

import alpaca_trade_api as tradeapi
import config
from datetime import datetime

api = tradeapi.REST(config.API_KEY, config.SECRET_KEY, base_url=config.API_URL)

print(f"[{datetime.now().isoformat()}] daily_close.py starting | Alpaca base_url: {config.API_URL}")

# Step 1: cancel open orders before closing positions. Wrapped in try/except
# so a cancel failure doesn't prevent us from at least attempting the flatten.
try:
    cancel_response = api.cancel_all_orders()
    print(f"Canceled {len(cancel_response) if cancel_response else 0} open orders")
except Exception as e:
    print(f"Failed to cancel orders ({type(e).__name__}): {e}")

# Step 2: flatten. Alpaca handles long-vs-short internally.
# `close_response or []` defends against the API returning None on a no-op day.
try:
    close_response = api.close_all_positions()
    print(f"Submitted close orders for {len(close_response) if close_response else 0} positions")
    for order in close_response or []:
        print(f"  {order.symbol}: {order.side} {order.qty} shares")
except Exception as e:
    print(f"Failed to close positions ({type(e).__name__}): {e}")

print(f"[{datetime.now().isoformat()}] daily_close.py finished")
