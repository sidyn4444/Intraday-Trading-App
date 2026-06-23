"""Build a small SQLite file for the deployed portfolio demo.

The deployed dashboard on Railway needs SOME data to display — querying an empty
database would just render blank pages. But shipping the real 111MB app.db is
overkill (and leaks our trading history). This script generates a curated demo
SQLite with ~50 well-known tickers and 100 days of synthetic-but-realistic OHLC
data + indicator values + a few sample strategy assignments.

Run with:
    python seed_demo_db.py

Produces:
    app-demo.db   (a few hundred KB, committed to the repo)

Set DB_FILE=app-demo.db on Railway so the deployed dashboard reads from this
seed instead of looking for app.db (which doesn't exist on the cloud).
"""

import os
import random
import sqlite3
from datetime import date, timedelta

# Seeded RNG so re-running this script always produces the same demo DB.
# Reproducibility matters because the demo DB is checked into git — non-
# deterministic generation would create noisy diffs every time we re-seed.
random.seed(42)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "app-demo.db")
DAYS_OF_HISTORY = 100  # enough for SMA-50 + RSI-14 to have real values

# 50 well-known tickers across sectors — picked so recruiters recognize names
# in the dashboard at a glance. Each entry: (symbol, company name, exchange, shortable)
STOCK_UNIVERSE = [
    # Mega-cap tech
    ("AAPL", "Apple Inc.", "NASDAQ", 1),
    ("MSFT", "Microsoft Corp.", "NASDAQ", 1),
    ("GOOGL", "Alphabet Inc.", "NASDAQ", 1),
    ("AMZN", "Amazon.com Inc.", "NASDAQ", 1),
    ("META", "Meta Platforms Inc.", "NASDAQ", 1),
    ("NVDA", "NVIDIA Corp.", "NASDAQ", 1),
    ("TSLA", "Tesla Inc.", "NASDAQ", 1),
    ("AMD", "Advanced Micro Devices", "NASDAQ", 1),
    # Other tech
    ("NFLX", "Netflix Inc.", "NASDAQ", 1),
    ("ADBE", "Adobe Inc.", "NASDAQ", 1),
    ("CRM", "Salesforce Inc.", "NYSE", 1),
    ("ORCL", "Oracle Corp.", "NYSE", 1),
    ("INTC", "Intel Corp.", "NASDAQ", 1),
    ("CSCO", "Cisco Systems", "NASDAQ", 1),
    ("IBM", "IBM Corp.", "NYSE", 1),
    # Finance
    ("JPM", "JPMorgan Chase", "NYSE", 1),
    ("BAC", "Bank of America", "NYSE", 1),
    ("WFC", "Wells Fargo & Co.", "NYSE", 1),
    ("GS", "Goldman Sachs", "NYSE", 1),
    ("MS", "Morgan Stanley", "NYSE", 1),
    ("V", "Visa Inc.", "NYSE", 1),
    ("MA", "Mastercard Inc.", "NYSE", 1),
    # Industrials
    ("BA", "Boeing Co.", "NYSE", 1),
    ("CAT", "Caterpillar Inc.", "NYSE", 1),
    ("GE", "General Electric", "NYSE", 1),
    ("MMM", "3M Co.", "NYSE", 1),
    ("HON", "Honeywell", "NASDAQ", 1),
    # Consumer
    ("WMT", "Walmart Inc.", "NYSE", 1),
    ("COST", "Costco Wholesale", "NASDAQ", 1),
    ("HD", "Home Depot", "NYSE", 1),
    ("NKE", "Nike Inc.", "NYSE", 1),
    ("MCD", "McDonald's Corp.", "NYSE", 1),
    ("SBUX", "Starbucks Corp.", "NASDAQ", 1),
    ("DIS", "Walt Disney Co.", "NYSE", 1),
    ("TGT", "Target Corp.", "NYSE", 1),
    ("LOW", "Lowe's Cos.", "NYSE", 1),
    # Healthcare
    ("JNJ", "Johnson & Johnson", "NYSE", 1),
    ("PFE", "Pfizer Inc.", "NYSE", 1),
    ("UNH", "UnitedHealth Group", "NYSE", 1),
    ("MRK", "Merck & Co.", "NYSE", 1),
    ("ABBV", "AbbVie Inc.", "NYSE", 1),
    # Energy
    ("XOM", "Exxon Mobil Corp.", "NYSE", 1),
    ("CVX", "Chevron Corp.", "NYSE", 1),
    # Telecom
    ("VZ", "Verizon Communications", "NYSE", 1),
    ("T", "AT&T Inc.", "NYSE", 1),
    # ETFs (popular index trackers)
    ("SPY", "SPDR S&P 500 ETF", "NYSE", 1),
    ("QQQ", "Invesco QQQ Trust", "NASDAQ", 1),
    # Retail traders' favorites
    ("GME", "GameStop Corp.", "NYSE", 1),
    ("PLTR", "Palantir Technologies", "NYSE", 1),
    ("F", "Ford Motor Co.", "NYSE", 1),
]

# Approximate starting prices keyed by ticker — anchors the random walks at a
# realistic level for each stock so AAPL doesn't end up at $5 or BAC at $400.
STARTING_PRICES = {
    "AAPL": 175, "MSFT": 410, "GOOGL": 140, "AMZN": 175, "META": 480,
    "NVDA": 880, "TSLA": 200, "AMD": 165, "NFLX": 620, "ADBE": 530,
    "CRM": 290, "ORCL": 120, "INTC": 40, "CSCO": 49, "IBM": 175,
    "JPM": 195, "BAC": 38, "WFC": 55, "GS": 410, "MS": 95,
    "V": 270, "MA": 470, "BA": 200, "CAT": 350, "GE": 165,
    "MMM": 100, "HON": 195, "WMT": 60, "COST": 730, "HD": 350,
    "NKE": 95, "MCD": 280, "SBUX": 95, "DIS": 110, "TGT": 165,
    "LOW": 230, "JNJ": 155, "PFE": 28, "UNH": 510, "MRK": 125,
    "ABBV": 175, "XOM": 110, "CVX": 155, "VZ": 40, "T": 17,
    "SPY": 530, "QQQ": 460, "GME": 25, "PLTR": 22, "F": 12,
}

STRATEGIES = [
    "opening_range_breakout",
    "opening_range_breakdown",
    "bollinger_bands",
    "bollinger_bands_short",
]


def create_schema(conn):
    """Same schema as create_db.py. Duplicated here so this script doesn't
    depend on importing create_db.py (which would trigger create_db.py to
    open a connection to the real DB at import time)."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            exchange TEXT NOT NULL,
            shortable INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_price (
            id INTEGER PRIMARY KEY,
            stock_id INTEGER,
            date NOT NULL,
            open NOT NULL,
            high NOT NULL,
            low NOT NULL,
            close NOT NULL,
            volume NOT NULL,
            sma_20,
            sma_50,
            rsi_14,
            FOREIGN KEY(stock_id) REFERENCES stock (id)
            UNIQUE(stock_id, date)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS strategy (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_strategy (
            stock_id INTEGER NOT NULL,
            strategy_id INTEGER NOT NULL,
            FOREIGN KEY (stock_id) REFERENCES stock (id),
            FOREIGN KEY (strategy_id) REFERENCES strategy (id),
            UNIQUE(stock_id, strategy_id)
        )
    """)
    conn.commit()


def generate_price_walk(symbol):
    """Generate DAYS_OF_HISTORY days of synthetic-but-realistic OHLC bars.

    Uses a random walk anchored at the stock's STARTING_PRICE. Each day:
      - daily drift = small random change between -3% and +3%
      - open = previous close (continuous, no gap)
      - high = max(open, close) * (1 + intraday range)
      - low  = min(open, close) * (1 - intraday range)
      - volume = log-normal-ish to look real
    """
    starting_price = STARTING_PRICES.get(symbol, 100)
    bars = []
    today = date.today()
    price = starting_price

    for days_ago in range(DAYS_OF_HISTORY, 0, -1):
        bar_date = today - timedelta(days=days_ago)

        daily_pct = random.uniform(-0.03, 0.03)  # ±3% daily move
        open_price = price
        close_price = price * (1 + daily_pct)
        intraday_range = random.uniform(0.005, 0.025)
        high_price = max(open_price, close_price) * (1 + intraday_range)
        low_price = min(open_price, close_price) * (1 - intraday_range)
        volume = int(random.uniform(1_000_000, 50_000_000))

        bars.append({
            "date": bar_date.isoformat(),
            "open": round(open_price, 2),
            "high": round(high_price, 2),
            "low": round(low_price, 2),
            "close": round(close_price, 2),
            "volume": volume,
        })

        price = close_price  # next day opens where today closed

    return bars


def compute_indicators(bars):
    """Compute SMA-20, SMA-50, and RSI-14 for the MOST RECENT day only.

    Matches populate_prices.py behavior — historical days have NULL indicators
    and only the latest day gets values. This keeps the dashboard's "above SMA"
    and "RSI overbought" filters working without needing to backfill every day.
    """
    closes = [bar["close"] for bar in bars]

    sma_20 = sum(closes[-20:]) / 20
    sma_50 = sum(closes[-50:]) / 50

    # RSI-14: classic Wilder calculation simplified for the seed
    gains, losses = [], []
    for i in range(-14, 0):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi_14 = 100 - (100 / (1 + rs))

    return round(sma_20, 2), round(sma_50, 2), round(rsi_14, 2)


def seed_stocks(conn):
    """Insert all 50 stocks and return a {symbol: stock_id} lookup."""
    cur = conn.cursor()
    for symbol, name, exchange, shortable in STOCK_UNIVERSE:
        cur.execute(
            "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
            (symbol, name, exchange, shortable),
        )
    conn.commit()
    rows = cur.execute("SELECT id, symbol FROM stock").fetchall()
    return {row[1]: row[0] for row in rows}


def seed_prices(conn, stock_id_by_symbol):
    """Insert 100 days × 50 stocks of synthetic OHLC + indicators on day 100."""
    cur = conn.cursor()
    for symbol, stock_id in stock_id_by_symbol.items():
        bars = generate_price_walk(symbol)
        sma_20, sma_50, rsi_14 = compute_indicators(bars)
        for i, bar in enumerate(bars):
            # Indicators only on the latest day, matching populate_prices.py
            is_latest = (i == len(bars) - 1)
            cur.execute(
                """INSERT INTO stock_price
                   (stock_id, date, open, high, low, close, volume, sma_20, sma_50, rsi_14)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stock_id, bar["date"], bar["open"], bar["high"],
                    bar["low"], bar["close"], bar["volume"],
                    sma_20 if is_latest else None,
                    sma_50 if is_latest else None,
                    rsi_14 if is_latest else None,
                ),
            )
    conn.commit()


def seed_strategies(conn):
    """Seed all 4 strategy rows (matches create_db.py)."""
    cur = conn.cursor()
    for name in STRATEGIES:
        cur.execute("INSERT OR IGNORE INTO strategy (name) VALUES (?)", (name,))
    conn.commit()


def seed_strategy_assignments(conn, stock_id_by_symbol):
    """Assign a handful of stocks to each strategy so the strategy detail pages
    show real content instead of being empty.

    Picks 5 random stocks per strategy. Some overlap is intentional — tests
    the many-to-many relationship the dashboard's JOINs depend on."""
    cur = conn.cursor()
    strategy_ids = {row[1]: row[0] for row in cur.execute("SELECT id, name FROM strategy").fetchall()}
    all_symbols = list(stock_id_by_symbol.keys())

    for strategy_name, strategy_id in strategy_ids.items():
        sample = random.sample(all_symbols, 5)
        for symbol in sample:
            cur.execute(
                "INSERT OR IGNORE INTO stock_strategy (stock_id, strategy_id) VALUES (?, ?)",
                (stock_id_by_symbol[symbol], strategy_id),
            )
    conn.commit()


def main():
    # If a previous demo file exists, blow it away so we start clean.
    # Otherwise we'd hit UNIQUE constraint errors on re-run.
    if os.path.exists(OUTPUT_PATH):
        os.remove(OUTPUT_PATH)
        print(f"Removed existing {OUTPUT_PATH}")

    conn = sqlite3.connect(OUTPUT_PATH)
    print(f"Creating {OUTPUT_PATH}")

    create_schema(conn)
    print("  - Schema created")

    stock_id_by_symbol = seed_stocks(conn)
    print(f"  - Seeded {len(stock_id_by_symbol)} stocks")

    seed_prices(conn, stock_id_by_symbol)
    n_prices = conn.execute("SELECT COUNT(*) FROM stock_price").fetchone()[0]
    print(f"  - Seeded {n_prices:,} price rows ({DAYS_OF_HISTORY} days x {len(stock_id_by_symbol)} stocks)")

    seed_strategies(conn)
    print(f"  - Seeded {len(STRATEGIES)} strategies")

    seed_strategy_assignments(conn, stock_id_by_symbol)
    n_assignments = conn.execute("SELECT COUNT(*) FROM stock_strategy").fetchone()[0]
    print(f"  - Seeded {n_assignments} stock_strategy assignments")

    conn.close()

    file_size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\nDone. {OUTPUT_PATH} is {file_size_kb:.1f} KB.")


if __name__ == "__main__":
    main()
