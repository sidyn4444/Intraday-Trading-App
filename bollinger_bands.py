"""Bollinger Bands mean reversion (long).

For each stock assigned to this strategy:
  1. Pull today's minute bars and compute 20-period Bollinger Bands on close.
  2. Look for a cross-back: previous candle closed BELOW the lower band AND
     current candle closed BACK ABOVE it. That's the mean-reversion signal.
  3. Submit a bracket limit-buy at the current close, with:
        take-profit = entry + (3 × candle range)
        stop-loss   = previous candle's low (just outside the entry signal)

The 3× candle-range TP is chosen so winners pay for the inevitable losers
when mean reversion fails and the stop hits.
"""

import sqlite3
import config
import alpaca_trade_api as tradeapi
from datetime import date
import pandas as pd
import smtplib, ssl
import tulipy as ti
from helpers import calculate_quantity

context = ssl.create_default_context()

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

DRY_RUN = False

def round_to_penny(x: float) -> float:
    """Round to 2 decimals. +1e-9 nudge avoids 0.005 silently rounding to 0.00."""
    return round(float(x) + 1e-9, 2)

connection = sqlite3.connect(config.DB_FILE)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

cursor.execute("select id from strategy where name = 'bollinger_bands'")
row = cursor.fetchone()
# Defensive: a missing strategy row means the dashboard never inserted this strategy
# OR create_db.py is out of date — fail loud rather than silently no-op
if row is None:
    raise RuntimeError("Strategy 'bollinger_bands' not found. Did you INSERT it into the strategy table?")
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
    raise RuntimeError("No symbols found for strategy 'bollinger_bands'.")

api = tradeapi.REST(
    config.API_KEY,
    config.SECRET_KEY,
    base_url=config.API_URL
)

print("Alpaca base_url:", config.API_URL)

# Skip symbols already in an open order or position so we don't double-up
open_orders = api.list_orders(status="open")
open_order_symbols = {o.symbol for o in open_orders}

open_positions = api.list_positions()
open_position_symbols = {p.symbol for p in open_positions if float(p.qty) != 0.0}

blocked_symbols = open_order_symbols | open_position_symbols
if blocked_symbols:
    print("Blocked symbols (open order/position):", sorted(blocked_symbols))

# =========================
# Market hours window in NY time
# =========================
# IANA tz name so DST is handled automatically
current_day = date.today().isoformat()
ny_tz = "America/New_York"

start_minute_bar = pd.Timestamp(f"{current_day} 09:30:00", tz=ny_tz)
end_minute_bar   = pd.Timestamp(f"{current_day} 16:00:00", tz=ny_tz)

start_rfc3339 = start_minute_bar.isoformat()
end_rfc3339   = end_minute_bar.isoformat()

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

    # Alpaca bars come back UTC; convert so the comparison against
    # 09:30/16:00 NY timestamps actually filters to RTH
    if minute_bars.index.tz is None:
        minute_bars.index = minute_bars.index.tz_localize("UTC")
    minute_bars.index = minute_bars.index.tz_convert(ny_tz)

    market_open_mask = (minute_bars.index >= start_minute_bar) & (minute_bars.index < end_minute_bar)
    market_open_bars = minute_bars.loc[market_open_mask]

    # Bollinger Bands need 20 closes minimum — skip if the day is too young
    # to have produced enough bars yet
    if len(market_open_bars) < 20:
        print(f"{symbol}: only {len(market_open_bars)} bars so far, need at least 20, skipping")
        continue

    closes = market_open_bars["close"].values

    # tulipy.bbands returns (lower, middle, upper) arrays; index [-1] is the
    # most recent bar's band values
    try:
        lower, middle, upper = ti.bbands(closes, 20, 2)
    except Exception as e:
        print(f"{symbol}: bollinger calc failed ({type(e).__name__}): {e}")
        continue

    current_candle = market_open_bars.iloc[-1]
    previous_candle = market_open_bars.iloc[-2]

    current_close = float(current_candle["close"])
    previous_close = float(previous_candle["close"])
    current_lower = float(lower[-1])
    previous_lower = float(lower[-2])

    print(
        f"{symbol}: close={current_close:.2f} lower[-1]={current_lower:.2f} | "
        f"prev close={previous_close:.2f} lower[-2]={previous_lower:.2f}"
    )

    # Mean-reversion entry: previous candle closed below the lower band
    # (price overstretched down) AND current candle closed back above it
    # (price is reverting). Both conditions are required — a single bar
    # above the band on its own isn't a cross-back.
    if current_close > current_lower and previous_close < previous_lower:
        signal_ts = market_open_bars.index[-1]

        candle_range = float(current_candle["high"]) - float(current_candle["low"])

        # Entry at current close. 3× candle range for TP gives winners
        # enough room to pay for losers when mean reversion fails.
        limit_price = current_close
        tp = limit_price + (candle_range * 3)
        # SL just outside the previous candle's low — if price re-breaks that level,
        # the mean-reversion thesis is dead
        sl = float(previous_candle["low"])

        limit_price = round_to_penny(limit_price)
        tp = round_to_penny(tp)
        sl = max(round_to_penny(sl), 0.01)

        print(
            f"{symbol}: BOLLINGER CROSS-BACK signal at {signal_ts} | "
            f"entry={limit_price:.2f} tp={tp:.2f} sl={sl:.2f} candle_range={candle_range:.2f}"
        )

        if DRY_RUN:
            print(f"{symbol}: DRY_RUN enabled: skipping submit_order()")
            continue

        try:
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
        except Exception as e:
            print(f"{symbol}: could not submit order ({type(e).__name__}): {e}")
            continue

        messages.append(
            "\n".join([
                f"Symbol: {symbol}",
                f"Strategy: bollinger_bands",
                f"Signal time (NY): {signal_ts}",
                f"Lower band (current): {current_lower:.2f}",
                f"Lower band (previous): {previous_lower:.2f}",
                f"Previous close (below band): {previous_close:.2f}",
                f"Current close (entry): {limit_price:.2f}",
                f"Take Profit:   {tp:.2f}",
                f"Stop Loss:     {sl:.2f}",
                f"Candle range: {candle_range:.2f}",
                f"Account: {config.API_URL}",
            ])
        )

        print(f"{symbol}: order submitted (paper) as bracket limit order.")
    else:
        print(f"{symbol}: no bollinger signal")

connection.close()

# Email failures shouldn't roll back trades that already submitted
if messages:
    try:
        with smtplib.SMTP_SSL(config.EMAIL_HOST, config.EMAIL_PORT, context=context) as server:
            server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)

            email_message = f"Subject: Bollinger Trade Notifications for {current_day}\n\n"
            email_message += "\n\n".join(messages)

            server.sendmail(config.EMAIL_ADDRESS, config.EMAIL_ADDRESS, email_message)
    except Exception as e:
        print(f"Email notification failed ({type(e).__name__}): {e}")
        print("Trades already submitted; email failure does not affect orders.")
