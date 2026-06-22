"""Tests for helpers.calculate_quantity and helpers.round_to_penny.

calculate_quantity returns math.floor(10000 / price), so we want to verify it:
  - returns the right share count for normal prices
  - rounds DOWN so we never exceed the $10K cap
  - returns 0 for shares too expensive to fit in the budget

round_to_penny rounds to 2 decimals using a +1e-9 nudge to avoid the float
artifact where 0.005 silently rounds DOWN to 0.00 in Python's default round().
"""

import math
import pytest

from helpers import calculate_quantity, round_to_penny


# ----- calculate_quantity -----

def test_normal_price_returns_expected_share_count():
    # $50 share -> 10000 / 50 = 200 shares, exact
    assert calculate_quantity(50) == 200


def test_expensive_share_returns_few_shares():
    # $3000 share -> floor(10000 / 3000) = floor(3.33...) = 3 shares
    # Real-world case: Amazon used to trade around this price
    assert calculate_quantity(3000) == 3


def test_cheap_share_returns_many_shares():
    # $1 share -> 10000 shares
    assert calculate_quantity(1) == 10000


def test_price_with_remainder_rounds_down():
    # $33 share -> floor(10000 / 33) = floor(303.03...) = 303
    # If we rounded UP to 304, total cost = 304 * 33 = 10,032 -> over the cap
    # floor() keeps us under: 303 * 33 = 9,999
    quantity = calculate_quantity(33)
    assert quantity == 303
    assert quantity * 33 <= 10000  # never over the cap


def test_float_price_handled():
    # $123.45 share -> floor(10000 / 123.45) = floor(81.00...) = 81
    quantity = calculate_quantity(123.45)
    assert quantity == 81
    assert quantity * 123.45 <= 10000


def test_share_more_expensive_than_budget_returns_zero():
    # Berkshire Hathaway Class A trades above $500K, and even a $15K share
    # exceeds the per-trade cap -> floor(10000 / 15000) = 0
    # The strategy script's `qty=0` submit would be rejected by Alpaca,
    # which is the correct behavior — we don't want to over-allocate.
    assert calculate_quantity(15000) == 0


def test_share_exactly_at_budget_returns_one():
    # $10000 share -> exactly 1 share
    assert calculate_quantity(10000) == 1


# ----- round_to_penny -----

def test_round_to_penny_normal_price():
    # Typical case: 4-decimal Alpaca price truncates to 2 decimals
    assert round_to_penny(123.4567) == 123.46


def test_round_to_penny_already_at_two_decimals():
    # Already-rounded prices pass through unchanged
    assert round_to_penny(50.00) == 50.00


def test_round_to_penny_half_cent_rounds_up():
    # 0.005 is the case that breaks Python's default round() because of
    # binary float representation — 0.005 is actually slightly less than
    # half a cent, so round() rounds it DOWN to 0.00 instead of up to 0.01.
    # The +1e-9 nudge in our implementation fixes this so 0.005 -> 0.01.
    assert round_to_penny(0.005) == 0.01


def test_round_to_penny_zero():
    assert round_to_penny(0) == 0.00

