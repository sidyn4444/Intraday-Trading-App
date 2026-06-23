"""FastAPI dashboard.

Routes:
  GET  /                       — stock browser with 8 filter modes
  GET  /stock/{symbol}         — per-stock detail page with daily price history
  POST /apply_strategy         — assign a strategy to a stock (from a form post)
  GET  /strategies             — list all strategies
  GET  /strategy/{strategy_id} — show stocks assigned to a single strategy
  GET  /orders                 — live order list from Alpaca

All filters key off the latest date in stock_price rather than today's date,
because on weekends/holidays Alpaca returns no new bars and "today" would
silently produce empty results.
"""

import sqlite3, config
import alpaca_trade_api as tradeapi
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory = "templates")

@app.get("/")
def index(request: Request):
    """Stock browser with 8 filter modes (closing highs/lows, RSI, SMA-20/50)."""
    stock_filter = request.query_params.get('filter', False)
    connection = sqlite3.connect(config.DB_FILE)
    # row_factory lets us access columns by name (row['symbol']) instead of by index
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    if stock_filter == 'new_closing_highs':
        # GROUP BY stock_id gives us each stock's max close. The outer SELECT
        # filters that down to only the rows where max(close) happened on the
        # latest available date. The WHERE has to live in the outer query —
        # putting it before GROUP BY would filter rows BEFORE the aggregate,
        # which breaks the "is today the new high?" semantics.
        cursor.execute("""
        select * from (
            select symbol, name, stock_id, shortable, max(close), date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            group by stock_id
            order by symbol
        )
        where date = (select max(date) from stock_price)
        """)
    elif stock_filter == 'new_closing_lows':
        cursor.execute("""
        select * from (
            select symbol, name, stock_id, shortable, min(close), date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            group by stock_id
            order by symbol
        )
        where date = (select max(date) from stock_price)
        """)
    elif stock_filter == 'rsi_overbought':
        cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where rsi_14 > 70
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    elif stock_filter == 'rsi_oversold':
         cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where rsi_14 < 30
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    elif stock_filter == 'above_sma_20':
        cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where close > sma_20
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    elif stock_filter == 'below_sma_20':
        cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where close < sma_20
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    elif stock_filter == 'above_sma_50':
        cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where close > sma_50
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    elif stock_filter == 'below_sma_50':
        cursor.execute("""
            select symbol, name, stock_id, date
            from stock_price
            join stock on stock.id = stock_price.stock_id
            where close < sma_50
            AND date = (select max(date) from stock_price)
            order by symbol
        """)
    else:
        cursor.execute("""
            SELECT id, symbol, name, shortable FROM stock ORDER BY symbol
        """)

    rows = cursor.fetchall()

    # Pull the latest indicator values in a second query so the template can
    # show them on every row regardless of which filter mode is active
    cursor.execute("""
        select stock.symbol, stock_price.rsi_14, stock_price.sma_20, stock_price.sma_50, stock_price.close
        from stock
        join stock_price on stock_price.stock_id = stock.id
        where stock_price.date = (select max(date) from stock_price)
    """)
    indicator_rows = cursor.fetchall()
    # symbol -> row dict so the template can do O(1) lookups in the row loop
    # instead of scanning the full indicator list for every row
    indicator_values = {}
    for row in indicator_rows:
        indicator_values[row['symbol']] = row
    connection.close()
    return templates.TemplateResponse("index.html", {"request": request, "stocks": rows, "indicator_values": indicator_values})

@app.get("/stock/{symbol}")
def stock_detail(request: Request, symbol):
    """Per-stock detail page: stock metadata + full daily price history + strategy dropdown."""
    connection = sqlite3.connect(config.DB_FILE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()
    # Strategies feed the assignment dropdown on this page
    cursor.execute("""
        SELECT * FROM strategy
    """)
    strategies = cursor.fetchall()
    cursor.execute("""
        SELECT id, symbol, name, exchange, shortable FROM stock WHERE symbol = ?
    """, (symbol,))

    row = cursor.fetchone()

    cursor.execute("""
        SELECT * FROM stock_price WHERE stock_id = ? ORDER BY date DESC
    """, (row['id'],))
    prices = cursor.fetchall()
    connection.close()
    return templates.TemplateResponse("stock_detail.html", {"request": request, "stock": row, "bars": prices, "strategies": strategies})

@app.post("/apply_strategy")
def apply_strategy(strategy_id: int = Form(...), stock_id: int = Form(...)):
    """Assign a stock to a strategy. Form-posted from stock_detail.html, then
    303-redirect to the strategy detail page so a refresh doesn't re-submit.

    Blocked when READ_ONLY is True so public deploys can't accept anonymous
    strategy assignments. Local dev still works because READ_ONLY defaults False.
    """
    if config.READ_ONLY:
        raise HTTPException(
            status_code=403,
            detail="Strategy assignment is disabled in production mode."
        )

    connection = sqlite3.connect(config.DB_FILE)
    cursor = connection.cursor()

    cursor.execute("""
        INSERT INTO stock_strategy (stock_id, strategy_id)
        VALUES (?, ?)
    """, (stock_id, strategy_id))

    connection.commit()
    connection.close()
    return RedirectResponse(url=f"/strategy/{strategy_id}", status_code=303)

@app.get("/strategies")
def strategies(request: Request):
    """List all strategies in the system."""
    connection = sqlite3.connect(config.DB_FILE)
    connection.row_factory = sqlite3.Row
    cursor = connection.cursor()

    cursor.execute("""
        SELECT * FROM strategy
    """)
    strategies = cursor.fetchall()
    return templates.TemplateResponse(
        "strategies.html",
        {"request": request, "strategies": strategies}
    )

@app.get("/orders")
def orders(request: Request):
    """Live order list pulled directly from Alpaca (not the local DB) so we always
    see the truth from the broker, including fills the local DB never recorded."""
    api = tradeapi.REST(
    config.API_KEY,
    config.SECRET_KEY,
    base_url=config.API_URL
    )
    orders = api.list_orders(status="all")

    return templates.TemplateResponse(
        "orders.html",
        {"request": request, "orders": orders}
    )

@app.get("/strategy/{strategy_id}")
def strategy(request: Request, strategy_id: int):
    """Strategy detail page: show all stocks assigned to a single strategy."""
    connection = sqlite3.connect(config.DB_FILE)
    connection.row_factory = sqlite3.Row

    cursor = connection.cursor()

    cursor.execute("""
        SELECT id, name
        FROM strategy
        WHERE id = ?
    """, (strategy_id,))

    strategy = cursor.fetchone()

    # JOIN here goes through stock_strategy (the many-to-many link table)
    # to pull every stock attached to this strategy_id — same pattern the
    # strategy scripts use when they pick up their symbol list each cron tick
    cursor.execute("""
        SELECT symbol, name, shortable
        FROM stock
        JOIN stock_strategy ON stock_strategy.stock_id = stock.id
        WHERE strategy_id = ?
    """, (strategy_id,))

    stocks = cursor.fetchall()
    connection.close()
    return templates.TemplateResponse(
        "strategy.html",
        {"request": request, "stocks": stocks, "strategy": strategy}
    )
