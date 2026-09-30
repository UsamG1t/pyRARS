"""Floating point formats: how a number is laid out in a word.

A format is described by the widths of its two fields, as IEEE 754 does: the
exponent field and the significand field (the leading one of a normal number
is not stored). Everything else follows from those two widths.

A finite number is read as three integers:

    value = (-1)**sign * significand * 2**exponent

Python integers hold the significand of any intermediate result without loss,
so an operation can be computed exactly and rounded once (`rounding.py`).

Sources: IEEE 754-2019 §3.4 (formats) and §6.2 (NaNs); RISC-V ISA manual
v20260120, chapter F ("Single-Precision Load and Store Instructions" for the
NaN boxing, "Single-Precision Floating-Point Classify Instruction" for the
classification bits) and chapter D.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Format:
    """One binary format. The derived widths are computed once, in `make`."""

    name: str
    exponent_bits: int
    significand_bits: int  # stored bits, the leading one of a normal number excluded
    width: int  # bits of the whole number
    bias: int  # exponent field of the value 1.0
    max_exponent: int  # exponent of a finite number written as 1.f * 2**e
    min_exponent: int  # the same for the smallest normal number
    least_exponent: int  # exponent of the least significant bit of a subnormal
    sign_mask: int
    significand_mask: int
    exponent_field_mask: int  # the field of an infinity or a NaN, in place
    infinity: int  # bits of +infinity
    canonical_nan: int  # the only NaN this package produces (DEV-32)
    largest: int  # bits of the largest finite number


def make(name: str, exponent_bits: int, significand_bits: int) -> Format:
    bias = (1 << (exponent_bits - 1)) - 1
    field = ((1 << exponent_bits) - 1) << significand_bits
    quiet = 1 << (significand_bits - 1)
    return Format(
        name=name,
        exponent_bits=exponent_bits,
        significand_bits=significand_bits,
        width=1 + exponent_bits + significand_bits,
        bias=bias,
        max_exponent=bias,
        min_exponent=1 - bias,
        least_exponent=1 - bias - significand_bits,
        sign_mask=1 << (exponent_bits + significand_bits),
        significand_mask=(1 << significand_bits) - 1,
        exponent_field_mask=field,
        infinity=field,
        canonical_nan=field | quiet,
        largest=field - 1,
    )


BINARY32 = make("binary32", 8, 23)
BINARY64 = make("binary64", 11, 52)

# Bits of FCLASS, from the lowest: the classes in the order of the ISA manual.
NEGATIVE_INFINITY = 1 << 0
NEGATIVE_NORMAL = 1 << 1
NEGATIVE_SUBNORMAL = 1 << 2
NEGATIVE_ZERO = 1 << 3
POSITIVE_ZERO = 1 << 4
POSITIVE_SUBNORMAL = 1 << 5
POSITIVE_NORMAL = 1 << 6
POSITIVE_INFINITY = 1 << 7
SIGNALLING_NAN = 1 << 8
QUIET_NAN = 1 << 9


# ------------------------------------------------------- reading a bit pattern


def sign(bits: int, fmt: Format) -> bool:
    return bool(bits & fmt.sign_mask)


def exponent_field(bits: int, fmt: Format) -> int:
    return (bits & fmt.exponent_field_mask) >> fmt.significand_bits


def stored_significand(bits: int, fmt: Format) -> int:
    return bits & fmt.significand_mask


def is_zero(bits: int, fmt: Format) -> bool:
    return not bits & ~fmt.sign_mask


def is_subnormal(bits: int, fmt: Format) -> bool:
    return not bits & fmt.exponent_field_mask and bool(bits & fmt.significand_mask)


def is_infinite(bits: int, fmt: Format) -> bool:
    return bits & ~fmt.sign_mask == fmt.infinity


def is_nan(bits: int, fmt: Format) -> bool:
    return (bits & fmt.exponent_field_mask == fmt.exponent_field_mask
            and bool(bits & fmt.significand_mask))


def is_signalling_nan(bits: int, fmt: Format) -> bool:
    """A NaN whose highest significand bit is clear: it raises NV when used."""
    return is_nan(bits, fmt) and not bits & (1 << (fmt.significand_bits - 1))


def is_finite(bits: int, fmt: Format) -> bool:
    return bits & fmt.exponent_field_mask != fmt.exponent_field_mask


def decode(bits: int, fmt: Format) -> tuple[bool, int, int]:
    """(sign, exponent, significand) of a finite number; a zero has significand 0.

    The number is (-1)**sign * significand * 2**exponent. A subnormal number
    and a normal one differ only in the exponent field, so both are read here
    without a special case for the reader.
    """
    field = exponent_field(bits, fmt)
    stored = stored_significand(bits, fmt)
    if field == 0:
        return sign(bits, fmt), fmt.least_exponent, stored
    return (sign(bits, fmt), field - fmt.bias - fmt.significand_bits,
            stored | (1 << fmt.significand_bits))


def zero(negative: bool, fmt: Format) -> int:
    return fmt.sign_mask if negative else 0


def infinity(negative: bool, fmt: Format) -> int:
    return fmt.infinity | (fmt.sign_mask if negative else 0)


def classify(bits: int, fmt: Format) -> int:
    """The bit FCLASS writes for this number."""
    negative = sign(bits, fmt)
    if is_nan(bits, fmt):
        return SIGNALLING_NAN if is_signalling_nan(bits, fmt) else QUIET_NAN
    if is_infinite(bits, fmt):
        return NEGATIVE_INFINITY if negative else POSITIVE_INFINITY
    if is_zero(bits, fmt):
        return NEGATIVE_ZERO if negative else POSITIVE_ZERO
    if is_subnormal(bits, fmt):
        return NEGATIVE_SUBNORMAL if negative else POSITIVE_SUBNORMAL
    return NEGATIVE_NORMAL if negative else POSITIVE_NORMAL


# --------------------------------------------------------------- NaN boxing

BOX = ((1 << 32) - 1) << 32  # the upper half of a boxed single precision value


def box(single: int) -> int:
    """A binary32 value as it is kept in a 64-bit register (ISA manual D)."""
    return BOX | single


def unbox(register: int) -> int:
    """The binary32 value of a 64-bit register: the canonical NaN unless boxed."""
    return register & 0xFFFFFFFF if register & BOX == BOX else BINARY32.canonical_nan
