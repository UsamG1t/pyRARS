"""Conversions between the formats and the integers.

Expected values are derived by hand from the RISC-V ISA manual v20260120,
chapters F and D: the conversions saturate at the ends of the integer range and
raise the invalid operation flag there, a NaN gives the largest value, and the
rounding of a fractional part follows the mode like any other rounding.
"""

import pytest

from pyrars.softfloat.convert import from_integer, to_format, to_integer
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NV, NX, OF, RDN, RMM, RNE, RTZ, RUP

TWO_AND_A_HALF = 0x40200000
MINUS_TWO_AND_A_HALF = 0xC0200000
A_HALF = 0x3F000000
MINUS_A_HALF = 0xBF000000
TWO = 0x40000000
TEN_BILLION = 0x501502F9  # 1e10, which a single holds exactly
LARGEST = 0x7F7FFFFF
PLUS_INFINITY = 0x7F800000
MINUS_INFINITY = 0xFF800000
CANONICAL = 0x7FC00000
SIGNALLING = 0x7F800001


@pytest.mark.parametrize("mode, two_and_a_half, minus, a_half", [
    (RNE, 2, -2, 0),  # a tie goes to the even number (DEV-35: RARS gives 3 and -3)
    (RMM, 3, -3, 1),  # a tie goes away from zero
    (RTZ, 2, -2, 0),
    (RDN, 2, -3, 0),
    (RUP, 3, -2, 1),
])
def test_the_rounding_of_a_conversion_to_an_integer(mode, two_and_a_half, minus, a_half):
    assert to_integer(TWO_AND_A_HALF, BINARY32, 32, True, mode) == (two_and_a_half, NX)
    assert to_integer(MINUS_TWO_AND_A_HALF, BINARY32, 32, True, mode) == (minus, NX)
    assert to_integer(A_HALF, BINARY32, 32, True, mode) == (a_half, NX)


@pytest.mark.parametrize("bits, width, signed, expected, flags", [
    (TWO, 32, True, 2, 0),
    (TWO, 32, False, 2, 0),
    (0xC0000000, 32, True, -2, 0),  # -2.0
    (TEN_BILLION, 32, True, 2147483647, NV),  # beyond a 32-bit integer
    (TEN_BILLION, 64, True, 10000000000, 0),  # but a 64-bit one holds it
    (TEN_BILLION, 32, False, 4294967295, NV),
    (0x4F000000, 32, True, 2147483647, NV),  # 2**31 is one beyond the range
    (0x4EFFFFFF, 32, True, 2147483520, 0),  # the largest single below 2**31
    (0xCF000000, 32, True, -2147483648, 0),  # -2**31 is the end of the range
    (0xBF800000, 32, False, 0, NV),  # -1.0 has no unsigned value
    (MINUS_A_HALF, 32, False, 0, NX),  # but -0.5 rounds to zero, which has one
    (MINUS_TWO_AND_A_HALF, 32, False, 0, NV),  # -2.5 saturates: no inexact flag (DEV-41)
    (MINUS_TWO_AND_A_HALF, 64, False, 0, NV),  # beside the range, the width does not matter
    (LARGEST, 64, True, (1 << 63) - 1, NV),
    (PLUS_INFINITY, 32, True, 2147483647, NV),
    (MINUS_INFINITY, 32, True, -2147483648, NV),
    (MINUS_INFINITY, 32, False, 0, NV),
    (CANONICAL, 32, True, 2147483647, NV),
    (CANONICAL, 32, False, 4294967295, NV),
    (SIGNALLING, 64, True, (1 << 63) - 1, NV),
    (0x00000001, 32, True, 0, NX),  # the least subnormal is not zero
    (0x00000000, 32, True, 0, 0),
    (0x80000000, 32, False, 0, 0),  # a negative zero is still zero
])
def test_a_conversion_to_an_integer(bits, width, signed, expected, flags):
    assert to_integer(bits, BINARY32, width, signed, RNE) == (expected, flags)


def test_a_conversion_of_a_double_to_an_integer():
    assert to_integer(0x3FF8000000000000, BINARY64, 32, True, RNE) == (2, NX)  # 1.5
    assert to_integer(0x43E0000000000000, BINARY64, 64, True, RNE) == ((1 << 63) - 1, NV)
    assert to_integer(0x7FF8000000000000, BINARY64, 64, False, RNE) == ((1 << 64) - 1, NV)


@pytest.mark.parametrize("value, expected, flags", [
    (0, 0x00000000, 0),  # zero is positive, never negative
    (1, 0x3F800000, 0),
    (-1, 0xBF800000, 0),
    (2, TWO, 0),
    (16777216, 0x4B800000, 0),  # 2**24 still fits the significand
    (16777217, 0x4B800000, NX),  # one more is a tie, down to the even number
    (16777219, 0x4B800002, NX),  # a tie the other way
    (-16777217, 0xCB800000, NX),
    (10000000000, TEN_BILLION, 0),
])
def test_a_conversion_from_an_integer(value, expected, flags):
    assert from_integer(value, BINARY32, RNE) == (expected, flags)


def test_a_conversion_from_an_integer_of_64_bits():
    assert from_integer((1 << 63) - 1, BINARY64, RNE) == (0x43E0000000000000, NX)
    assert from_integer(1 << 62, BINARY64, RNE) == (0x43D0000000000000, 0)
    assert from_integer((1 << 64) - 1, BINARY32, RNE) == (0x5F800000, NX)


@pytest.mark.parametrize("bits, expected, flags", [
    (0x3F800000, 0x3FF0000000000000, 0),
    (0xBF800000, 0xBFF0000000000000, 0),
    (0x00000001, 0x36A0000000000000, 0),  # a subnormal single is a normal double
    (0x00000000, 0x0000000000000000, 0),
    (0x80000000, 0x8000000000000000, 0),
    (PLUS_INFINITY, 0x7FF0000000000000, 0),
    (MINUS_INFINITY, 0xFFF0000000000000, 0),
    (CANONICAL, 0x7FF8000000000000, 0),
    (SIGNALLING, 0x7FF8000000000000, NV),
])
def test_widening_a_single_to_a_double(bits, expected, flags):
    assert to_format(bits, BINARY32, BINARY64, RNE) == (expected, flags)


@pytest.mark.parametrize("bits, expected, flags", [
    (0x3FF0000000000000, 0x3F800000, 0),
    (0x3FF0000010000000, 0x3F800000, NX),  # 1 + 2**-24: a tie, to the even number
    (0x3FF0000030000000, 0x3F800002, NX),  # 1 + 3 * 2**-24: a tie, upward
    (0x7E37E43C8800759C, PLUS_INFINITY, OF | NX),  # 1e300 is far beyond a single
    (0x3750000000000000, 0x00000800, 0),  # 2**-138 is an exact subnormal single
    (0x36A0000000000000, 0x00000001, 0),  # 2**-149, the least subnormal single
    (0x7FF8000000000001, CANONICAL, 0),
    (0x7FF0000000000001, CANONICAL, NV),
])
def test_narrowing_a_double_to_a_single(bits, expected, flags):
    assert to_format(bits, BINARY64, BINARY32, RNE) == (expected, flags)
