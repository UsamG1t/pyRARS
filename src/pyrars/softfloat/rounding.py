"""Rounding of an exact value to a format, and the exception flags.

Every operation of this package computes its result exactly, as integers, and
calls `round_value` once. That is the only place where information can be
lost, so the flags of an operation are raised in one place as well.

The rounding modes are numbered as the `rm` field of an instruction (ISA
manual v20260120, chapter F, "Rounding Modes"). The dynamic mode DYN is
resolved from `frm` by the caller, so `round_value` never sees it.

Tininess (the condition of the underflow flag) is detected BEFORE rounding:
IEEE 754-2019 §7.5 lets an implementation choose, and this is the choice of
RARS (verified 2026-09-30: a value below the smallest normal that rounds up to
the smallest normal raises UF together with NX).

Sources: IEEE 754-2019 §4.3 (rounding directions), §7.4 (overflow) and §7.5
(underflow); ISA manual chapter F for the flags of `fflags`.
"""

from pyrars.softfloat.formats import Format, infinity, zero

# Rounding modes, numbered as the rm field of an instruction.
RNE = 0  # to nearest, a tie to the even significand
RTZ = 1  # toward zero
RDN = 2  # down, toward minus infinity
RUP = 3  # up, toward plus infinity
RMM = 4  # to nearest, a tie away from zero
DYN = 7  # the mode of frm; resolved by the caller
MODES = (RNE, RTZ, RDN, RUP, RMM)

# Exception flags, as they sit in fflags (ISA manual, chapter F).
NX = 1 << 0  # inexact
UF = 1 << 1  # underflow
OF = 1 << 2  # overflow
DZ = 1 << 3  # division by zero
NV = 1 << 4  # invalid operation


def round_value(negative: bool, exponent: int, significand: int,
                fmt: Format, mode: int) -> tuple[int, int]:
    """Round (-1)**negative * significand * 2**exponent to `fmt`.

    `significand` is a non-negative integer of any size. Returns the bits of
    the result and the flags raised by the rounding.
    """
    if significand == 0:
        return zero(negative, fmt), 0

    # The exponent of the leading bit of the value, and of the least
    # significant bit the format can keep: a normal number keeps
    # significand_bits + 1 bits, a subnormal one ends at least_exponent.
    top = exponent + significand.bit_length() - 1
    lowest = max(top - fmt.significand_bits, fmt.least_exponent)
    drop = lowest - exponent

    if drop <= 0:  # the value fits, only its position changes
        kept, half, rest = significand << -drop, 0, 0
    else:
        kept = significand >> drop
        half = (significand >> (drop - 1)) & 1
        rest = significand & ((1 << (drop - 1)) - 1)

    inexact = bool(half or rest)
    if inexact and _round_away(mode, negative, kept, half, rest):
        kept += 1
        if kept.bit_length() > fmt.significand_bits + 1:
            kept >>= 1  # the carry reached a new bit; the dropped bit is 0
            lowest += 1

    flags = NX if inexact else 0
    if inexact and top < fmt.min_exponent:  # tiny before rounding
        flags |= UF
    if kept == 0:  # rounded down to nothing
        return zero(negative, fmt), flags

    result = lowest + kept.bit_length() - 1
    if result > fmt.max_exponent:
        return _overflow(mode, negative, fmt), flags | OF | NX
    if result < fmt.min_exponent:  # subnormal: the exponent field stays 0
        return zero(negative, fmt) | kept, flags
    field = result + fmt.bias
    return (zero(negative, fmt) | field << fmt.significand_bits
            | kept & fmt.significand_mask), flags


def _round_away(mode: int, negative: bool, kept: int, half: int, rest: int) -> bool:
    """Whether an inexact value is rounded away from zero."""
    if mode == RNE:
        return bool(half and (rest or kept & 1))
    if mode == RMM:
        return bool(half)
    if mode == RDN:
        return negative
    if mode == RUP:
        return not negative
    return False  # RTZ


def _overflow(mode: int, negative: bool, fmt: Format) -> int:
    """An overflowing result: infinity, or the largest finite number when the
    rounding direction points toward zero (IEEE 754-2019 §7.4)."""
    if mode == RTZ or (mode == RDN and not negative) or (mode == RUP and negative):
        return zero(negative, fmt) | fmt.largest
    return infinity(negative, fmt)
