import math

def calculate_quantity(price):
    """Dollar-capped position sizing.

    Returns how many shares to buy so the total cost stays at or under $10K.
    Using floor() because Alpaca rejects fractional shares on limit orders
    and rounding up could push us over the cap.
    """
    quantity = math.floor(10000 / price)

    return quantity
