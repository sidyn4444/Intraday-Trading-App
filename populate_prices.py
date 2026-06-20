"""Daily price + indicator refresh.

Pulls the last DAYS_BACK days of daily bars from Alpaca for every stock in
the stock table, computes SMA-20, SMA-50, and RSI-14 for the latest day,
and inserts the bars into stock_price. Trims rows older than DAYS_BACK so
the DB stays a rolling window instead of growing forever.

Runs daily after market close via cron.
"""

import sqlite3
import config
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import tulipy as ti
import numpy as nu
import alpaca_trade_api as tradeapi

DAYS_BACK = 100
CHUNK_SIZE = 200

def chunked(lst, size):
    """Yield successive `size`-sized slices of `lst`. Used to batch the
    Alpaca bars call because passing 10K symbols in one request is too big."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]

def main():
    connection = sqlite3.connect(config.DB_FILE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    # UNIQUE(stock_id, date) is on the table, but the index makes the
    # INSERT OR IGNORE below fast on re-runs that hit the same day
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_price_unique
        ON stock_price (stock_id, date);
    """)

    cursor.execute("SELECT id, symbol FROM stock")
    rows = cursor.fetchall()

    symbols = [row["symbol"] for row in rows]
    # Filter out symbols with "/" because Alpaca uses them for things like
    # BRK/B and the bars endpoint chokes on them in batched requests
    symbols = [s for s in symbols if "/" not in s]

    # Dictionary lookup so we get stock_id in O(1) instead of querying
    # the stock table every row. Alpaca only knows symbols, the DB only knows ids.
    stock_id_by_symbol = {row["symbol"]: row["id"] for row in rows}

    if not symbols:
        print("No symbols found in stock table.")
        return

    api = tradeapi.REST(
        config.API_KEY,
        config.SECRET_KEY,
        base_url=config.API_URL
    )

    start = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).isoformat()

    inserted = 0

    for symbol_chunk in chunked(symbols, CHUNK_SIZE):
        barsets = api.get_bars(
            symbol_chunk,
            tradeapi.TimeFrame.Day,
            start=start
        )

        # Alpaca returns one flat stream of bars across all symbols,
        # so group them back by symbol before processing
        bars_by_symbol = defaultdict(list)
        for bar in barsets:
            bars_by_symbol[bar.S].append(bar)

        for symbol, symbol_bars in bars_by_symbol.items():
            print(f"\nprocessing symbol {symbol}")

            # Sort by date so symbol_bars[-1] is reliably the latest day
            symbol_bars.sort(key=lambda b: b.t)

            stock_id = stock_id_by_symbol.get(symbol)
            if stock_id is None:
                continue

            if not symbol_bars:
                continue

            # Only the latest day gets indicator values. Older days already
            # had their indicators computed on the day they were the latest,
            # and recomputing them now would just waste work.
            latest_day = symbol_bars[-1].t.date()

            recent_closes = [bar.c for bar in symbol_bars]

            # tulipy needs at least 50 closes for SMA-50, so skip indicators
            # entirely on stocks with shorter history rather than crashing
            sma_20_latest, sma_50_latest, rsi_14_latest = None, None, None
            try:
                if len(recent_closes) >= 50:
                    closes_arr = nu.array(recent_closes, dtype=float)
                    sma_20_latest = ti.sma(closes_arr, period=20)[-1]
                    sma_50_latest = ti.sma(closes_arr, period=50)[-1]
                    rsi_14_latest = ti.rsi(closes_arr, period=14)[-1]
            except Exception as e:
                print(f"{symbol}: indicator calc failed ({type(e).__name__}): {e}")
                sma_20_latest, sma_50_latest, rsi_14_latest = None, None, None

            for bar in symbol_bars:
                day = bar.t.date()

                # Older days store NULL for indicators; only latest day gets the values
                if day == latest_day:
                    sma_20, sma_50, rsi_14 = sma_20_latest, sma_50_latest, rsi_14_latest
                else:
                    sma_20, sma_50, rsi_14 = None, None, None

                # INSERT OR IGNORE so a re-run on the same day doesn't blow up
                # on the UNIQUE(stock_id, date) constraint
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO stock_price
                    (stock_id, date, open, high, low, close, volume, sma_20, sma_50, rsi_14)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (stock_id, day.isoformat(), bar.o, bar.h, bar.l, bar.c, bar.v, sma_20, sma_50, rsi_14)
                )
                inserted += cursor.rowcount

            # Rolling-window trim: drop anything older than DAYS_BACK for this stock.
            # stock_id filter is required — without it the DELETE would run globally
            # and wipe history for every stock whose latest day is different from this one's.
            cutoff_date = (latest_day - timedelta(days=DAYS_BACK - 1)).isoformat()
            cursor.execute(
                """
                DELETE FROM stock_price
                WHERE stock_id = ?
                  AND date < ?
                """,
                (stock_id, cutoff_date)
            )

    connection.commit()
    connection.close()

    print(f"\nDone. Inserted {inserted} rows into stock_price.")

if __name__ == "__main__":
    main()
