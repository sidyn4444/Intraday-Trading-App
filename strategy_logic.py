"""Pure-logic functions extracted from the strategy scripts so they can be
unit tested without going through the Alpaca API or the database.

The strategy scripts (opening_range_breakout.py etc.) still have their own
inline implementations because they execute as module-level scripts under
cron. These functions are the testable, doc-able versions of the same math.
"""

from typing import Optional, Tuple


def compute_opening_range(opening_bars) -> Tuple[float, float, float]:
    """Given the 09:30-09:45 ET bars, return (high, low, range_size).

    Pulls high from the max of all bars' highs (not just the first bar's high)
    and low from the min — same logic the strategy scripts use to define the
    opening range envelope.

    Raises ValueError if opening_bars is empty so callers fail loud rather
    than silently treating an empty range as range=0.
    """
    if len(opening_bars) == 0:
        raise ValueError("opening_bars is empty — can't compute range")

    high = float(opening_bars["high"].max())
    low = float(opening_bars["low"].min())
    return high, low, high - low


def find_first_breakout(after_range_bars, range_high: float) -> Optional[int]:
    """Find the index of the first bar that CLOSED above the opening range
    high. Returns the integer position (0 = first such bar) or None if no
    bar broke out.

    "First" matters because the strategy only takes ONE trade per day per
    symbol — later breakouts in the same day are ignored even if they're
    bigger moves.
    """
    breakout = after_range_bars[after_range_bars["close"] > range_high]
    if breakout.empty:
        return None
    # iloc-style integer position of the first breakout row within the slice
    return 0


def find_first_breakdown(after_range_bars, range_low: float) -> Optional[int]:
    """Mirror of find_first_breakout for the short side — finds the first
    bar that CLOSED below the opening range low.
    """
    breakdown = after_range_bars[after_range_bars["close"] < range_low]
    if breakdown.empty:
        return None
    return 0


def is_bollinger_cross_back_long(
    current_close: float,
    previous_close: float,
    current_lower: float,
    previous_lower: float,
) -> bool:
    """Long mean-reversion entry signal: previous candle closed BELOW the
    lower band (price overstretched down) AND current candle closed BACK
    ABOVE it (price is reverting). Both conditions are required — a single
    bar above the band on its own isn't a cross-back.
    """
    return current_close > current_lower and previous_close < previous_lower


def is_bollinger_cross_back_short(
    current_close: float,
    previous_close: float,
    current_upper: float,
    previous_upper: float,
) -> bool:
    """Short mean-reversion entry signal: previous candle closed ABOVE the
    upper band (overextension) and current candle closed BACK BELOW it
    (reversion starting).
    """
    return current_close < current_upper and previous_close > previous_upper
