"""Conversions: between a format and an integer, and between the two formats.

A value that does not fit the integer it is asked for gives the nearest end of
the range and raises the invalid operation flag, which is what the ISA manual
prescribes instead of a trap; nothing else about a conversion differs from an
ordinary rounding.

Sources: RISC-V ISA manual v20260120, chapter F ("Single-Precision Floating-
Point Conversion and Move Instructions": the conversions to an integer, their
saturation and their flags) and chapter D (the conversions between the formats).
"""

from pyrars.softfloat.formats import (Format, decode, infinity, is_infinite, is_nan,
                                      is_signalling_nan, sign)
from pyrars.softfloat.rounding import NV, NX, round_to_integer, round_value


def to_integer(bits: int, fmt: Format, width: int, signed: bool,
               mode: int) -> tuple[int, int]:
    """The number as an integer of `width` bits, as FCVT.W, FCVT.WU, FCVT.L and
    FCVT.LU compute it. Returns the integer itself; placing it in a register of
    another width is the business of the caller.

    A NaN gives the largest value of the range, an infinity the end it points
    at, and a number outside the range the end it is nearest to; each of them
    raises NV. A fractional part that is lost raises NX.
    """
    lowest = -(1 << (width - 1)) if signed else 0
    highest = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
    if is_nan(bits, fmt):
        return highest, NV
    if is_infinite(bits, fmt):
        return (lowest if sign(bits, fmt) else highest), NV
    whole, inexact = round_to_integer(*decode(bits, fmt), mode)
    if whole < lowest:
        return lowest, NV
    if whole > highest:
        return highest, NV
    return whole, NX if inexact else 0


def from_integer(value: int, fmt: Format, mode: int) -> tuple[int, int]:
    """An integer as a number of the format, as FCVT.S.W and its relatives
    compute it; a value with more digits than the significand holds is rounded."""
    return round_value(value < 0, 0, abs(value), fmt, mode)


def to_format(bits: int, source: Format, target: Format, mode: int) -> tuple[int, int]:
    """The number in another format: widening is exact, narrowing is rounded."""
    if is_nan(bits, source):
        return target.canonical_nan, NV if is_signalling_nan(bits, source) else 0
    if is_infinite(bits, source):
        return infinity(sign(bits, source), target), 0
    return round_value(*decode(bits, source), target, mode)
