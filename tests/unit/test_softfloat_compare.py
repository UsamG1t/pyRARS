"""Comparisons, minimum and maximum.

Expected values are from the ISA manual v20260120, chapter F: the compare
instructions (FEQ signals only for a signalling NaN, FLT and FLE for any NaN)
and the minimum/maximum instructions (a NaN operand is skipped, two NaNs give
the canonical NaN, a negative zero is smaller than a positive one).
"""

import pytest

from pyrars.softfloat.compare import equal, less, less_equal, maximum, minimum
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NV

ONE = 0x3F800000
TWO = 0x40000000
MINUS_ONE = 0xBF800000
MINUS_TWO = 0xC0000000
PLUS_ZERO = 0x00000000
MINUS_ZERO = 0x80000000
PLUS_INFINITY = 0x7F800000
MINUS_INFINITY = 0xFF800000
QUIET = 0x7FC00000
SIGNALLING = 0x7F800001


@pytest.mark.parametrize("a, b, expected", [
    (ONE, ONE, True),
    (ONE, TWO, False),
    (PLUS_ZERO, MINUS_ZERO, True),  # the two zeros are equal
    (MINUS_ONE, ONE, False),
    (PLUS_INFINITY, PLUS_INFINITY, True),
    (PLUS_INFINITY, MINUS_INFINITY, False),
])
def test_equality_of_numbers(a, b, expected):
    assert equal(a, b, BINARY32) == (expected, 0)
    assert equal(b, a, BINARY32) == (expected, 0)


@pytest.mark.parametrize("a, b, is_less, is_less_equal", [
    (ONE, TWO, True, True),
    (TWO, ONE, False, False),
    (ONE, ONE, False, True),
    (MINUS_TWO, MINUS_ONE, True, True),  # the order of negative numbers is turned around
    (MINUS_ONE, MINUS_TWO, False, False),
    (MINUS_ZERO, PLUS_ZERO, False, True),  # equal, so neither is less
    (MINUS_INFINITY, MINUS_TWO, True, True),
    (TWO, PLUS_INFINITY, True, True),
])
def test_less_than(a, b, is_less, is_less_equal):
    assert less(a, b, BINARY32) == (is_less, 0)
    assert less_equal(a, b, BINARY32) == (is_less_equal, 0)


def test_a_quiet_nan_is_unequal_without_a_flag():
    """FEQ is the quiet comparison: only a signalling NaN raises a flag."""
    assert equal(QUIET, ONE, BINARY32) == (False, 0)
    assert equal(QUIET, QUIET, BINARY32) == (False, 0)
    assert equal(ONE, QUIET, BINARY32) == (False, 0)


def test_a_signalling_nan_is_unequal_and_raises_the_flag():
    assert equal(SIGNALLING, ONE, BINARY32) == (False, NV)
    assert equal(ONE, SIGNALLING, BINARY32) == (False, NV)


@pytest.mark.parametrize("nan", [QUIET, SIGNALLING])
def test_an_order_comparison_with_a_nan_raises_the_flag(nan):
    assert less(nan, ONE, BINARY32) == (False, NV)
    assert less(ONE, nan, BINARY32) == (False, NV)
    assert less_equal(nan, ONE, BINARY32) == (False, NV)
    assert less_equal(nan, nan, BINARY32) == (False, NV)


@pytest.mark.parametrize("a, b, smallest, largest", [
    (ONE, TWO, ONE, TWO),
    (MINUS_ONE, ONE, MINUS_ONE, ONE),
    (MINUS_INFINITY, MINUS_TWO, MINUS_INFINITY, MINUS_TWO),
    (PLUS_INFINITY, ONE, ONE, PLUS_INFINITY),
    (MINUS_ZERO, PLUS_ZERO, MINUS_ZERO, PLUS_ZERO),  # the signs decide
])
def test_minimum_and_maximum_of_numbers(a, b, smallest, largest):
    assert minimum(a, b, BINARY32) == (smallest, 0)
    assert minimum(b, a, BINARY32) == (smallest, 0)
    assert maximum(a, b, BINARY32) == (largest, 0)
    assert maximum(b, a, BINARY32) == (largest, 0)


def test_a_nan_operand_is_skipped():
    assert minimum(QUIET, ONE, BINARY32) == (ONE, 0)
    assert maximum(ONE, QUIET, BINARY32) == (ONE, 0)
    # a signalling NaN is skipped as well, but it raises the flag
    assert minimum(SIGNALLING, ONE, BINARY32) == (ONE, NV)
    assert maximum(SIGNALLING, ONE, BINARY32) == (ONE, NV)


def test_two_nan_operands_give_the_canonical_nan():
    assert minimum(QUIET, QUIET, BINARY32) == (BINARY32.canonical_nan, 0)
    assert minimum(SIGNALLING, QUIET, BINARY32) == (BINARY32.canonical_nan, NV)
    assert maximum(SIGNALLING, SIGNALLING, BINARY32) == (BINARY32.canonical_nan, NV)


def test_the_same_rules_hold_for_a_double():
    one, two = 0x3FF0000000000000, 0x4000000000000000
    quiet, signalling = 0x7FF8000000000000, 0x7FF0000000000001
    assert equal(one, one, BINARY64) == (True, 0)
    assert equal(quiet, one, BINARY64) == (False, 0)
    assert less(one, two, BINARY64) == (True, 0)
    assert less(signalling, two, BINARY64) == (False, NV)
    assert minimum(0x8000000000000000, 0, BINARY64) == (0x8000000000000000, 0)
    assert maximum(quiet, two, BINARY64) == (two, 0)
