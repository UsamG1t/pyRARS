"""Rounding of an exact value to a format, and the flags it raises.

Expected values are derived by hand from IEEE 754-2019: §4.3.1 (the two
directions to nearest), §4.3.2 (toward zero, up and down), §7.4 (what an
overflowing result becomes in each direction) and §7.5 (underflow). Tininess is
detected before rounding, as in RARS (see rounding.py).

A value is given to `round_value` as (sign, exponent, significand), meaning
(-1)**sign * significand * 2**exponent, so every expected result can be read
from the value itself without any floating point arithmetic.
"""

import pytest

from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NX, OF, RDN, RMM, RNE, RTZ, RUP, UF, round_value

ONE = 0x3F800000
LARGEST32 = 0x7F7FFFFF
INFINITY32 = 0x7F800000


def test_a_value_that_fits_is_not_changed():
    assert round_value(False, -23, 0x800000, BINARY32, RNE) == (ONE, 0)
    assert round_value(True, -22, 0xA00000, BINARY32, RNE) == (0xC0200000, 0)
    assert round_value(False, 104, 0xFFFFFF, BINARY32, RNE) == (LARGEST32, 0)
    assert round_value(False, -149, 2, BINARY32, RNE) == (0x00000002, 0)
    assert round_value(False, -52, 1 << 52, BINARY64, RNE) == (0x3FF0000000000000, 0)


@pytest.mark.parametrize("negative, expected", [(False, 0x00000000), (True, 0x80000000)])
def test_a_zero_keeps_its_sign(negative, expected):
    assert round_value(negative, 0, 0, BINARY32, RNE) == (expected, 0)
    assert round_value(negative, 17, 0, BINARY32, RTZ) == (expected, 0)


# 1 + 2**-24 lies exactly between 1 and 1 + 2**-23: the tie goes to the even
# significand, which is the one of 1.0. 1 + 3 * 2**-24 lies between
# 1 + 2**-23 and 1 + 2**-22, and there the even significand is the upper one.
@pytest.mark.parametrize("mode, lower_tie, upper_tie", [
    (RNE, ONE, 0x3F800002),
    (RMM, 0x3F800001, 0x3F800002),
    (RTZ, ONE, 0x3F800001),
    (RDN, ONE, 0x3F800001),
    (RUP, 0x3F800001, 0x3F800002),
])
def test_a_tie_is_broken_by_the_mode(mode, lower_tie, upper_tie):
    assert round_value(False, -24, 2**24 + 1, BINARY32, mode) == (lower_tie, NX)
    assert round_value(False, -24, 2**24 + 3, BINARY32, mode) == (upper_tie, NX)


@pytest.mark.parametrize("mode, expected", [
    (RNE, 0xBF800000), (RMM, 0xBF800001), (RTZ, 0xBF800000),
    (RDN, 0xBF800001), (RUP, 0xBF800000),
])
def test_up_and_down_follow_the_sign(mode, expected):
    """RDN and RUP round toward minus and plus infinity, not away from zero."""
    assert round_value(True, -24, 2**24 + 1, BINARY32, mode) == (expected, NX)


def test_a_value_below_half_a_step_is_rounded_down_to_nearest():
    # 1 + 2**-25 is a quarter of a step above 1.0
    assert round_value(False, -25, 2**25 + 1, BINARY32, RNE) == (ONE, NX)
    assert round_value(False, -25, 2**25 + 1, BINARY32, RMM) == (ONE, NX)
    assert round_value(False, -25, 2**25 + 1, BINARY32, RUP) == (0x3F800001, NX)


def test_the_carry_of_a_rounding_reaches_the_exponent():
    # the largest value below 2.0 plus half a step: rounds up to 2.0 exactly
    assert round_value(False, -24, 2**25 - 1, BINARY32, RNE) == (0x40000000, NX)


# ------------------------------------------------------------------ underflow


def test_a_tiny_exact_value_raises_nothing():
    assert round_value(False, -149, 1, BINARY32, RNE) == (0x00000001, 0)
    assert round_value(False, -1074, 3, BINARY64, RNE) == (0x0000000000000003, 0)


def test_a_tiny_inexact_value_underflows():
    # 3 * 2**-150 is 1.5 steps of the subnormal grid: the tie goes to 2 steps
    assert round_value(False, -150, 3, BINARY32, RNE) == (0x00000002, NX | UF)
    # half a step: the tie goes to zero, which is inexact and tiny as well
    assert round_value(False, -150, 1, BINARY32, RNE) == (0x00000000, NX | UF)
    assert round_value(True, -150, 1, BINARY32, RNE) == (0x80000000, NX | UF)
    # rounded away from zero, half a step becomes the least subnormal
    assert round_value(False, -150, 1, BINARY32, RUP) == (0x00000001, NX | UF)


def test_a_tiny_value_that_grows_into_the_smallest_normal_still_underflows():
    """Tininess before rounding: the result is normal, the flag is raised."""
    assert round_value(False, -150, 2**24 - 1, BINARY32, RNE) == (0x00800000, NX | UF)


def test_a_value_at_the_smallest_normal_does_not_underflow():
    assert round_value(False, -149, 1 << 23, BINARY32, RNE) == (0x00800000, 0)
    # inexact but not tiny: the value is above the smallest normal
    assert round_value(False, -150, 2**24 + 1, BINARY32, RNE) == (0x00800000, NX)


# ------------------------------------------------------------------- overflow


@pytest.mark.parametrize("mode, positive, negative", [
    (RNE, INFINITY32, 0xFF800000),
    (RMM, INFINITY32, 0xFF800000),
    (RTZ, LARGEST32, 0xFF7FFFFF),
    (RDN, LARGEST32, 0xFF800000),
    (RUP, INFINITY32, 0xFF7FFFFF),
])
def test_an_overflowing_value_follows_the_direction(mode, positive, negative):
    assert round_value(False, 128, 1, BINARY32, mode) == (positive, OF | NX)
    assert round_value(True, 128, 1, BINARY32, mode) == (negative, OF | NX)


def test_a_value_rounded_up_into_the_overflow():
    """2**128 - 2**103 is finite, but rounding it to 24 bits reaches 2**128."""
    assert round_value(False, 103, 2**25 - 1, BINARY32, RNE) == (INFINITY32, OF | NX)
    assert round_value(False, 103, 2**25 - 1, BINARY32, RTZ) == (LARGEST32, NX)


def test_the_largest_finite_double():
    assert round_value(False, 971, 2**53 - 1, BINARY64, RNE) == (0x7FEFFFFFFFFFFFFF, 0)
    assert round_value(False, 1024, 1, BINARY64, RNE) == (0x7FF0000000000000, OF | NX)
