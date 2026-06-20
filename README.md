# Intraday Trading App

FastAPI dashboard and a cron-driven Python trading bot against the Alpaca paper trading API. Screens ~10K tradable symbols across 8 technical filters, runs four intraday strategies, and flattens all positions 30 minutes before market close.

Paper trading only (`paper-api.alpaca.markets`). No real capital is at risk.

## Components

| File | Responsibility |
|---|---|
| `main.py` | FastAPI app. Routes: stock browser with 8 filter modes, per-stock detail with daily bars, strategy assignment (POST), per-strategy view, live order list from Alpaca. |
| `create_db.py` | SQLite schema. Tables: `stock`, `stock_price`, `strategy`, `stock_strategy`. |
| `populate_stocks.py` | Seeds `stock` from Alpaca's tradable assets endpoint. |
| `populate_prices.py` | Seeds `stock_price` with daily bars and tulipy-computed RSI-14, SMA-20, SMA-50. |
| `opening_range_breakout.py` | Long on break above the 15-min opening range. Bracket order with 1× range take-profit and 1× range stop-loss. |
| `opening_range_breakdown.py` | Short on break below the 15-min opening range. Same bracket structure. |
| `bollinger_bands.py` | Mean reversion long: enters on cross back above the lower 20-period band. |
| `bollinger_bands_short.py` | Mean reversion short: enters on cross back below the upper 20-period band. |
| `daily_close.py` | Calls `api.cancel_all_orders()` then `api.close_all_positions()`. Scheduled at 15:30 ET. |
| `helpers.py` | `calculate_quantity(price)` returns `math.floor(10000 / price)`. Used by all four strategies. |

## Architecture

```
                  ┌─────────────────────────────────────────┐
                  │              cron scheduler             │
                  └─────┬──────────────────────────┬────────┘
                        │                          │
               Mon-Fri 9:46-15:25 ET        Sundays 21:00 ET
                 every 5 minutes              + Daily 17:00
                        │                          │
                        ▼                          ▼
              ┌──────────────────┐       ┌──────────────────┐
              │ Strategy scripts │       │ populate_stocks  │
              │   (4 of them)    │       │ populate_prices  │
              └────────┬─────────┘       └────────┬─────────┘
                       │                          │
                       ▼                          ▼
              ┌──────────────────┐       ┌──────────────────┐
              │   Alpaca REST    │       │     SQLite       │
              │  (paper trading) │◀──────│    (app.db)      │
              └────────┬─────────┘       └────────┬─────────┘
                       │                          │
                       │                          ▼
                       │              ┌──────────────────────┐
                       │              │  FastAPI dashboard   │
                       └─────────────▶│  (Jinja2 templates)  │
                                      └──────────────────────┘
```

## Setup

Python 3.10+, an Alpaca paper trading account, and a Gmail account with an [app password](https://support.google.com/accounts/answer/185833). The four strategy scripts use stdlib `smtplib` to email a notification on each fill — no SMTP creds means the scripts will fail at the email step.

```bash
git clone https://github.com/sidyn4444/Intraday-Trading-App.git
cd Intraday-Trading-App

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp config.example.py config.py
# Set in config.py:
#   API_KEY, SECRET_KEY              from the Alpaca paper account
#   DB_FILE                          absolute path to app.db
#   EMAIL_ADDRESS, EMAIL_PASSWORD    Gmail address + app password
#   API_URL, EMAIL_HOST, EMAIL_PORT  defaults already correct

python create_db.py
python populate_stocks.py
python populate_prices.py

uvicorn main:app --reload
```

## Scheduling

Strategies run via cron. Cron has no clean expression for "every 5 minutes from 9:46 to 15:25 ET," so each strategy is three lines:

```cron
46,51,56 9 * * 1-5            /abs/path/venv/bin/python opening_range_breakout.py
*/5 10-14 * * 1-5             /abs/path/venv/bin/python opening_range_breakout.py
0,5,10,15,20,25 15 * * 1-5    /abs/path/venv/bin/python opening_range_breakout.py
```

Repeat for the other three strategies. Schedule `daily_close.py` at `30 15 * * 1-5`. The 5-minute gap between the last strategy run (15:25) and the daily close (15:30) prevents a strategy entry from opening a position after the close-out script has already run.

`populate_stocks.py` runs weekly (Sundays 21:00), `populate_prices.py` daily (Mon-Fri 17:00).

Cron's PATH does not include the venv, so every entry must reference `venv/bin/python` by absolute path.

## Risk controls

- **Position sizing**: `helpers.calculate_quantity(price)` caps each entry at ~$10K regardless of share price. A hardcoded `qty=100` on a $3K share would consume $300K of buying power; this prevents that.
- **Bracket orders**: every entry submits with `take_profit` and `stop_loss` legs in the same `api.submit_order()` call. Alpaca handles OCO server-side.
- **End-of-day flatten**: `daily_close.py` cancels open orders and closes all positions at 15:30 ET. Nothing is held overnight.


## Stack

FastAPI · Jinja2 · SQLite · alpaca-trade-api · tulipy · pandas


## Disclaimer

This code trades against `paper-api.alpaca.markets` so it does not use real money. Use real money at your own risk.

