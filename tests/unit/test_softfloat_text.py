"""Decimal text of a number, and a number from decimal text.

The texts are those RARS prints (verified by running it), except where its own
language writes a digit more than is needed to read the number back (DEV-37);
those two cases are marked below. The values of the literals are derived from
the grammar of the RISC-V assembly manual, "Floating-point literals".
"""

import pytest

from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NX, OF, RDN, RNE, RTZ, RUP, UF
from pyrars.softfloat.text import from_text, to_text


@pytest.mark.parametrize("bits, text", [
    (0x00000000, "0.0"),
    (0x80000000, "-0.0"),
    (0x3F800000, "1.0"),
    (0xBF800000, "-1.0"),
    (0x40000000, "2.0"),
    (0x3DCCCCCD, "0.1"),
    (0x3EAAAAAB, "0.33333334"),
    (0x3A83126F, "0.001"),  # the smallest magnitude still written plainly
    (0x38D1B717, "1.0E-4"),  # one step further the exponent appears
    (0x44960000, "1200.0"),
    (0x4B3C614E, "1.2345678E7"),
    (0x501502F9, "1.0E10"),
    (0x2EDBE6FF, "1.0E-10"),
    (0x00800000, "1.1754944E-38"),  # the smallest normal single
    (0x7F7FFFFF, "3.4028235E38"),  # the largest finite single
    (0x7F800000, "Infinity"),
    (0xFF800000, "-Infinity"),
    (0x7FC00000, "NaN"),
    (0xFFC00001, "NaN"),  # every NaN is written the same way
    (0x00000001, "1.0E-45"),  # DEV-37: RARS writes 1.4E-45
])
def test_the_text_of_a_single(bits, text):
    assert to_text(bits, BINARY32) == text


@pytest.mark.parametrize("bits, text", [
    (0x3FF0000000000000, "1.0"),
    (0x3FB999999999999A, "0.1"),
    (0x3FD5555555555555, "0.3333333333333333"),
    (0x4341C37937E08000, "1.0E16"),
    (0x7FEFFFFFFFFFFFFF, "1.7976931348623157E308"),
    (0x0010000000000000, "2.2250738585072014E-308"),
    (0xFFF0000000000000, "-Infinity"),
    (0x0000000000000001, "5.0E-324"),  # DEV-37: RARS writes 4.9E-324
])
def test_the_text_of_a_double(bits, text):
    assert to_text(bits, BINARY64) == text


@pytest.mark.parametrize("bits", [
    0x00000001, 0x00800000, 0x3DCCCCCD, 0x3EAAAAAB, 0x3F800000, 0x7F7FFFFF,
    0x4B3C614E, 0x38D1B717, 0x80000000, 0xC0200000, 0x007FFFFF, 0x33800000,
])
def test_the_text_of_a_single_reads_back_as_the_same_number(bits):
    assert from_text(to_text(bits, BINARY32), BINARY32)[0] == bits


@pytest.mark.parametrize("bits", [
    0x0000000000000001, 0x0010000000000000, 0x3FB999999999999A, 0x3FD5555555555555,
    0x7FEFFFFFFFFFFFFF, 0xC000000000000000, 0x000FFFFFFFFFFFFF,
])
def test_the_text_of_a_double_reads_back_as_the_same_number(bits):
    assert from_text(to_text(bits, BINARY64), BINARY64)[0] == bits


@pytest.mark.parametrize("text, bits, flags", [
    ("1.0", 0x3F800000, 0),
    ("1.", 0x3F800000, 0),
    (".5", 0x3F000000, 0),
    ("-1.5", 0xBF800000 | 0x400000, 0),
    ("+2.0", 0x40000000, 0),
    ("0.1", 0x3DCCCCCD, NX),
    ("1e10", 0x501502F9, 0),
    ("1E10", 0x501502F9, 0),
    ("1.2345678e7", 0x4B3C614E, 0),
    ("0x1.8p1", 0x40400000, 0),  # a hexadecimal literal: 1.5 * 2 is 3.0
    ("0x1p-149", 0x00000001, 0),
    ("Inf", 0x7F800000, 0),
    ("-Inf", 0xFF800000, 0),
    ("NaN", 0x7FC00000, 0),
    ("1e400", 0x7F800000, OF | NX),  # too large for a single: infinity
    ("-1e400", 0xFF800000, OF | NX),
    ("1e-400", 0x00000000, UF | NX),  # too small: zero
    ("0.0", 0x00000000, 0),
    ("-0.0", 0x80000000, 0),
])
def test_the_value_of_a_literal(text, bits, flags):
    assert from_text(text, BINARY32) == (bits, flags)


def test_a_literal_is_rounded_once():
    """DEV-36: read as a double and narrowed afterwards, this literal gives
    0x3f800002, because the first rounding lands exactly on the midpoint."""
    literal = ("1.00000029802322387695312582718061255302767487140869206996285356581"
               "21109008789062")
    assert from_text(literal, BINARY32) == (0x3F800003, NX)


@pytest.mark.parametrize("mode, expected", [
    (RNE, 0x3DCCCCCD), (RUP, 0x3DCCCCCD), (RTZ, 0x3DCCCCCC), (RDN, 0x3DCCCCCC),
])
def test_a_literal_follows_the_rounding_mode(mode, expected):
    assert from_text("0.1", BINARY32, mode) == (expected, NX)


def test_the_value_of_a_literal_as_a_double():
    assert from_text("0.1", BINARY64) == (0x3FB999999999999A, NX)
    assert from_text("1e16", BINARY64) == (0x4341C37937E08000, 0)
    assert from_text("Inf", BINARY64) == (0x7FF0000000000000, 0)


def test_text_that_is_no_literal():
    for text in ("", "abc", "0x1.8", "1.0.0", "e5"):
        with pytest.raises(ValueError):
            from_text(text, BINARY32)
