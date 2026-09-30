"""Arithmetic: addition, multiplication, division, square root, fused product.

Every operation computes its result exactly, with Python integers, and rounds
it once (`rounding.round_value`). A division and a square root have no exact
integer result, so they are computed to a few more bits than the format keeps
and the rest of the value is gathered into a sticky bit: the lowest bit of the
integer is set when something was cut away, which is all the rounding needs to
know about it.

A NaN operand gives the canonical NaN, and a signalling one raises NV as well
(DEV-32, DEV-33: RARS passes the operand through and raises nothing). When an
operation has to produce a NaN of its own (infinity minus infinity, zero times
infinity, zero divided by zero, the root of a negative number), it raises NV.
Where an operand is a quiet NaN and the product of a fused operation is
invalid, only the NaN rule applies and no flag is raised, which IEEE 754-2019
§7.2 leaves to the implementation.

Sources: IEEE 754-2019 §5.4 (the operations), §6.2 (NaN propagation), §6.3
(the sign of an exact zero result) and §7.2 (invalid operations); RISC-V ISA
manual v20260120, chapters F and D.
"""

from math import isqrt

from pyrars.softfloat.formats import (Format, decode, infinity, is_infinite, is_nan,
                                      is_signalling_nan, is_zero, sign, zero)
from pyrars.softfloat.rounding import DZ, NV, RDN, round_value

# Bits computed beyond the significand of the format before the sticky bit is
# gathered: one for the rounding position, one to see whether it is a tie, and
# one more so that setting the sticky bit can never disturb them.
EXTRA = 3


def negate(bits: int, fmt: Format) -> int:
    """The number with the other sign; a NaN stays the same NaN."""
    return bits ^ fmt.sign_mask


def add(a: int, b: int, fmt: Format, mode: int) -> tuple[int, int]:
    nan = _nan_result(fmt, a, b)
    if nan is not None:
        return nan
    if is_infinite(a, fmt) or is_infinite(b, fmt):
        if is_infinite(a, fmt) and is_infinite(b, fmt) and sign(a, fmt) != sign(b, fmt):
            return fmt.canonical_nan, NV  # infinity minus infinity
        return (a if is_infinite(a, fmt) else b), 0
    return _sum(decode(a, fmt), decode(b, fmt), fmt, mode)


def subtract(a: int, b: int, fmt: Format, mode: int) -> tuple[int, int]:
    return add(a, negate(b, fmt), fmt, mode)


def multiply(a: int, b: int, fmt: Format, mode: int) -> tuple[int, int]:
    nan = _nan_result(fmt, a, b)
    if nan is not None:
        return nan
    if is_infinite(a, fmt) or is_infinite(b, fmt):
        if is_zero(a, fmt) or is_zero(b, fmt):
            return fmt.canonical_nan, NV  # zero times infinity
        return infinity(sign(a, fmt) != sign(b, fmt), fmt), 0
    negative, exponent, significand = _product(a, b, fmt)
    return round_value(negative, exponent, significand, fmt, mode)


def divide(a: int, b: int, fmt: Format, mode: int) -> tuple[int, int]:
    nan = _nan_result(fmt, a, b)
    if nan is not None:
        return nan
    negative = sign(a, fmt) != sign(b, fmt)
    if is_infinite(a, fmt):
        if is_infinite(b, fmt):
            return fmt.canonical_nan, NV
        return infinity(negative, fmt), 0
    if is_infinite(b, fmt):
        return zero(negative, fmt), 0
    if is_zero(b, fmt):
        if is_zero(a, fmt):
            return fmt.canonical_nan, NV
        return infinity(negative, fmt), DZ
    if is_zero(a, fmt):
        return zero(negative, fmt), 0

    _, ea, sa = decode(a, fmt)
    _, eb, sb = decode(b, fmt)
    # The quotient is computed to EXTRA bits below the place where the format is
    # cut: enough bits for a normal result, and low enough (the second term) for
    # a subnormal one, whose bits end at least_exponent. What the division
    # leaves over becomes the sticky bit.
    shift = max(sb.bit_length() - sa.bit_length() + fmt.significand_bits + EXTRA,
                ea - eb - fmt.least_exponent + EXTRA, 0)
    quotient, rest = divmod(sa << shift, sb)
    if rest:
        quotient |= 1
    return round_value(negative, ea - eb - shift, quotient, fmt, mode)


def square_root(a: int, fmt: Format, mode: int) -> tuple[int, int]:
    nan = _nan_result(fmt, a)
    if nan is not None:
        return nan
    if is_zero(a, fmt):
        return a, 0  # the root of a zero keeps its sign, even a negative one
    if sign(a, fmt):
        return fmt.canonical_nan, NV
    if is_infinite(a, fmt):
        return a, 0

    _, exponent, significand = decode(a, fmt)
    # the root of significand * 2**exponent is isqrt(significand << shift) *
    # 2**((exponent - shift) / 2), so the shift must leave that exponent even
    # and the root long enough to be rounded (a root is never subnormal)
    shift = max(2 * (fmt.significand_bits + EXTRA) - significand.bit_length(), 0)
    if (exponent - shift) % 2:
        shift += 1
    scaled = significand << shift
    root = isqrt(scaled)
    if root * root != scaled:
        root |= 1
    return round_value(False, (exponent - shift) // 2, root, fmt, mode)


def fused_multiply_add(a: int, b: int, c: int, fmt: Format, mode: int) -> tuple[int, int]:
    """a * b + c with a single rounding. The three other fused instructions of
    the ISA are this one with `negate` applied to an operand."""
    nan = _nan_result(fmt, a, b, c)
    if nan is not None:
        return nan
    if is_infinite(a, fmt) or is_infinite(b, fmt):
        if is_zero(a, fmt) or is_zero(b, fmt):
            return fmt.canonical_nan, NV  # zero times infinity
        negative = sign(a, fmt) != sign(b, fmt)
        if is_infinite(c, fmt) and sign(c, fmt) != negative:
            return fmt.canonical_nan, NV  # infinity minus infinity
        return infinity(negative, fmt), 0
    if is_infinite(c, fmt):
        return c, 0
    return _sum(_product(a, b, fmt), decode(c, fmt), fmt, mode)


# ------------------------------------------------------------------ the parts


def _nan_result(fmt: Format, *operands: int) -> tuple[int, int] | None:
    """The result of an operation that has a NaN among its operands."""
    if not any(is_nan(operand, fmt) for operand in operands):
        return None
    signalling = any(is_signalling_nan(operand, fmt) for operand in operands)
    return fmt.canonical_nan, NV if signalling else 0


def _product(a: int, b: int, fmt: Format) -> tuple[bool, int, int]:
    """The exact product of two finite numbers, as (sign, exponent, significand)."""
    negative_a, ea, sa = decode(a, fmt)
    negative_b, eb, sb = decode(b, fmt)
    return negative_a != negative_b, ea + eb, sa * sb


def _sum(first: tuple[bool, int, int], second: tuple[bool, int, int],
         fmt: Format, mode: int) -> tuple[int, int]:
    """The exact sum of two finite values, rounded once."""
    (negative_first, e1, s1), (negative_second, e2, s2) = first, second
    common = min(e1, e2)
    s1 <<= e1 - common
    s2 <<= e2 - common
    if negative_first == negative_second:
        return round_value(negative_first, common, s1 + s2, fmt, mode)
    if s1 == s2:  # the two values cancel out exactly (IEEE 754-2019 §6.3)
        return zero(mode == RDN, fmt), 0
    if s1 > s2:
        return round_value(negative_first, common, s1 - s2, fmt, mode)
    return round_value(negative_second, common, s2 - s1, fmt, mode)
