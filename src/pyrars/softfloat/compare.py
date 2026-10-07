"""Comparisons, minimum and maximum.

The three comparisons are those of the ISA manual (chapter F, "Single-Precision
Floating-Point Compare Instructions"): FEQ signals an invalid operation only
for a signalling NaN, FLT and FLE signal for any NaN.

FMIN and FMAX take the other operand when one of them is a NaN, give the
canonical NaN when both are, and treat a negative zero as smaller than a
positive one.
"""

from pyrars.softfloat.formats import Format, is_nan, is_signalling_nan, is_zero, sign
from pyrars.softfloat.rounding import NV


def _order(bits: int, fmt: Format) -> int:
    """A number that orders the finite values and the infinities as they are
    ordered numerically: the fields of a format are laid out for it, so only
    the sign has to be turned around. Both zeros give 0."""
    magnitude = bits & ~fmt.sign_mask
    return -magnitude if bits & fmt.sign_mask else magnitude


def _invalid(a: int, b: int, fmt: Format) -> int:
    return NV if is_signalling_nan(a, fmt) or is_signalling_nan(b, fmt) else 0


def equal(a: int, b: int, fmt: Format) -> tuple[bool, int]:
    """FEQ: equality; a quiet NaN compares unequal without raising a flag."""
    if is_nan(a, fmt) or is_nan(b, fmt):
        return False, _invalid(a, b, fmt)
    return _order(a, fmt) == _order(b, fmt), 0


def less(a: int, b: int, fmt: Format) -> tuple[bool, int]:
    """FLT: a NaN makes the comparison false and raises an invalid operation."""
    if is_nan(a, fmt) or is_nan(b, fmt):
        return False, NV
    return _order(a, fmt) < _order(b, fmt), 0


def less_equal(a: int, b: int, fmt: Format) -> tuple[bool, int]:
    """FLE, like FLT."""
    if is_nan(a, fmt) or is_nan(b, fmt):
        return False, NV
    return _order(a, fmt) <= _order(b, fmt), 0


def minimum(a: int, b: int, fmt: Format) -> tuple[int, int]:
    """FMIN."""
    return _extreme(a, b, fmt, smaller=True)


def maximum(a: int, b: int, fmt: Format) -> tuple[int, int]:
    """FMAX."""
    return _extreme(a, b, fmt, smaller=False)


def _extreme(a: int, b: int, fmt: Format, smaller: bool) -> tuple[int, int]:
    flags = _invalid(a, b, fmt)
    if is_nan(a, fmt) and is_nan(b, fmt):
        return fmt.canonical_nan, flags
    if is_nan(a, fmt):
        return b, flags
    if is_nan(b, fmt):
        return a, flags
    if is_zero(a, fmt) and is_zero(b, fmt):  # the signs decide, not the values
        negative = a if sign(a, fmt) else b
        positive = b if sign(a, fmt) else a
        return (negative if smaller else positive), flags
    if smaller:
        return (a if _order(a, fmt) < _order(b, fmt) else b), flags
    return (a if _order(a, fmt) > _order(b, fmt) else b), flags
