"""Configuration loaded from environment variables.

Local dev:  values come from a gitignored .env file via python-dotenv
Production: values come from the cloud platform's secret store
            (Railway / Fly.io / etc.) injected before this code runs

Required vars (script crashes loud on startup if missing):
    ALPACA_API_KEY, ALPACA_SECRET_KEY, DB_FILE

Optional vars (use sensible defaults):
    ALPACA_API_URL  -> paper trading URL
    EMAIL_*         -> Gmail SMTP, empty strings disable notifications cleanly
                       thanks to the graceful-degradation check in the strategy scripts
"""

import os
from dotenv import load_dotenv

# Reads .env into os.environ when running locally.
# In production (Railway/Fly/etc.), there's no .env file - this becomes a
# silent no-op because the platform already populated os.environ before
# Python started. MUST run before any os.environ reads below.
load_dotenv()

# ---- Required: fail loud if missing ----
# KeyError on startup is the GOOD failure mode here - better than silently
# misbehaving with empty strings. The error message names the missing var.
API_KEY = os.environ['ALPACA_API_KEY']
SECRET_KEY = os.environ['ALPACA_SECRET_KEY']
DB_FILE = os.environ['DB_FILE']

# ---- Optional: defaults if missing ----
# Paper trading URL is the default so a missing env var never accidentally
# hits live trading.
API_URL = os.environ.get('ALPACA_API_URL', 'https://paper-api.alpaca.markets')

# Email vars default to empty so the strategy scripts' email graceful
# degradation check does the right thing when SMTP isn't configured.
EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')

# int() cast because env vars are ALWAYS strings - smtplib needs an int port
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '465'))
