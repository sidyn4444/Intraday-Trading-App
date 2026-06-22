"""Opening Range Breakdown (short).

Mirror of opening_range_breakout.py but on the short side:
  1. Define the opening range as the high/low of 09:30-09:45 ET bars.
  2. Wait for the first candle that closes BELOW the opening range low.
  3. Submit a bracket limit-sell at that close, with:
        take-profit (cover) = entry - range
        stop-loss   (cover) = entry + range

The submit_order call is wrapped in try/except because shorting can fail
for reasons the long side never sees (stock not on the easy-to-borrow
list, fees, etc.) and we want the loop to continue with the next symbol.
"""

import sqlite3
import config
import alpaca_trade_api as tradeapi
from datetime import date
import pandas as pd
import smtplib, ssl
from helpers import calculate_quantity, round_to_penny

context = ssl.create_default_context()

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

DRY_RUN = False

connection = sqlite3.connect(config.DB_FILE)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

cursor.execute("select id from strategy where name = 'opening_range_breakdown'")
row = cursor.fetchone()
strategy_id = row["id"]

cursor.execute("""
    select symbol, name
    from stock
    join stock_strategy on stock_strategy.stock_id = stock.id
    where stock_strategy.strategy_id = ?
""", (strategy_id,))
stocks = cursor.fetchall()
symbols = [stock["symbol"] for stock in stocks]

if not symbols:
    raise RuntimeError("No symbols found for strategy 'opening_range_breakdown'.")

api = tradeapi.REST(
    config.API_KEY,
    config.SECRET_KEY,
    base_url=config.API_URL
)

print("Alpaca base_url:", config.API_URL)

# Skip symbols already in an open order or position so we don't double-up
# on the same name across cron ticks
open_orders = api.list_orders(status="open")
open_order_symbols = {o.symbol for o in open_orders}

open_positions = api.list_positions()
open_position_symbols = {p.symbol for p in open_positions if float(p.qty) != 0.0}

blocked_symbols = open_order_symbols | open_position_symbols
if blocked_symbols:
    print("Blocked symbols (open order/position):", sorted(blocked_symbols))

# IANA tz name so DST flips don't silently break the 09:30/09:45 comparison
current_day = date.today().isoformat()
ny_tz = "America/New_York"

start_minute_bar = pd.Timestamp(f"{current_day} 09:30:00", tz=ny_tz)
end_minute_bar   = pd.Timestamp(f"{current_day} 09:45:00", tz=ny_tz)

start_rfc3339 = start_minute_bar.isoformat()
end_rfc3339   = pd.Timestamp(f"{current_day} 16:00:00", tz=ny_tz).isoformat()

messages = []

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

    # Alpaca bars come back UTC; convert so 09:30/09:45 means NY time
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

    # Bail on a 0 or negative range so we don't submit a bracket with no width
    if opening_range <= 0:
        print(f"{symbol}: opening range not valid (range={opening_range}), skipping")
        continue

    after_opening_range = minute_bars.loc[minute_bars.index >= end_minute_bar]
    breakdown = after_opening_range[after_opening_range["close"] < opening_range_low]

    if breakdown.empty:
        print(f"{symbol}: no breakdown yet")
        continue

    # First breakdown candle is the entry; later candles that also break down get ignored
    row0 = breakdown.iloc[0]
    print(
        f"{symbol}: breakdown candle | "
        f"close={float(row0['close']):.2f} "
        f"low={float(row0['low']):.2f} "
        f"ORL={opening_range_low:.2f}"
    )

    first_breakdown_ts = breakdown.index[0]
    limit_price = float(row0["close"])

    # On a short, TP is BELOW entry and SL is ABOVE — opposite of the long
    tp = limit_price - opening_range
    sl = limit_price + opening_range

    limit_price = round_to_penny(limit_price)
    # Clamp TP to a penny minimum so we never set a sub-cent target
    tp = max(round_to_penny(tp), 0.01)
    sl = round_to_penny(sl)

    print(
        f"{symbol}: breakdown at {first_breakdown_ts} | "
        f"ORH={opening_range_high:.2f} ORL={opening_range_low:.2f} R={opening_range:.2f} | "
        f"entry={limit_price:.2f} tp={tp:.2f} sl={sl:.2f}"
    )

    if DRY_RUN:
        print(f"{symbol}: DRY_RUN enabled: skipping submit_order()")
        continue

    # Try/except because shorts can fail for reasons the long side never sees
    # (no shares to borrow, hard-to-borrow fees, etc.) — log and continue
    try:
        api.submit_order(
            symbol=symbol,
            side="sell",
            type="limit",
            qty=calculate_quantity(limit_price),
            time_in_force="day",
            order_class="bracket",
            limit_price=limit_price,
            take_profit={"limit_price": tp},
            stop_loss={"stop_price": sl},
        )
    except Exception as e:
        print(f"{symbol}: could not submit short order ({type(e).__name__}): {e}")
        continue

    messages.append(
        "\n".join([
            f"Symbol: {symbol} (SHORT)",
            f"Breakdown time (NY): {first_breakdown_ts}",
            f"Opening Range: ORH={opening_range_high:.2f} ORL={opening_range_low:.2f} R={opening_range:.2f}",
            f"Entry (limit sell): {limit_price:.2f}",
            f"Take Profit (cover): {tp:.2f}",
            f"Stop Loss (cover):   {sl:.2f}",
            f"Breakdown candle: close={float(row0['close']):.2f} low={float(row0['low']):.2f}",
            f"Account: {config.API_URL}",
        ])
    )

    print(f"{symbol}: short order submitted (paper) as bracket limit order.")

# Skip cleanly if creds aren't configured. Never let an email failure
# roll back trades that already submitted.
if messages:
    if not getattr(config, "EMAIL_ADDRESS", None) or not getattr(config, "EMAIL_PASSWORD", None):
        print("Email creds not configured; skipping notification.")
    else:
        try:
            with smtplib.SMTP_SSL(config.EMAIL_HOST, config.EMAIL_PORT, context=context) as server:
                server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)

                email_message = f"Subject: Short Trade Notifications for {current_day}\n\n"
                email_message += "\n\n".join(messages)

                server.sendmail(config.EMAIL_ADDRESS, config.EMAIL_ADDRESS, email_message)
        except Exception as e:
            print(f"Email notification failed ({type(e).__name__}): {e}")
            print("Trades already submitted; email failure does not affect orders.")
