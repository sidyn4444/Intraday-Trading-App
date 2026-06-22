"""Bollinger Bands mean reversion (short).

Mirror of bollinger_bands.py on the short side:
  1. Compute 20-period Bollinger Bands on today's minute closes.
  2. Look for a cross-back from ABOVE: previous candle closed ABOVE the
     upper band, current candle closed BACK BELOW it.
  3. Submit a bracket limit-sell at the current close, with:
        take-profit (cover) = entry - (3 × candle range)
        stop-loss   (cover) = previous candle's high
"""

import sqlite3
import config
import alpaca_trade_api as tradeapi
from datetime import date
import pandas as pd
import smtplib, ssl
import tulipy as ti
from helpers import calculate_quantity, round_to_penny

context = ssl.create_default_context()

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 200)

DRY_RUN = False

connection = sqlite3.connect(config.DB_FILE)
connection.row_factory = sqlite3.Row
cursor = connection.cursor()

cursor.execute("select id from strategy where name = 'bollinger_bands_short'")
row = cursor.fetchone()
# Defensive: missing strategy row means create_db.py is out of date.
# Fail loud rather than silently no-op so the cron log makes the problem obvious.
if row is None:
    raise RuntimeError("Strategy 'bollinger_bands_short' not found. Did you INSERT it into the strategy table?")
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
    raise RuntimeError("No symbols found for strategy 'bollinger_bands_short'.")

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

    # UTC → NY conversion so the RTH filter actually matches NY time
    if minute_bars.index.tz is None:
        minute_bars.index = minute_bars.index.tz_localize("UTC")
    minute_bars.index = minute_bars.index.tz_convert(ny_tz)

    market_open_mask = (minute_bars.index >= start_minute_bar) & (minute_bars.index < end_minute_bar)
    market_open_bars = minute_bars.loc[market_open_mask]

    # Need 20 bars minimum for a valid 20-period Bollinger calculation
    if len(market_open_bars) < 20:
        print(f"{symbol}: only {len(market_open_bars)} bars so far, need at least 20, skipping")
        continue

    closes = market_open_bars["close"].values

    try:
        lower, middle, upper = ti.bbands(closes, 20, 2)
    except Exception as e:
        print(f"{symbol}: bollinger calc failed ({type(e).__name__}): {e}")
        continue

    current_candle = market_open_bars.iloc[-1]
    previous_candle = market_open_bars.iloc[-2]

    current_close = float(current_candle["close"])
    previous_close = float(previous_candle["close"])
    current_upper = float(upper[-1])
    previous_upper = float(upper[-2])

    print(
        f"{symbol}: close={current_close:.2f} upper[-1]={current_upper:.2f} | "
        f"prev close={previous_close:.2f} upper[-2]={previous_upper:.2f}"
    )

    # Short entry: previous candle closed ABOVE the upper band (overextension)
    # and current candle closed BACK BELOW it (reversion starting)
    if current_close < current_upper and previous_close > previous_upper:
        signal_ts = market_open_bars.index[-1]

        candle_range = float(current_candle["high"]) - float(current_candle["low"])

        # On a short, TP is below entry, SL is above — opposite of the long.
        # 3× candle range for TP for the same reason as the long: winners
        # need to pay for the losers when mean reversion fails.
        limit_price = current_close
        tp = limit_price - (candle_range * 3)
        sl = float(previous_candle["high"])

        limit_price = round_to_penny(limit_price)
        # Clamp TP to a penny minimum so it can't go sub-cent on a low-priced stock
        tp = max(round_to_penny(tp), 0.01)
        sl = round_to_penny(sl)

        print(
            f"{symbol}: BOLLINGER CROSS-BACK SHORT signal at {signal_ts} | "
            f"entry={limit_price:.2f} tp={tp:.2f} sl={sl:.2f} candle_range={candle_range:.2f}"
        )

        if DRY_RUN:
            print(f"{symbol}: DRY_RUN enabled: skipping submit_order()")
            continue

        # try/except because shorts can fail for borrow-related reasons —
        # log and move on to the next symbol
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
                f"Strategy: bollinger_bands_short",
                f"Signal time (NY): {signal_ts}",
                f"Upper band (current): {current_upper:.2f}",
                f"Upper band (previous): {previous_upper:.2f}",
                f"Previous close (above band): {previous_close:.2f}",
                f"Current close (entry / limit sell): {limit_price:.2f}",
                f"Take Profit (cover): {tp:.2f}",
                f"Stop Loss (cover):   {sl:.2f}",
                f"Candle range: {candle_range:.2f}",
                f"Account: {config.API_URL}",
            ])
        )

        print(f"{symbol}: short order submitted (paper) as bracket limit order.")
    else:
        print(f"{symbol}: no bollinger short signal")

connection.close()

# Email failures shouldn't roll back trades that already submitted
if messages:
    try:
        with smtplib.SMTP_SSL(config.EMAIL_HOST, config.EMAIL_PORT, context=context) as server:
            server.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)

            email_message = f"Subject: Bollinger Short Trade Notifications for {current_day}\n\n"
            email_message += "\n\n".join(messages)

            server.sendmail(config.EMAIL_ADDRESS, config.EMAIL_ADDRESS, email_message)
    except Exception as e:
        print(f"Email notification failed ({type(e).__name__}): {e}")
        print("Trades already submitted; email failure does not affect orders.")
