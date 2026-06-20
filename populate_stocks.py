import sqlite3, config
import alpaca_trade_api as tradeapi

connection = sqlite3.connect(config.DB_FILE)
# Helps to set up rows by returning each row as an object
connection.row_factory = sqlite3.Row

cursor = connection.cursor()

cursor.execute("""
    SELECT symbol, name FROM stock
""")

# Now we can access each row by 'symbol' or 'name'
rows = cursor.fetchall()
symbols = [row['symbol'] for row in rows]

api = tradeapi.REST(
    config.API_KEY,
    config.SECRET_KEY,
    base_url = config.API_URL
)

assets = api.list_assets()
existing_symbols = set(symbols)
newStocksAdded = 0
shortableUpdated = 0

for asset in assets:
    if asset.status == 'active' and asset.tradable:
        shortable_int = 1 if asset.shortable else 0
        if asset.symbol not in existing_symbols:
            print(f"Added a new stock {asset.symbol} {asset.name}")
            cursor.execute(
                "INSERT INTO stock (symbol, name, exchange, shortable) VALUES (?, ?, ?, ?)",
                (asset.symbol, asset.name, asset.exchange, shortable_int)
            )
            newStocksAdded += 1
        else:
            cursor.execute(
                "UPDATE stock SET shortable = ? WHERE symbol = ?",
                (shortable_int, asset.symbol)
            )
            shortableUpdated += 1

print(f"Added {newStocksAdded} new stocks; refreshed shortable for {shortableUpdated} existing stocks")

connection.commit()
