# Copy this file to config.py and fill in your credentials.
# config.py is gitignored so your real keys never get committed.

# Alpaca paper trading account: sign up free at https://alpaca.markets/
# After signing up, generate keys at https://app.alpaca.markets/paper/dashboard/overview
API_URL = 'https://paper-api.alpaca.markets'
API_KEY = 'YOUR_API_KEY_HERE'
SECRET_KEY = 'YOUR_SECRET_KEY_HERE'

# Absolute path to where SQLite should store the database file.
DB_FILE = '/path/to/your/database/app.db'

# Gmail app password (NOT your regular Gmail password) for trade notifications.
# Generate one at https://myaccount.google.com/apppasswords after enabling 2FA.
# Leave EMAIL_ADDRESS empty to disable email notifications entirely.
EMAIL_ADDRESS = 'your-email@gmail.com'
EMAIL_PASSWORD = 'your-app-password'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 465
