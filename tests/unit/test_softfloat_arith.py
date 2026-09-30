"""Addition, multiplication, division, square root and the fused product.

Expected values are derived by hand from IEEE 754-2019 (§5.4 the operations,
§6.2 NaNs, §6.3 the sign of an exact zero, §7.2 the invalid operations) and
from the RISC-V ISA manual chapters F and D. A value written as a bit pattern
is named after the number it holds.
"""

import pytest

from pyrars.softfloat.arith import (add, divide, fused_multiply_add, multiply, negate,
                                    square_root, subtract)
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import DZ, NV, NX, OF, RDN, RMM, RNE, RTZ, RUP, UF

PLUS_ZERO = 0x00000000
MINUS_ZERO = 0x80000000
LEAST = 0x00000001  # the least subnormal, 2**-149
TWO_TO_MINUS_148 = 0x00000002
SMALLEST_NORMAL = 0x00800000  # 2**-126
HALF = 0x3F000000
ONE = 0x3F800000
ONE_AND_ULP = 0x3F800001  # 1 + 2**-23
TWO = 0x40000000
THREE = 0x40400000
FOUR = 0x40800000
FIVE = 0x40A00000
SIX = 0x40C00000
SEVEN = 0x40E00000
MINUS_ONE = 0xBF800000
MINUS_TWO = 0xC0000000
TWO_TO_103 = 0x73000000
LARGEST = 0x7F7FFFFF
PLUS_INFINITY = 0x7F800000
MINUS_INFINITY = 0xFF800000
CANONICAL = 0x7FC00000
QUIET_WITH_PAYLOAD = 0x7FC00001
SIGNALLING = 0x7F800001

# binary64
D_ONE = 0x3FF0000000000000
D_TWO = 0x4000000000000000
D_THREE = 0x4008000000000000
D_ONE_AND_ULP = 0x3FF0000000000001  # 1 + 2**-52


# ------------------------------------------------------------------- addition


@pytest.mark.parametrize("a, b, expected, flags", [
    (ONE, TWO, THREE, 0),
    (TWO, MINUS_ONE, ONE, 0),
    (LEAST, LEAST, TWO_TO_MINUS_148, 0),  # subnormal, exact
    (ONE, 0x33800000, ONE, NX),  # 1 + 2**-24: a tie, down to the even significand
    (LARGEST, TWO_TO_103, PLUS_INFINITY, OF | NX),  # the rounding overflows (DEV-38)
    (PLUS_INFINITY, MINUS_ONE, PLUS_INFINITY, 0),
    (MINUS_INFINITY, PLUS_INFINITY, CANONICAL, NV),
    (PLUS_INFINITY, PLUS_INFINITY, PLUS_INFINITY, 0),
])
def test_addition(a, b, expected, flags):
    assert add(a, b, BINARY32, RNE) == (expected, flags)
    assert add(b, a, BINARY32, RNE) == (expected, flags)


@pytest.mark.parametrize("mode, cancelled", [
    (RNE, PLUS_ZERO), (RTZ, PLUS_ZERO), (RUP, PLUS_ZERO), (RMM, PLUS_ZERO),
    (RDN, MINUS_ZERO),  # only rounding down makes an exact cancellation negative
])
def test_the_sign_of_an_exact_zero(mode, cancelled):
    assert add(ONE, MINUS_ONE, BINARY32, mode) == (cancelled, 0)
    assert subtract(ONE, ONE, BINARY32, mode) == (cancelled, 0)
    assert add(PLUS_ZERO, MINUS_ZERO, BINARY32, mode) == (cancelled, 0)
    # two zeros of the same sign keep it, whatever the mode
    assert add(MINUS_ZERO, MINUS_ZERO, BINARY32, mode) == (MINUS_ZERO, 0)
    assert add(PLUS_ZERO, PLUS_ZERO, BINARY32, mode) == (PLUS_ZERO, 0)


def test_subtraction_is_addition_of_the_other_sign():
    assert subtract(ONE, TWO, BINARY32, RNE) == (MINUS_ONE, 0)
    assert subtract(TWO, ONE, BINARY32, RNE) == (ONE, 0)
    assert subtract(PLUS_INFINITY, PLUS_INFINITY, BINARY32, RNE) == (CANONICAL, NV)
    assert subtract(PLUS_INFINITY, MINUS_INFINITY, BINARY32, RNE) == (PLUS_INFINITY, 0)
    assert subtract(ONE, MINUS_ZERO, BINARY32, RNE) == (ONE, 0)


# ------------------------------------------------------------- multiplication


@pytest.mark.parametrize("a, b, expected, flags", [
    (TWO, THREE, SIX, 0),
    (TWO, HALF, ONE, 0),
    (MINUS_ONE, TWO, MINUS_TWO, 0),
    (MINUS_ONE, MINUS_ONE, ONE, 0),
    (MINUS_ZERO, TWO, MINUS_ZERO, 0),
    (MINUS_ZERO, MINUS_TWO, PLUS_ZERO, 0),
    # (1 + 2**-23)**2 is 1 + 2**-22 + 2**-46, rounded to 1 + 2**-22
    (ONE_AND_ULP, ONE_AND_ULP, 0x3F800002, NX),
    (LARGEST, LARGEST, PLUS_INFINITY, OF | NX),
    (LEAST, HALF, PLUS_ZERO, UF | NX),  # 2**-150: a tie, down to zero
    (LEAST, TWO, TWO_TO_MINUS_148, 0),  # tiny but exact
    (PLUS_INFINITY, MINUS_TWO, MINUS_INFINITY, 0),
    (PLUS_INFINITY, PLUS_ZERO, CANONICAL, NV),
    (MINUS_INFINITY, MINUS_ZERO, CANONICAL, NV),
])
def test_multiplication(a, b, expected, flags):
    assert multiply(a, b, BINARY32, RNE) == (expected, flags)
    assert multiply(b, a, BINARY32, RNE) == (expected, flags)


# -------------------------------------------------------------------- division


@pytest.mark.parametrize("mode, expected", [
    (RNE, 0x3EAAAAAB), (RMM, 0x3EAAAAAB), (RUP, 0x3EAAAAAB),
    (RTZ, 0x3EAAAAAA), (RDN, 0x3EAAAAAA),
])
def test_a_division_that_never_ends(mode, expected):
    """One third: the exact value lies above the midpoint, so only the
    directions toward zero give the lower number."""
    assert divide(ONE, THREE, BINARY32, mode) == (expected, NX)


@pytest.mark.parametrize("a, b, expected, flags", [
    (SIX, THREE, TWO, 0),
    (ONE, TWO, HALF, 0),
    (MINUS_ONE, TWO, 0xBF000000, 0),
    (SMALLEST_NORMAL, FOUR, 0x00200000, 0),  # 2**-128 is an exact subnormal
    (LEAST, TWO, PLUS_ZERO, UF | NX),  # 2**-150: a tie, down to zero
    (ONE, PLUS_INFINITY, PLUS_ZERO, 0),
    (MINUS_ONE, PLUS_INFINITY, MINUS_ZERO, 0),
    (PLUS_INFINITY, TWO, PLUS_INFINITY, 0),
    (PLUS_INFINITY, MINUS_INFINITY, CANONICAL, NV),
    (PLUS_ZERO, PLUS_ZERO, CANONICAL, NV),
    (MINUS_ZERO, PLUS_ZERO, CANONICAL, NV),
    (PLUS_ZERO, TWO, PLUS_ZERO, 0),
    (ONE, PLUS_ZERO, PLUS_INFINITY, DZ),
    (MINUS_ONE, PLUS_ZERO, MINUS_INFINITY, DZ),
    (ONE, MINUS_ZERO, MINUS_INFINITY, DZ),
    (MINUS_ONE, MINUS_ZERO, PLUS_INFINITY, DZ),
])
def test_division(a, b, expected, flags):
    assert divide(a, b, BINARY32, RNE) == (expected, flags)


# ----------------------------------------------------------------- square root


@pytest.mark.parametrize("a, expected, flags", [
    (FOUR, TWO, 0),
    (ONE, ONE, 0),
    (0x41100000, THREE, 0),  # the root of nine
    (TWO, 0x3FB504F3, NX),  # the root of two, rounded to nearest
    (TWO_TO_MINUS_148, 0x1A800000, 0),  # the root of 2**-148 is 2**-74, exact
    (PLUS_ZERO, PLUS_ZERO, 0),
    (MINUS_ZERO, MINUS_ZERO, 0),  # the root of a negative zero keeps its sign
    (PLUS_INFINITY, PLUS_INFINITY, 0),
    (MINUS_ONE, CANONICAL, NV),
    (MINUS_INFINITY, CANONICAL, NV),
])
def test_square_root(a, expected, flags):
    assert square_root(a, BINARY32, RNE) == (expected, flags)


def test_the_root_of_a_double():
    assert square_root(D_TWO, BINARY64, RNE) == (0x3FF6A09E667F3BCD, NX)
    assert square_root(0x4010000000000000, BINARY64, RNE) == (D_TWO, 0)  # 4.0 -> 2.0


# ---------------------------------------------------------------- fused product


def test_a_fused_product_rounds_once():
    """(1 + 2**-23)**2 - (1 + 2**-22) is 2**-46 exactly. Rounding the product
    first would give zero, because the product alone rounds to 1 + 2**-22."""
    assert fused_multiply_add(ONE_AND_ULP, ONE_AND_ULP, 0xBF800002,
                              BINARY32, RNE) == (0x28800000, 0)
    assert multiply(ONE_AND_ULP, ONE_AND_ULP, BINARY32, RNE) == (0x3F800002, NX)
    # the same in double precision: the residue is 2**-104
    assert fused_multiply_add(D_ONE_AND_ULP, D_ONE_AND_ULP, 0xBFF0000000000002,
                              BINARY64, RNE) == (0x3970000000000000, 0)


@pytest.mark.parametrize("a, b, c, expected, flags", [
    (TWO, THREE, ONE, SEVEN, 0),
    (TWO, THREE, MINUS_ONE, FIVE, 0),
    (ONE, ONE, MINUS_ONE, PLUS_ZERO, 0),
    (ONE, MINUS_ONE, ONE, PLUS_ZERO, 0),
    (PLUS_ZERO, PLUS_INFINITY, ONE, CANONICAL, NV),  # the product is invalid
    (PLUS_INFINITY, ONE, MINUS_INFINITY, CANONICAL, NV),  # infinity minus infinity
    (PLUS_INFINITY, ONE, PLUS_INFINITY, PLUS_INFINITY, 0),
    (ONE, ONE, PLUS_INFINITY, PLUS_INFINITY, 0),
    (LARGEST, TWO, MINUS_INFINITY, MINUS_INFINITY, 0),
    (LARGEST, TWO, ONE, PLUS_INFINITY, OF | NX),
])
def test_the_fused_product(a, b, c, expected, flags):
    assert fused_multiply_add(a, b, c, BINARY32, RNE) == (expected, flags)


def test_the_three_other_fused_instructions_are_this_one_negated():
    """fmsub, fnmsub and fnmadd of the ISA differ only in the signs."""
    product, addend = (TWO, THREE), ONE
    assert fused_multiply_add(*product, addend, BINARY32, RNE) == (SEVEN, 0)  # fmadd
    assert fused_multiply_add(*product, negate(addend, BINARY32),
                              BINARY32, RNE) == (FIVE, 0)  # fmsub
    assert fused_multiply_add(negate(TWO, BINARY32), THREE, addend,
                              BINARY32, RNE) == (FIVE | 0x80000000, 0)  # fnmsub: -5.0
    assert fused_multiply_add(negate(TWO, BINARY32), THREE, negate(addend, BINARY32),
                              BINARY32, RNE) == (SEVEN | 0x80000000, 0)  # fnmadd: -7.0


def test_negate_turns_the_sign_of_a_number():
    assert negate(ONE, BINARY32) == MINUS_ONE
    assert negate(MINUS_ONE, BINARY32) == ONE
    assert negate(PLUS_ZERO, BINARY32) == MINUS_ZERO
    assert negate(PLUS_INFINITY, BINARY32) == MINUS_INFINITY
    assert negate(D_ONE, BINARY64) == 0xBFF0000000000000


# ----------------------------------------------------------------------- NaNs


@pytest.mark.parametrize("operation", [add, subtract, multiply, divide])
def test_a_nan_operand_gives_the_canonical_nan(operation):
    """DEV-32 and DEV-33: RARS hands the operand back and raises nothing."""
    assert operation(QUIET_WITH_PAYLOAD, ONE, BINARY32, RNE) == (CANONICAL, 0)
    assert operation(ONE, QUIET_WITH_PAYLOAD, BINARY32, RNE) == (CANONICAL, 0)
    assert operation(SIGNALLING, ONE, BINARY32, RNE) == (CANONICAL, NV)
    assert operation(ONE, SIGNALLING, BINARY32, RNE) == (CANONICAL, NV)
    assert operation(QUIET_WITH_PAYLOAD, SIGNALLING, BINARY32, RNE) == (CANONICAL, NV)


def test_a_nan_operand_of_the_other_operations():
    assert square_root(QUIET_WITH_PAYLOAD, BINARY32, RNE) == (CANONICAL, 0)
    assert square_root(SIGNALLING, BINARY32, RNE) == (CANONICAL, NV)
    for place in range(3):
        operands = [ONE, ONE, ONE]
        operands[place] = QUIET_WITH_PAYLOAD
        assert fused_multiply_add(*operands, BINARY32, RNE) == (CANONICAL, 0)
        operands[place] = SIGNALLING
        assert fused_multiply_add(*operands, BINARY32, RNE) == (CANONICAL, NV)


def test_a_quiet_nan_leaves_an_invalid_product_unflagged():
    """IEEE 754-2019 §7.2 leaves this case to the implementation: the NaN rule
    is applied first, so zero times infinity plus a quiet NaN raises nothing."""
    assert fused_multiply_add(PLUS_ZERO, PLUS_INFINITY, QUIET_WITH_PAYLOAD,
                              BINARY32, RNE) == (CANONICAL, 0)
    assert fused_multiply_add(PLUS_ZERO, PLUS_INFINITY, SIGNALLING,
                              BINARY32, RNE) == (CANONICAL, NV)


def test_a_double_nan_is_canonical_too():
    assert add(0x7FF8000000000001, D_ONE, BINARY64, RNE) == (
        BINARY64.canonical_nan, 0)
    assert add(0x7FF0000000000001, D_ONE, BINARY64, RNE) == (
        BINARY64.canonical_nan, NV)
