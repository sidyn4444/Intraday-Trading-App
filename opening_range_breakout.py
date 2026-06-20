"""Opening Range Breakout (long).

For each stock assigned to this strategy:
  1. Define the opening range as the high/low of 09:30-09:45 ET bars.
  2. Wait for the first candle that closes ABOVE the opening range high.
  3. Submit a bracket limit-buy at that close, with:
        take-profit = entry + range
        stop-loss   = entry - range
  4. Skip symbols already in an open order or position so we don't double-up.

Runs every 5 min via cron from 09:46 to 15:25 ET. Daily-close script
flattens anything still open at 15:30.
"""

import sqlite3
import config
import alpaca_trade_api as tradeapi
from datetime import date
import pandas as pd
import smtplib, ssl
from helpers import calculate_quantity

context = ssl.create_default_context()

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

# =========================
# Paper trading run switch
# =========================
# Flip to True to dry-run: everything prints but no orders are submitted.
DRY_RUN = False

def round_to_penny(x: float) -> float:
    """Round to 2 decimals.

    The +1e-9 nudge avoids the classic float case where 0.005 silently
    rounds DOWN to 0.00 because of binary representation.
    """
    return round(float(x) + 1e-9, 2)

# =========================
# Load symbols from DB
# =========================
connection = sqlite3.connect(config.DB_FILE)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

cursor.execute("select id from strategy where name = 'opening_range_breakout'")
row = cursor.fetchone()
strategy_id = row["id"]

# Pull the symbols a user has assigned to this strategy via the dashboard
cursor.execute("""
    select symbol, name
    from stock
    join stock_strategy on stock_strategy.stock_id = stock.id
    where stock_strategy.strategy_id = ?
""", (strategy_id,))
stocks = cursor.fetchall()
symbols = [stock["symbol"] for stock in stocks]

if not symbols:
    raise RuntimeError("No symbols found for strategy 'opening_range_breakout'.")

# =========================
# Alpaca client
# =========================
api = tradeapi.REST(
    config.API_KEY,
    config.SECRET_KEY,
    base_url=config.API_URL
)

print("Alpaca base_url:", config.API_URL)

# Skip any symbol we already have an open order or position on, otherwise
# the cron re-runs every 5 minutes would keep submitting duplicate brackets
# until we hit the buying-power limit
open_orders = api.list_orders(status="open")
open_order_symbols = {o.symbol for o in open_orders}

open_positions = api.list_positions()
open_position_symbols = {p.symbol for p in open_positions if float(p.qty) != 0.0}

blocked_symbols = open_order_symbols | open_position_symbols
if blocked_symbols:
    print("Blocked symbols (open order/position):", sorted(blocked_symbols))

# =========================
# ORB time window in NY time
# =========================
# Using IANA tz name so DST is handled automatically — pinning to a fixed
# UTC offset like -05:00 would silently break in March and November
current_day = date.today().isoformat()
ny_tz = "America/New_York"

start_minute_bar = pd.Timestamp(f"{current_day} 09:30:00", tz=ny_tz)
end_minute_bar   = pd.Timestamp(f"{current_day} 09:45:00", tz=ny_tz)

# Alpaca's bars endpoint wants RFC3339 timestamps. Pulling all bars up to
# 16:00 in one request rather than re-fetching every cron tick.
start_rfc3339 = start_minute_bar.isoformat()
end_rfc3339   = pd.Timestamp(f"{current_day} 16:00:00", tz=ny_tz).isoformat()

messages = []

# =========================
# Strategy loop
# =========================
for symbol in symbols:
    if symbol in blocked_symbols:
        print(f"{symbol}: blocked (open order or open position), skipping")
        continue

    minute_bars = api.get_bars(
        symbol,
        tradeapi.TimeFrame.Minute,
        start=start_rfc3339,
        end=end_rfc3339,
        feed="iex"
    ).df

    if minute_bars.empty:
        print(f"{symbol}: no minute bars returned, skipping")
        continue

    # Alpaca bars come back in UTC. Convert to NY so the comparison against
    # 09:30/09:45 NY timestamps actually means what we think it means.
    if minute_bars.index.tz is None:
        minute_bars.index = minute_bars.index.tz_localize("UTC")
    minute_bars.index = minute_bars.index.tz_convert(ny_tz)

    opening_range_mask = (minute_bars.index >= start_minute_bar) & (minute_bars.index < end_minute_bar)
    opening_range_bars = minute_bars.loc[opening_range_mask]

    if opening_range_bars.empty:
        print(f"{symbol}: opening range bars empty (09:30-09:45), skipping")
        continue

    opening_range_low = float(opening_range_bars["low"].min())
    opening_range_high = float(opening_range_bars["high"].max())
    opening_range = opening_range_high - opening_range_low

    # Bail on degenerate ranges (e.g. halted stocks or feed gaps) so we don't
    # divide by zero or submit a bracket with a 0-distance TP/SL
    if opening_range <= 0:
        print(f"{symbol}: opening range not valid (range={opening_range}), skipping")
        continue

    after_opening_range = minute_bars.loc[minute_bars.index >= end_minute_bar]
    breakout = after_opening_range[after_opening_range["close"] > opening_range_high]

    if breakout.empty:
        print(f"{symbol}: no breakout yet")
        continue

    # First breakout candle is the entry signal — any later candles that also
    # break the range get ignored because we only take one trade per day per symbol
    row0 = breakout.iloc[0]
    print(
        f"{symbol}: breakout candle | "
        f"close={float(row0['close']):.2f} "
        f"high={float(row0['high']):.2f} "
        f"ORH={opening_range_high:.2f}"
    )

    first_breakout_ts = breakout.index[0]
    limit_price = float(row0["close"])

    # Symmetric bracket: 1× range above for TP, 1× range below for SL
    tp = limit_price + opening_range
    sl = limit_price - opening_range

    limit_price = round_to_penny(limit_price)
    tp = round_to_penny(tp)
    # Clamp SL to a penny minimum so Alpaca doesn't reject a sub-cent stop on a penny stock
    sl = max(round_to_penny(sl), 0.01)

    print(
        f"{symbol}: breakout at {first_breakout_ts} | "
        f"ORH={opening_range_high:.2f} ORL={opening_range_low:.2f} R={opening_range:.2f} | "
        f"entry={limit_price:.2f} tp={tp:.2f} sl={sl:.2f}"
    )

    if DRY_RUN:
        print(f"{symbol}: DRY_RUN enabled: skipping submit_order()")
        continue

    # Bracket order = entry + take_profit leg + stop_loss leg in one submit_order
    # call. Alpaca handles the OCO server-side so we don't have to track which
    # leg fires first.
    api.submit_order(
        symbol=symbol,
        side="buy",
        type="limit",
        qty=calculate_quantity(limit_price),
        time_in_force="day",
        order_class="bracket",
        limit_price=limit_price,
        take_profit={"limit_price": tp},
        stop_loss={"stop_price": sl},
    )

    messages.append(
        "\n".join([
            f"Symbol: {symbol}",
            f"Breakout time (NY): {first_breakout_ts}",
            f"Opening Range: ORH={opening_range_high:.2f} ORL={opening_range_low:.2f} R={opening_range:.2f}",
            f"Entry (limit): {limit_price:.2f}",
            f"Take Profit:   {tp:.2f}",
            f"Stop Loss:     {sl:.2f}",
            f"Breakout candle: close={float(row0['close']):.2f} high={float(row0['high']):.2f}",
            f"Account: {config.API_URL}",
        ])
    )

    print(f"{symbol}: order submitted (paper) as bracket limit order.")

# One email at the end of the run if we placed at least one order, so we
# don't spam ourselves on quiet days
if messages:
    with smtplib.SMTP_SSL(config.EMAIL_HOST, config.EMAIL_PORT, context=context) as server:
        server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)

        email_message = f"Subject: Trade Notifications for {current_day}\n\n"
        email_message += "\n\n".join(messages)

        server.sendmail(config.EMAIL_ADDRESS, config.EMAIL_ADDRESS, email_message)
