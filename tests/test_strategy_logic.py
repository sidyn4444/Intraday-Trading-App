"""Tests for the pure-logic strategy functions in strategy_logic.py.

These don't touch Alpaca or the DB — they just exercise the math.
"""

import pandas as pd
import pytest

from strategy_logic import (
    compute_opening_range,
    find_first_breakout,
    find_first_breakdown,
    is_bollinger_cross_back_long,
    is_bollinger_cross_back_short,
)


# ---------- compute_opening_range ----------

def _bars(rows):
    """Helper: build a small DataFrame from a list of (open, high, low, close) tuples."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_opening_range_uses_full_window_highs_and_lows():
    # Three bars — high should be the max across them, low the min
    bars = _bars([
        (100, 101, 99, 100.5),
        (100.5, 102, 100, 101),    # this bar has the highest high
        (101, 101.5, 98, 99),       # this bar has the lowest low
    ])
    high, low, range_size = compute_opening_range(bars)
    assert high == 102
    assert low == 98
    assert range_size == 4


def test_opening_range_single_bar():
    bars = _bars([(50, 51, 49, 50.5)])
    high, low, range_size = compute_opening_range(bars)
    assert high == 51
    assert low == 49
    assert range_size == 2


def test_opening_range_empty_raises():
    """Empty range should fail loud rather than silently returning 0 —
    otherwise the strategy script would submit a bracket with 0 width."""
    empty = _bars([])
    with pytest.raises(ValueError):
        compute_opening_range(empty)


# ---------- find_first_breakout ----------

def test_breakout_detected_when_close_exceeds_range_high():
    # Range high = 102; later bar closes at 102.5 — that's a breakout
    after_range = _bars([
        (100, 101, 99, 100),     # below range
        (100, 102, 99.5, 101),   # at range high but didn't close above
        (101, 103, 101, 102.5),  # CLOSED above range_high=102 — breakout here
    ])
    idx = find_first_breakout(after_range, range_high=102.0)
    assert idx == 0  # signals there IS a breakout in this slice


def test_no_breakout_when_nothing_closes_above_range():
    after_range = _bars([
        (100, 101.5, 99, 100),
        (100, 101.9, 99.5, 101),
        (101, 101.99, 100, 101.5),
    ])
    assert find_first_breakout(after_range, range_high=102.0) is None


def test_breakout_requires_close_not_just_intraday_high():
    """A bar can spike to a new high but if it closes BELOW the range_high
    it doesn't count as a breakout. The strategy is close-based, not tick-based."""
    after_range = _bars([
        (100, 103, 99, 101),     # spiked to 103 but closed at 101 — not a breakout
        (101, 101.5, 100.5, 101),
    ])
    assert find_first_breakout(after_range, range_high=102.0) is None


# ---------- find_first_breakdown ----------

def test_breakdown_detected_when_close_falls_below_range_low():
    after_range = _bars([
        (100, 101, 99.5, 100),    # above range_low
        (100, 100, 98, 99.5),     # at range low but didn't close below
        (99.5, 99.5, 97, 98),     # CLOSED below range_low=99 — breakdown here
    ])
    idx = find_first_breakdown(after_range, range_low=99.0)
    assert idx == 0


def test_no_breakdown_when_nothing_closes_below_range():
    after_range = _bars([
        (100, 101, 99.5, 100),
        (100, 100.5, 99.2, 99.8),
    ])
    assert find_first_breakdown(after_range, range_low=99.0) is None


# ---------- Bollinger long cross-back ----------

def test_bollinger_long_signal_fires_on_cross_back_above_lower_band():
    # Previous bar closed BELOW lower band, current bar closed back ABOVE
    assert is_bollinger_cross_back_long(
        current_close=101,
        previous_close=99,       # was below previous lower band
        current_lower=100,
        previous_lower=100,
    ) is True


def test_bollinger_long_no_signal_if_previous_was_above_band():
    # If we were never below the band, there's no "cross-back" — just normal trading
    assert is_bollinger_cross_back_long(
        current_close=102,
        previous_close=101,      # was already above the band
        current_lower=100,
        previous_lower=100,
    ) is False


def test_bollinger_long_no_signal_if_still_below_band():
    # Previous was below, but current also closed below — no cross-back yet
    assert is_bollinger_cross_back_long(
        current_close=99.5,
        previous_close=99,
        current_lower=100,
        previous_lower=100,
    ) is False


# ---------- Bollinger short cross-back ----------

def test_bollinger_short_signal_fires_on_cross_back_below_upper_band():
    # Previous bar closed ABOVE upper band, current bar closed back BELOW
    assert is_bollinger_cross_back_short(
        current_close=99,
        previous_close=101,      # was above previous upper band
        current_upper=100,
        previous_upper=100,
    ) is True


def test_bollinger_short_no_signal_if_previous_was_below_band():
    assert is_bollinger_cross_back_short(
        current_close=98,
        previous_close=99,       # was already below band
        current_upper=100,
        previous_upper=100,
    ) is False


def test_bollinger_short_no_signal_if_still_above_band():
    # Previous was above, current also above — no cross-back yet
    assert is_bollinger_cross_back_short(
        current_close=101,
        previous_close=102,
        current_upper=100,
        previous_upper=100,
    ) is False


# ---------- boundary / strict-comparison edge cases ----------

def test_breakout_does_NOT_fire_when_close_equals_range_high():
    """The strategy uses strict > comparison. A bar that closes EXACTLY at the
    range high is treated as 'inside the range', not a breakout. Documents the
    design decision so future engineers don't change > to >=."""
    after_range = _bars([
        (100, 102, 99, 102.0),    # close == range_high (not strictly above)
        (102, 102, 101.5, 101.9), # close < range_high
    ])
    assert find_first_breakout(after_range, range_high=102.0) is None


def test_breakdown_does_NOT_fire_when_close_equals_range_low():
    """Mirror — strict < comparison on the short side."""
    after_range = _bars([
        (100, 101, 98, 99.0),     # close == range_low, NOT a breakdown
        (99, 99.5, 98.5, 99.1),
    ])
    assert find_first_breakdown(after_range, range_low=99.0) is None


def test_bollinger_long_does_NOT_fire_when_current_close_equals_lower():
    """Long entry needs current_close > current_lower (strict). A close exactly
    AT the band is not a cross-back — price needs to be visibly back inside."""
    assert is_bollinger_cross_back_long(
        current_close=100,         # exactly at the band
        previous_close=99,
        current_lower=100,
        previous_lower=100,
    ) is False


def test_bollinger_short_does_NOT_fire_when_current_close_equals_upper():
    """Mirror — strict < on the short side."""
    assert is_bollinger_cross_back_short(
        current_close=100,
        previous_close=101,
        current_upper=100,
        previous_upper=100,
    ) is False


def test_opening_range_flat_bars_produces_zero_range():
    """All four bars at the same exact price (halted stock, illiquid name)
    produces a 0-width range. The strategy script checks for this with
    `if opening_range <= 0` and skips the symbol — this test confirms
    `compute_opening_range` reports it accurately without crashing."""
    bars = _bars([
        (100, 100, 100, 100),
        (100, 100, 100, 100),
        (100, 100, 100, 100),
    ])
    high, low, range_size = compute_opening_range(bars)
    assert high == 100
    assert low == 100
    assert range_size == 0
