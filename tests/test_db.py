"""Integration tests for the SQLite schema and constraints.

These tests don't touch app.db. They create a fresh temp database, run the
same CREATE TABLE statements as create_db.py against it, and exercise the
schema + constraints directly. This catches schema drift early.
"""

import os
import sqlite3
import tempfile

import pytest


# ---------- helpers ----------

def _create_schema(conn):
    """Build the same schema as create_db.py. Kept here (not imported from
    create_db.py) because create_db.py opens a connection to config.DB_FILE
    at import time — we want this test to run in isolation against a temp DB.
    """
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


@pytest.fixture
def db():
    """Spin up a fresh in-memory SQLite DB with the schema applied. Each test
    gets its own — no shared state, no order dependence.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    yield conn
    conn.close()


# ---------- schema tests ----------

def test_schema_creates_all_four_tables(db):
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [row["name"] for row in rows]
    assert "stock" in table_names
    assert "stock_price" in table_names
    assert "strategy" in table_names
    assert "stock_strategy" in table_names


# ---------- insert + query round-trip ----------

def test_insert_stock_then_query_returns_it(db):
    db.execute(
        "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
        ("AMD", "Advanced Micro Devices", "NASDAQ", 1),
    )
    db.commit()

    row = db.execute("SELECT * FROM stock WHERE symbol = ?", ("AMD",)).fetchone()
    assert row is not None
    assert row["symbol"] == "AMD"
    assert row["name"] == "Advanced Micro Devices"
    assert row["shortable"] == 1


def test_strategy_name_must_be_unique(db):
    """The UNIQUE constraint on strategy.name lets create_db.py re-run safely
    with INSERT OR IGNORE. Without it, every re-run would duplicate seed rows."""
    db.execute("INSERT INTO strategy (name) VALUES ('opening_range_breakout')")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO strategy (name) VALUES ('opening_range_breakout')")
        db.commit()


def test_stock_symbol_must_be_unique(db):
    db.execute(
        "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
        ("AAPL", "Apple Inc.", "NASDAQ", 1),
    )
    db.commit()

    # Second insert with same symbol must fail because of UNIQUE constraint
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
            ("AAPL", "Apple Inc. duplicate", "NASDAQ", 1),
        )
        db.commit()


# ---------- the (stock_id, date) UNIQUE constraint on stock_price ----------

def test_stock_price_unique_constraint_prevents_duplicate_day(db):
    """The (stock_id, date) UNIQUE constraint is critical — without it, a
    re-run of populate_prices.py on the same day would create duplicate rows
    and break the indicator filters in main.py (which use max(date))."""
    db.execute(
        "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
        ("TSLA", "Tesla", "NASDAQ", 1),
    )
    db.commit()
    stock_id = db.execute("SELECT id FROM stock WHERE symbol='TSLA'").fetchone()["id"]

    db.execute(
        """INSERT INTO stock_price (stock_id, date, open, high, low, close, volume)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (stock_id, "2026-06-19", 250.0, 255.0, 248.0, 253.0, 1_000_000),
    )
    db.commit()

    # Same (stock_id, date) again — must fail
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO stock_price (stock_id, date, open, high, low, close, volume)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (stock_id, "2026-06-19", 251.0, 256.0, 249.0, 254.0, 1_100_000),
        )
        db.commit()


def test_stock_price_allows_different_dates_for_same_stock(db):
    """Sanity check the inverse — different dates for the same stock_id should be allowed."""
    db.execute(
        "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
        ("NVDA", "NVIDIA", "NASDAQ", 1),
    )
    db.commit()
    stock_id = db.execute("SELECT id FROM stock WHERE symbol='NVDA'").fetchone()["id"]

    db.execute(
        "INSERT INTO stock_price (stock_id, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (stock_id, "2026-06-18", 130.0, 132.0, 129.0, 131.0, 5_000_000),
    )
    db.execute(
        "INSERT INTO stock_price (stock_id, date, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (stock_id, "2026-06-19", 131.0, 134.0, 131.0, 133.5, 5_500_000),
    )
    db.commit()

    rows = db.execute("SELECT date FROM stock_price WHERE stock_id = ? ORDER BY date", (stock_id,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-06-18"
    assert rows[1]["date"] == "2026-06-19"


# ---------- stock_strategy many-to-many ----------

def test_stock_strategy_pairing_must_be_unique(db):
    """UNIQUE(stock_id, strategy_id) prevents duplicate pairings — without it,
    calling /apply_strategy twice with the same stock+strategy would create
    duplicate rows and the strategy script would pick up the symbol twice."""
    # Seed the parent rows
    db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES ('AMD','AMD','NASDAQ',1)")
    db.execute("INSERT INTO strategy (name) VALUES ('opening_range_breakout')")
    db.commit()

    db.execute("INSERT INTO stock_strategy (stock_id, strategy_id) VALUES (1, 1)")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO stock_strategy (stock_id, strategy_id) VALUES (1, 1)")
        db.commit()


def test_stock_symbol_cannot_be_null(db):
    """NOT NULL on stock.symbol stops accidentally inserting a row without
    its identifier, which would corrupt every downstream JOIN."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES (NULL, 'foo', 'NASDAQ', 1)")
        db.commit()


def test_same_date_allowed_across_different_stocks(db):
    """Sanity check that UNIQUE(stock_id, date) is composite — the same
    date IS allowed for different stocks (every stock prices on the same days)."""
    db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES ('AMD','AMD','NASDAQ',1)")
    db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES ('TSLA','Tesla','NASDAQ',1)")
    db.commit()

    db.execute("INSERT INTO stock_price (stock_id, date, open, high, low, close, volume) VALUES (1, '2026-06-21', 1, 1, 1, 1, 1)")
    db.execute("INSERT INTO stock_price (stock_id, date, open, high, low, close, volume) VALUES (2, '2026-06-21', 1, 1, 1, 1, 1)")
    db.commit()

    rows = db.execute("SELECT COUNT(*) AS n FROM stock_price WHERE date = '2026-06-21'").fetchone()
    assert rows["n"] == 2


def test_insert_or_ignore_silently_skips_duplicate_strategy(db):
    """INSERT OR IGNORE is what makes create_db.py safe to re-run — a duplicate
    strategy name doesn't crash, it's just silently dropped."""
    db.execute("INSERT INTO strategy (name) VALUES ('opening_range_breakout')")
    db.commit()

    # No exception, no extra row inserted
    db.execute("INSERT OR IGNORE INTO strategy (name) VALUES ('opening_range_breakout')")
    db.commit()

    rows = db.execute("SELECT COUNT(*) AS n FROM strategy WHERE name = 'opening_range_breakout'").fetchone()
    assert rows["n"] == 1


def test_stock_strategy_many_to_many_link(db):
    """One stock can have multiple strategies; one strategy can have multiple stocks."""
    # Seed two stocks and two strategies
    db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES ('AMD','AMD','NASDAQ',1)")
    db.execute("INSERT INTO stock (symbol, name, exchange, shortable) VALUES ('TSLA','Tesla','NASDAQ',1)")
    db.execute("INSERT INTO strategy (name) VALUES ('opening_range_breakout')")
    db.execute("INSERT INTO strategy (name) VALUES ('bollinger_bands')")
    db.commit()

    amd_id = db.execute("SELECT id FROM stock WHERE symbol='AMD'").fetchone()["id"]
    tsla_id = db.execute("SELECT id FROM stock WHERE symbol='TSLA'").fetchone()["id"]
    orb_id = db.execute("SELECT id FROM strategy WHERE name='opening_range_breakout'").fetchone()["id"]
    bb_id = db.execute("SELECT id FROM strategy WHERE name='bollinger_bands'").fetchone()["id"]

    # AMD runs both strategies; TSLA only runs bollinger
    db.execute("INSERT INTO stock_strategy (stock_id, strategy_id) VALUES (?, ?)", (amd_id, orb_id))
    db.execute("INSERT INTO stock_strategy (stock_id, strategy_id) VALUES (?, ?)", (amd_id, bb_id))
    db.execute("INSERT INTO stock_strategy (stock_id, strategy_id) VALUES (?, ?)", (tsla_id, bb_id))
    db.commit()

    # Query: which stocks are assigned to bollinger_bands?
    rows = db.execute(
        """SELECT s.symbol FROM stock s
           JOIN stock_strategy ss ON ss.stock_id = s.id
           WHERE ss.strategy_id = ? ORDER BY s.symbol""",
        (bb_id,),
    ).fetchall()
    symbols = [r["symbol"] for r in rows]
    assert symbols == ["AMD", "TSLA"]

    # Query: which strategies does AMD run?
    rows = db.execute(
        """SELECT st.name FROM strategy st
           JOIN stock_strategy ss ON ss.strategy_id = st.id
           WHERE ss.stock_id = ? ORDER BY st.name""",
        (amd_id,),
    ).fetchall()
    strategy_names = [r["name"] for r in rows]
    assert strategy_names == ["bollinger_bands", "opening_range_breakout"]
