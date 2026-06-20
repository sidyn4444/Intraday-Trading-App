import sqlite3, config

connection = sqlite3.connect(config.DB_FILE)

cursor = connection.cursor()

cursor.execute("""
               CREATE TABLE IF NOT EXISTS stock (
                    id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    shortable INTEGER NOT NULL
               )
""")

# stock_id is a foreign key into stock so the symbol can be renamed in one place
# without having to update every price row
cursor.execute("""
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

# strategy is its own table so the UI dropdown can use strategy.id directly
# and so stock_strategy can foreign-key into it
cursor.execute("""
    CREATE TABLE IF NOT EXISTS strategy (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL
    )
""")

# Many-to-many link table: one stock can run multiple strategies and
# one strategy can be applied to many stocks
cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_strategy (
        stock_id INTEGER NOT NULL,
        strategy_id INTEGER NOT NULL,
        FOREIGN KEY (stock_id) REFERENCES stock (id),
        FOREIGN KEY (strategy_id) REFERENCES strategy (id)
    )
""")

strategies = ['opening_range_breakout', 'opening_range_breakdown']

for strategy in strategies:
    cursor.execute("""
        INSERT INTO strategy (name) VALUES (?)
    """, (strategy,))

connection.commit()
