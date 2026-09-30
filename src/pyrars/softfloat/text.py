"""Decimal text of a number, and a number from decimal text.

Both directions are exact. Text is read as a fraction and rounded once, so a
literal never suffers the two roundings of a conversion through another format
(DEV-36). A number is written with the FEWEST digits that read back as the same
number, in the shape RARS shows: a plain number while the value lies between
1e-3 and 1e7, one digit before the point and an exponent otherwise, a digit on
both sides of the point in either case, and the words `Infinity` and `NaN`
(DEV-37: RARS takes that shape from its own language, whose rule sometimes
writes a digit more than is needed to read the number back).

The grammar of a literal is the one of the assembler (RISC-V assembly manual,
"Floating-point literals", plus the RARS words `Inf` and `NaN`): a decimal
number with a point, an exponent or both, or a hexadecimal number with a binary
exponent.
"""

import re
from fractions import Fraction

from pyrars.softfloat.formats import (Format, decode, infinity, is_infinite, is_nan,
                                      is_zero, sign)
from pyrars.softfloat.rounding import RNE, round_quotient

# A floating point literal without its sign. The lexer of the assembler uses the
# same expression, so the grammar and the conversion stay together.
LITERAL = re.compile(r"""(?:
      (?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?                     # 1.5  1.  .5  1.5e-3
    | [0-9]+[eE][+-]?[0-9]+                                               # 1e3
    | 0[xX](?:[0-9a-fA-F]+\.?|[0-9a-fA-F]*\.[0-9a-fA-F]+)[pP][+-]?[0-9]+  # 0x1.8p1
)""", re.X)

# The words RARS accepts for the two values that have no digits.
WORDS = ("Inf", "NaN")


def from_text(text: str, fmt: Format, mode: int = RNE) -> tuple[int, int]:
    """The value of a floating point literal, rounded once. Raises ValueError
    if the text is not a literal the assembler accepts."""
    body = text.strip()
    negative = body.startswith("-")
    if body[:1] in ("+", "-"):
        body = body[1:].strip()
    if body == "Inf":
        return infinity(negative, fmt), 0
    if body == "NaN":
        return fmt.canonical_nan, 0
    if not LITERAL.fullmatch(body):
        raise ValueError(f'"{text}" is no floating point literal')
    value = _fraction(body)
    return round_quotient(negative, value.numerator, value.denominator, 0, fmt, mode)


def to_text(bits: int, fmt: Format) -> str:
    """The shortest decimal text that reads back as this number."""
    if is_nan(bits, fmt):
        return "NaN"
    negative = sign(bits, fmt)
    written = "-" if negative else ""
    if is_infinite(bits, fmt):
        return written + "Infinity"
    if is_zero(bits, fmt):
        return written + "0.0"
    digits, exponent = _shortest(bits, fmt)
    return written + _written(digits, exponent)


# ------------------------------------------------------------------ the parts


def _fraction(text: str) -> Fraction:
    """The exact value of a literal without its sign."""
    if text[:2].lower() == "0x":
        mantissa, _, exponent = text[2:].lower().partition("p")
        whole, _, fraction = mantissa.partition(".")
        digits = int(whole + fraction, 16)
        return Fraction(digits, 16 ** len(fraction)) * Fraction(2) ** int(exponent or 0)
    mantissa, _, exponent = text.lower().partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = int(whole + fraction or "0")
    return Fraction(digits, 10 ** len(fraction)) * Fraction(10) ** int(exponent or 0)


def _shortest(bits: int, fmt: Format) -> tuple[int, int]:
    """The fewest significant digits that read back as this number, and the
    exponent of the first of them. The value itself is positive here."""
    magnitude = bits & ~fmt.sign_mask
    _, exponent, significand = decode(magnitude, fmt)
    value = Fraction(significand) * Fraction(2) ** exponent
    # This many digits always read back: one more than the decimal digits of the
    # largest significand of the format (9 for binary32, 17 for binary64).
    limit = len(str(1 << (fmt.significand_bits + 1))) + 1
    for count in range(1, limit + 1):
        digits, power = _rounded(value, count)
        if from_text(_written(digits, power), fmt)[0] == magnitude:
            return digits, power
    raise AssertionError(f"{limit} digits do not read back as 0x{bits:x}")


def _rounded(value: Fraction, count: int) -> tuple[int, int]:
    """`count` significant digits of a positive value, and the exponent of the
    first digit. The digits are those of the nearest decimal of that length."""
    exponent = _decimal_exponent(value)
    digits = _nearest(value * Fraction(10) ** (count - 1 - exponent))
    if digits >= 10 ** count:  # 9.99 rounded to two digits is 10, a digit longer
        digits //= 10
        exponent += 1
    return digits, exponent


def _decimal_exponent(value: Fraction) -> int:
    """The exponent of the first decimal digit of a positive value: the number e
    with 10**e <= value < 10**(e+1). Counting the digits of the two parts of the
    fraction gets within one of it, and the loops settle the rest."""
    exponent = len(str(value.numerator)) - len(str(value.denominator))
    while Fraction(10) ** exponent > value:
        exponent -= 1
    while Fraction(10) ** (exponent + 1) <= value:
        exponent += 1
    return exponent


def _nearest(value: Fraction) -> int:
    """The whole number nearest to a positive value, a tie to the even one."""
    whole, rest = divmod(value.numerator, value.denominator)
    if 2 * rest > value.denominator or (2 * rest == value.denominator and whole % 2):
        whole += 1
    return whole


def _written(digits: int, exponent: int) -> str:
    """The digits with a decimal point, in the shape of RARS."""
    text = str(digits)
    if not -3 <= exponent < 7:
        return f"{text[0]}.{text[1:] or '0'}E{exponent}"
    if exponent < 0:
        return "0." + "0" * (-exponent - 1) + text
    if exponent >= len(text) - 1:  # a whole number: 12 with exponent 3 is 1200.0
        return text + "0" * (exponent - len(text) + 1) + ".0"
    return text[:exponent + 1] + "." + text[exponent + 1:]
