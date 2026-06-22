import math

def calculate_quantity(price):
    """Dollar-capped position sizing.

    Returns how many shares to buy so the total cost stays at or under $10K.
    Using floor() because Alpaca rejects fractional shares on limit orders
    and rounding up could push us over the cap.
    """
    quantity = math.floor(10000 / price)

    return quantity


def round_to_penny(x: float) -> float:
    """Round a price to 2 decimals (one cent).

    The +1e-9 nudge avoids the classic float case where 0.005 silently
    rounds DOWN to 0.00 because of binary representation. Used by every
    strategy script when setting limit_price, take_profit, and stop_loss
    on bracket orders before sending to Alpaca.
    """
    return round(float(x) + 1e-9, 2)
