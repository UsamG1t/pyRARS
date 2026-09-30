"""Formats, reading of a bit pattern, classification and NaN boxing.

Expected values are written from IEEE 754-2019 §3.4 (the widths and the bias of
binary32 and binary64) and from the ISA manual chapters F and D (the bits of
FCLASS, the boxing of a single precision value in a 64-bit register).
"""

from fractions import Fraction

import pytest

from pyrars.softfloat import formats
from pyrars.softfloat.formats import BINARY32, BINARY64

# Values used in several tests: the name says what the number is.
ONE = 0x3F800000
MINUS_ONE = 0xBF800000
MINUS_TWO_AND_A_HALF = 0xC0200000
LARGEST = 0x7F7FFFFF
LEAST_SUBNORMAL = 0x00000001
INFINITY = 0x7F800000
SIGNALLING = 0x7F800001
QUIET = 0x7FC00000


def test_binary32_has_the_widths_of_the_standard():
    assert (BINARY32.width, BINARY32.exponent_bits, BINARY32.significand_bits) == (32, 8, 23)
    assert BINARY32.bias == 127
    assert (BINARY32.min_exponent, BINARY32.max_exponent) == (-126, 127)
    assert BINARY32.least_exponent == -149  # the exponent of the least subnormal
    assert BINARY32.sign_mask == 0x80000000
    assert BINARY32.significand_mask == 0x007FFFFF
    assert BINARY32.exponent_field_mask == 0x7F800000
    assert (BINARY32.infinity, BINARY32.canonical_nan, BINARY32.largest) == (
        0x7F800000, 0x7FC00000, 0x7F7FFFFF)


def test_binary64_has_the_widths_of_the_standard():
    assert (BINARY64.width, BINARY64.exponent_bits, BINARY64.significand_bits) == (64, 11, 52)
    assert BINARY64.bias == 1023
    assert (BINARY64.min_exponent, BINARY64.max_exponent) == (-1022, 1023)
    assert BINARY64.least_exponent == -1074
    assert BINARY64.sign_mask == 1 << 63
    assert BINARY64.significand_mask == 0x000FFFFFFFFFFFFF
    assert (BINARY64.infinity, BINARY64.canonical_nan, BINARY64.largest) == (
        0x7FF0000000000000, 0x7FF8000000000000, 0x7FEFFFFFFFFFFFFF)


@pytest.mark.parametrize("bits, fmt, expected, value", [
    (ONE, BINARY32, (False, -23, 0x800000), Fraction(1)),
    (MINUS_TWO_AND_A_HALF, BINARY32, (True, -22, 0xA00000), Fraction(-5, 2)),
    (LEAST_SUBNORMAL, BINARY32, (False, -149, 1), Fraction(1, 2**149)),
    (LARGEST, BINARY32, (False, 104, 0xFFFFFF), Fraction(2**128 - 2**104)),
    (0x00000000, BINARY32, (False, -149, 0), Fraction(0)),
    (0x80000000, BINARY32, (True, -149, 0), Fraction(0)),
    (0x3FF0000000000000, BINARY64, (False, -52, 1 << 52), Fraction(1)),
    (0x0000000000000001, BINARY64, (False, -1074, 1), Fraction(1, 2**1074)),
])
def test_a_finite_number_is_read_as_three_integers(bits, fmt, expected, value):
    assert formats.decode(bits, fmt) == expected
    negative, exponent, significand = expected
    # the three integers stand for the number they were read from
    read = Fraction(significand) * Fraction(2) ** exponent
    assert (-read if negative else read) == value


@pytest.mark.parametrize("bits, expected", [
    (0xFF800000, formats.NEGATIVE_INFINITY),
    (MINUS_ONE, formats.NEGATIVE_NORMAL),
    (0x80000001, formats.NEGATIVE_SUBNORMAL),
    (0x80000000, formats.NEGATIVE_ZERO),
    (0x00000000, formats.POSITIVE_ZERO),
    (LEAST_SUBNORMAL, formats.POSITIVE_SUBNORMAL),
    (ONE, formats.POSITIVE_NORMAL),
    (INFINITY, formats.POSITIVE_INFINITY),
    (SIGNALLING, formats.SIGNALLING_NAN),
    (QUIET, formats.QUIET_NAN),
    (0xFFFFFFFF, formats.QUIET_NAN),  # a negative NaN is still classified as a NaN
])
def test_classify_names_the_class_of_a_number(bits, expected):
    assert formats.classify(bits, BINARY32) == expected
    assert formats.classify(bits, BINARY32).bit_count() == 1


@pytest.mark.parametrize("bits, expected", [
    (0xFFF0000000000000, formats.NEGATIVE_INFINITY),
    (0x8000000000000000, formats.NEGATIVE_ZERO),
    (0x0000000000000001, formats.POSITIVE_SUBNORMAL),
    (0x3FF0000000000000, formats.POSITIVE_NORMAL),
    (0x7FF0000000000001, formats.SIGNALLING_NAN),
    (0x7FF8000000000000, formats.QUIET_NAN),
])
def test_classify_of_a_double(bits, expected):
    assert formats.classify(bits, BINARY64) == expected


def test_the_predicates_of_a_bit_pattern():
    assert formats.is_zero(0x80000000, BINARY32) and formats.is_zero(0, BINARY32)
    assert not formats.is_zero(LEAST_SUBNORMAL, BINARY32)
    assert formats.is_subnormal(LEAST_SUBNORMAL, BINARY32)
    assert not formats.is_subnormal(0, BINARY32)  # a zero is not subnormal
    assert formats.is_infinite(0xFF800000, BINARY32)
    assert not formats.is_infinite(SIGNALLING, BINARY32)
    assert formats.is_nan(SIGNALLING, BINARY32) and formats.is_nan(QUIET, BINARY32)
    assert formats.is_signalling_nan(SIGNALLING, BINARY32)
    assert not formats.is_signalling_nan(QUIET, BINARY32)
    assert formats.is_finite(LARGEST, BINARY32)
    assert not formats.is_finite(INFINITY, BINARY32)
    assert formats.sign(MINUS_ONE, BINARY32) and not formats.sign(ONE, BINARY32)


def test_zero_and_infinity_are_built_with_a_sign():
    assert formats.zero(False, BINARY32) == 0x00000000
    assert formats.zero(True, BINARY32) == 0x80000000
    assert formats.infinity(False, BINARY32) == 0x7F800000
    assert formats.infinity(True, BINARY32) == 0xFF800000
    assert formats.infinity(True, BINARY64) == 0xFFF0000000000000


def test_a_single_is_boxed_in_a_64_bit_register():
    assert formats.box(ONE) == 0xFFFFFFFF3F800000
    assert formats.unbox(0xFFFFFFFF3F800000) == ONE
    assert formats.unbox(formats.box(LEAST_SUBNORMAL)) == LEAST_SUBNORMAL
    # a register that holds a double is no single: reading it gives the canonical NaN
    assert formats.unbox(0x3FF0000000000000) == QUIET
    assert formats.unbox(0xFFFFFFFE3F800000) == QUIET
