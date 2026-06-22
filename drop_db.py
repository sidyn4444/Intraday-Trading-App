"""Tear down all 4 tables in the database. Use before re-running create_db.py
if you need a clean slate. Safe to run multiple times — IF EXISTS makes each
DROP a no-op when the table is already gone.

Child tables (stock_price, stock_strategy) drop before their parents (stock,
strategy) so this works even if `PRAGMA foreign_keys = ON` is set.
"""

import sqlite3, config

connection = sqlite3.connect(config.DB_FILE)
cursor = connection.cursor()

cursor.execute("DROP TABLE IF EXISTS stock_price")
cursor.execute("DROP TABLE IF EXISTS stock_strategy")
cursor.execute("DROP TABLE IF EXISTS stock")
cursor.execute("DROP TABLE IF EXISTS strategy")

connection.commit()
