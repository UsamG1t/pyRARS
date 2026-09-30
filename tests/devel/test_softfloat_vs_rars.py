"""T-FP: floating point against RARS - classification, comparisons, rounding
(stage 12) and the arithmetic (stage 13).

The oracle runs a program that prints, for every case, the result and the
exception flags it raised; our side calls `pyrars.softfloat` with the same bit
patterns. Rounding is reached through `fcvt.s.d` as well: narrowing a double to
a single is exactly "round this exact value to binary32", so the whole table of
`round_value` can be compared without any arithmetic instruction.

What differs on purpose, each stated on both sides here:
 - DEV-38: RARS decides the overflow flag from the exponent of the exact
   result, so an overflow made by the rounding keeps the inexact flag alone.
 - DEV-39: its FLT and FLE answer by the sign of the first operand when that
   operand is an infinity and the second one is not a zero.
 - DEV-32, DEV-33: the first NaN among the operands is handed back as it is,
   payload and signalling bit and all, and no flag is raised.
 - DEV-40: a fused instruction with a finite product and an infinite addend
   kills RARS, so that case has a test of its own.
Classification, FEQ, FMIN and FMAX agree everywhere.
"""

from fractions import Fraction

import pytest

from pyrars.softfloat import formats
from pyrars.softfloat.arith import (add, divide, fused_multiply_add, multiply, negate,
                                    square_root, subtract)
from pyrars.softfloat.compare import equal, less, less_equal, maximum, minimum
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NV, NX, OF, RDN, RMM, RNE, RTZ, RUP, round_value

pytestmark = pytest.mark.devel

MODES = {"rne": RNE, "rtz": RTZ, "rdn": RDN, "rup": RUP, "rmm": RMM}

# A macro prints one value in hexadecimal, then fflags, then clears fflags.
PREAMBLE = """\
.macro showf %r
        fmv.x.w a0, %r
        jal print
.end_macro
.macro showi %r
        mv a0, %r
        jal print
.end_macro
"""

EPILOGUE = """\
        li a7, 93
        li a0, 0
        ecall
print:  mv s11, ra
        li a7, 34
        ecall
        li a0, 32
        li a7, 11
        ecall
        csrrs a0, fflags, x0
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
        csrrw x0, fflags, x0
        jalr x0, 0(s11)
"""

SINGLES = (
    0x3F800000,  # 1.0
    0x40000000,  # 2.0
    0xBF800000,  # -1.0
    0x00000000,  # +0.0
    0x80000000,  # -0.0
    0x7F800000,  # +infinity
    0xFF800000,  # -infinity
    0x00000001,  # the least subnormal
    0x7FC00000,  # a quiet NaN
    0x7F800001,  # a signalling NaN
)

CLASSES32 = SINGLES + (0xFFFFFFFF, 0x807FFFFF, 0x7F7FFFFF, 0x80000001)
CLASSES64 = (
    0x3FF0000000000000, 0xBFF0000000000000, 0x0000000000000000, 0x8000000000000000,
    0x7FF0000000000000, 0xFFF0000000000000, 0x0000000000000001, 0x8000000000000001,
    0x7FF8000000000000, 0x7FF0000000000001, 0x7FEFFFFFFFFFFFFF,
)


def double_bits(negative: bool, exponent: int, significand: int) -> int:
    """Bits of a normal double holding significand * 2**exponent exactly.

    Written from the IEEE 754 layout, not from pyrars.softfloat.
    """
    width = significand.bit_length()
    top = exponent + width - 1
    assert -1022 <= top <= 1023 and width <= 53, "not a normal double"
    stored = (significand << (52 - (width - 1))) & ((1 << 52) - 1)
    return (int(negative) << 63) | ((top + 1023) << 52) | stored


# Doubles whose narrowing to a single exercises every rule of round_value.
NARROWING = (
    double_bits(False, -23, 0x800000),        # 1.0, exact
    double_bits(False, -24, 2**24 + 1),       # a tie, down to the even significand
    double_bits(False, -24, 2**24 + 3),       # a tie, up to the even significand
    double_bits(False, -25, 2**25 + 1),       # below half a step
    double_bits(False, -24, 2**25 - 1),       # rounding carries into the exponent
    double_bits(False, -150, 2**24 - 1),      # tiny, grows into the smallest normal
    double_bits(False, -150, 3),              # tiny, becomes a subnormal
    double_bits(False, -150, 1),              # tiny, half a step above zero
    double_bits(False, -149, 1),              # the least subnormal, exact
    double_bits(False, 104, 0xFFFFFF),        # the largest single, exact
    double_bits(False, 103, 2**25 - 1),       # rounds up into the overflow
    double_bits(False, 128, 1),               # beyond the largest single
    double_bits(True, -24, 2**24 + 1),        # the same ties with a sign
    double_bits(True, -150, 1),
    double_bits(True, 103, 2**25 - 1),
    double_bits(True, 128, 1),
)


def data_block(name: str, values, directive: str) -> str:
    return f"{name}: {directive} " + ", ".join(f"0x{v:x}" for v in values) + "\n"


def results(rars, tmp_path, source: str) -> list[tuple[int, int]]:
    """Run the program and read its lines of "<value> <flags>"."""
    path = tmp_path / "p.s"
    path.write_text(source)
    done = rars.run([path])
    assert done.messages == [] and done.exit_code == 0, done.stdout
    rows = []
    for line in done.stdout.splitlines():
        value, flags = line.split()
        rows.append((int(value, 16), int(flags, 16)))
    return rows


def test_classification_of_singles(rars, tmp_path):
    body = "".join(f"        flw ft0, {4 * i}(s0)\n        fclass.s t0, ft0\n        showi t0\n"
                   for i in range(len(CLASSES32)))
    source = (PREAMBLE + ".data\n" + data_block("v", CLASSES32, ".word")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    assert rows == [(formats.classify(bits, BINARY32), 0) for bits in CLASSES32]


def test_classification_of_doubles(rars, tmp_path):
    body = "".join(f"        fld ft0, {8 * i}(s0)\n        fclass.d t0, ft0\n        showi t0\n"
                   for i in range(len(CLASSES64)))
    source = (PREAMBLE + ".data\n" + data_block("v", CLASSES64, ".dword")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    assert rows == [(formats.classify(bits, BINARY64), 0) for bits in CLASSES64]


def test_comparisons_and_extremes(rars, tmp_path):
    pairs = [(a, b) for a in SINGLES for b in SINGLES]
    body = ""
    for a, b in pairs:
        body += (f"        flw ft0, {4 * SINGLES.index(a)}(s0)\n"
                 f"        flw ft1, {4 * SINGLES.index(b)}(s0)\n"
                 "        feq.s t0, ft0, ft1\n        showi t0\n"
                 "        flt.s t0, ft0, ft1\n        showi t0\n"
                 "        fle.s t0, ft0, ft1\n        showi t0\n"
                 "        fmin.s ft2, ft0, ft1\n        showf ft2\n"
                 "        fmax.s ft2, ft0, ft1\n        showf ft2\n")
    source = (PREAMBLE + ".data\n" + data_block("v", SINGLES, ".word")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    assert len(rows) == 5 * len(pairs)

    turned_around = 0
    for index, (a, b) in enumerate(pairs):
        theirs = rows[5 * index:5 * index + 5]
        where = f"{a:08x} {b:08x}"
        assert theirs[0] == _as_row(equal(a, b, BINARY32)), where
        for row, ours in zip(theirs[1:3], (less(a, b, BINARY32), less_equal(a, b, BINARY32))):
            expected = _their_order(a, b, ours)
            assert row == _as_row(expected), where
            turned_around += expected != ours
        assert theirs[3] == minimum(a, b, BINARY32), where
        assert theirs[4] == maximum(a, b, BINARY32), where
    assert turned_around == 20, "the matrix must reach the infinities of DEV-39"


def _as_row(result: tuple[bool, int]) -> tuple[int, int]:
    value, flags = result
    return int(value), flags


def _their_order(a: int, b: int, ours: tuple[bool, int]) -> tuple[bool, int]:
    """What RARS answers for FLT and FLE: the sign of the first operand decides
    when that operand is an infinity, the operands differ and the second one is
    not a zero (DEV-39); a NaN operand, which raises a flag, is answered right."""
    if (not ours[1] and formats.is_infinite(a, BINARY32) and a != b
            and not formats.is_zero(b, BINARY32)):
        return not formats.sign(a, BINARY32), ours[1]
    return ours


def beyond_the_binades_of_a_single(bits: int) -> bool:
    """Whether the exponent of a double reaches 2**128, which is where RARS
    decides that a narrowing overflows (DEV-38)."""
    _, exponent, significand = formats.decode(bits, BINARY64)
    return exponent + significand.bit_length() - 1 > BINARY32.max_exponent


@pytest.mark.parametrize("mode", MODES)
def test_rounding_to_a_single(rars, tmp_path, mode):
    body = "".join(f"        fld ft0, {8 * i}(s0)\n"
                   f"        fcvt.s.d ft1, ft0, {mode}\n        showf ft1\n"
                   for i in range(len(NARROWING)))
    source = (PREAMBLE + ".data\n" + data_block("v", NARROWING, ".dword")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    ours = [round_value(*formats.decode(bits, BINARY64), BINARY32, MODES[mode])
            for bits in NARROWING]
    # the results are equal; RARS drops OF where the rounding made the overflow
    theirs = [(value, flags if beyond_the_binades_of_a_single(bits) else flags & ~OF)
              for bits, (value, flags) in zip(NARROWING, ours)]
    assert rows == theirs


def test_rars_misses_the_overflow_a_rounding_creates(rars, tmp_path):  # DEV-38
    """2**128 - 2**103 is a finite single times two rounded to infinity."""
    source = (PREAMBLE + ".data\nv: .dword 0x47effffff0000000\n"
              "w: .word 0x7f7fffff, 0x73000000\n"
              ".text\nmain:   la s0, v\n"
              "        fld ft0, 0(s0)\n        fcvt.s.d ft1, ft0, rne\n        showf ft1\n"
              "        la s0, w\n        flw ft2, 0(s0)\n        flw ft3, 4(s0)\n"
              "        fadd.s ft1, ft2, ft3, rne\n        showf ft1\n" + EPILOGUE)
    # RARS: infinity with the inexact flag alone, from a conversion and from an addition
    assert results(rars, tmp_path, source) == [(0x7F800000, NX), (0x7F800000, NX)]
    # ours: the overflow flag as well (IEEE 754-2019 §7.4)
    assert round_value(False, 103, 2**25 - 1, BINARY32, RNE) == (0x7F800000, OF | NX)


# ----------------------------------------------- stage 13: the arithmetic

# Operands of the matrices: ordinary numbers, both zeros, both infinities, the
# ends of the range, values that make a rounding overflow, and two NaNs.
OPERANDS = (
    0x3F800000,  # 1.0
    0x40000000,  # 2.0
    0xBF800000,  # -1.0
    0x00000000,  # +0.0
    0x80000000,  # -0.0
    0x7F800000,  # +infinity
    0xFF800000,  # -infinity
    0x00000001,  # the least subnormal
    0x00800000,  # the smallest normal
    0x7F7FFFFF,  # the largest finite number
    0x3F800001,  # 1 + 2**-23
    0x33800000,  # 2**-24
    0x73000000,  # 2**103
    0xF3000000,  # -2**103, so that a subtraction can overflow as well
    0x5AF80000,  # 31 * 2**50, and the next value is 1082401 * 2**53:
    0x64042108,  # their product is 2**128 - 2**103, which rounds to infinity
    0x7FC00001,  # a quiet NaN carrying a payload
    0x7F800001,  # a signalling NaN
)

BINARY = {"fadd.s": add, "fsub.s": subtract, "fmul.s": multiply, "fdiv.s": divide}

FUSED = (
    (0x3F800001, 0x3F800001, 0xBF800002),  # the residue 2**-46: one rounding
    (0x40000000, 0x40400000, 0x3F800000),  # 2 * 3 + 1
    (0x3F800000, 0x3F800000, 0xBF800000),  # an exact cancellation
    (0x00000001, 0x3F000000, 0x00000000),  # tiny: underflow
    (0x00000000, 0x7F800000, 0x3F800000),  # zero times infinity
    (0x7F800000, 0x3F800000, 0xFF800000),  # infinity minus infinity
    (0x7F800000, 0x3F800000, 0x3F800000),  # an infinite product
    (0x00000000, 0x3F800000, 0x7F800000),  # a zero product and an infinite addend
    (0x7F7FFFFF, 0x40000000, 0x3F800000),  # the product overflows
    (0x5AF80000, 0x64042108, 0x00000000),  # the rounding overflows
    (0x5AF80000, 0x64042108, 0xF3000000),  # ... and the addend takes it back into range
    (0x7FC00001, 0x3F800000, 0x40000000),  # a quiet NaN as the first operand
    (0x3F800000, 0x7F800001, 0x40000000),  # a signalling NaN as the second
    (0x3F800000, 0x3F800000, 0x7FC00001),  # a NaN as the addend
)


def value_of(bits: int) -> Fraction:
    """The exact value of a finite single, as a fraction."""
    negative, exponent, significand = formats.decode(bits, BINARY32)
    magnitude = Fraction(significand) * Fraction(2) ** exponent
    return -magnitude if negative else magnitude


def first_nan(*operands: int) -> int | None:
    for operand in operands:
        if formats.is_nan(operand, BINARY32):
            return operand
    return None


def their_flags(ours: tuple[int, int], exact: Fraction | None) -> tuple[int, int]:
    """RARS raises OF only when the exact result itself leaves the binades of
    the format, so an overflow made by the rounding keeps NX alone (DEV-38)."""
    value, flags = ours
    if flags & OF and exact is not None and abs(exact) < Fraction(2) ** 128:
        flags &= ~OF
    return value, flags


def exact_binary(mnemonic: str, a: int, b: int) -> Fraction | None:
    """The exact result of an operation on two finite operands."""
    if not (formats.is_finite(a, BINARY32) and formats.is_finite(b, BINARY32)):
        return None
    left, right = value_of(a), value_of(b)
    if mnemonic == "fadd.s":
        return left + right
    if mnemonic == "fsub.s":
        return left - right
    if mnemonic == "fmul.s":
        return left * right
    return None if right == 0 else left / right


def binary_source(mnemonic: str, mode: str, pairs) -> str:
    body = "".join(f"        flw ft0, {4 * OPERANDS.index(a)}(s0)\n"
                   f"        flw ft1, {4 * OPERANDS.index(b)}(s0)\n"
                   f"        {mnemonic} ft2, ft0, ft1, {mode}\n        showf ft2\n"
                   for a, b in pairs)
    return (PREAMBLE + ".data\n" + data_block("v", OPERANDS, ".word")
            + ".text\nmain:   la s0, v\n" + body + EPILOGUE)


@pytest.mark.parametrize("mnemonic", BINARY)
def test_an_operation_over_every_pair_of_operands(rars, tmp_path, mnemonic):
    pairs = [(a, b) for a in OPERANDS for b in OPERANDS]
    rows = results(rars, tmp_path, binary_source(mnemonic, "rne", pairs))
    overflows_of_rounding = 0
    for (a, b), row in zip(pairs, rows):
        ours = BINARY[mnemonic](a, b, BINARY32, RNE)
        nan = first_nan(a, b)
        if nan is not None:  # DEV-32, DEV-33: RARS hands the operand back
            expected = (nan, 0)
            assert ours[0] == BINARY32.canonical_nan
        else:
            expected = their_flags(ours, exact_binary(mnemonic, a, b))
            overflows_of_rounding += expected != ours
        assert row == expected, f"{mnemonic} {a:08x} {b:08x}"
    if mnemonic in ("fadd.s", "fsub.s", "fmul.s"):
        assert overflows_of_rounding, "the matrix must reach the overflow of DEV-38"


@pytest.mark.parametrize("mode", MODES)
def test_the_operations_in_every_rounding_mode(rars, tmp_path, mode):
    """A smaller table, but all four operations and all five modes."""
    chosen = OPERANDS[:3] + (0x00000001, 0x7F7FFFFF, 0x3F800001, 0x73000000, 0x64042108)
    pairs = [(a, b) for a in chosen for b in chosen]
    body = ""
    for a, b in pairs:
        body += (f"        flw ft0, {4 * OPERANDS.index(a)}(s0)\n"
                 f"        flw ft1, {4 * OPERANDS.index(b)}(s0)\n")
        for mnemonic in BINARY:
            body += f"        {mnemonic} ft2, ft0, ft1, {mode}\n        showf ft2\n"
    source = (PREAMBLE + ".data\n" + data_block("v", OPERANDS, ".word")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    for index, (a, b) in enumerate(pairs):
        for offset, mnemonic in enumerate(BINARY):
            ours = BINARY[mnemonic](a, b, BINARY32, MODES[mode])
            expected = their_flags(ours, exact_binary(mnemonic, a, b))
            assert rows[len(BINARY) * index + offset] == expected, \
                f"{mnemonic} {mode} {a:08x} {b:08x}"


def test_the_square_root_of_every_operand_in_every_mode(rars, tmp_path):
    body = ""
    for mode in MODES:
        body += "".join(f"        flw ft0, {4 * i}(s0)\n"
                        f"        fsqrt.s ft2, ft0, {mode}\n        showf ft2\n"
                        for i in range(len(OPERANDS)))
    source = (PREAMBLE + ".data\n" + data_block("v", OPERANDS, ".word")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    index = 0
    for mode in MODES:
        for operand in OPERANDS:
            ours = square_root(operand, BINARY32, MODES[mode])
            nan = first_nan(operand)
            assert rows[index] == ((nan, 0) if nan is not None else ours), \
                f"fsqrt.s {mode} {operand:08x}"
            index += 1


def test_the_fused_product(rars, tmp_path):
    values = sorted({bits for triple in FUSED for bits in triple})
    body = "".join(f"        flw ft0, {4 * values.index(a)}(s0)\n"
                   f"        flw ft1, {4 * values.index(b)}(s0)\n"
                   f"        flw ft2, {4 * values.index(c)}(s0)\n"
                   "        fmadd.s ft3, ft0, ft1, ft2, rne\n        showf ft3\n"
                   for a, b, c in FUSED)
    source = (PREAMBLE + ".data\n" + data_block("v", values, ".word")
              + ".text\nmain:   la s0, v\n" + body + EPILOGUE)
    rows = results(rars, tmp_path, source)
    for (a, b, c), row in zip(FUSED, rows):
        ours = fused_multiply_add(a, b, c, BINARY32, RNE)
        nan = first_nan(a, b, c)
        if nan is not None:
            assert row == (nan, 0) and ours[0] == BINARY32.canonical_nan
            continue
        exact = None
        if all(formats.is_finite(bits, BINARY32) for bits in (a, b, c)):
            exact = value_of(a) * value_of(b) + value_of(c)
        assert row == their_flags(ours, exact), f"fmadd.s {a:08x} {b:08x} {c:08x}"


def test_rars_hands_back_the_first_nan_operand(rars, tmp_path):  # DEV-32, DEV-33
    """The NaN of an operand survives, payload, signalling bit and all, and no
    flag is raised; only the fused instructions that negate an operand return it
    with the other sign. We give the canonical NaN and raise NV for a
    signalling operand."""
    quiet, other, signalling, one = 0x7FC00001, 0x7FC00002, 0x7F800001, 0x3F800000
    source = (PREAMBLE + ".data\n"
              + data_block("v", (quiet, other, signalling, one), ".word")
              + ".text\nmain:   la s0, v\n"
              "        flw ft0, 0(s0)\n        flw ft1, 4(s0)\n"
              "        flw ft2, 8(s0)\n        flw ft3, 12(s0)\n"
              "        fadd.s ft4, ft0, ft1, rne\n        showf ft4\n"
              "        fadd.s ft4, ft1, ft0, rne\n        showf ft4\n"
              "        fadd.s ft4, ft1, ft2, rne\n        showf ft4\n"
              "        fmul.s ft4, ft0, ft1, rne\n        showf ft4\n"
              "        fdiv.s ft4, ft1, ft0, rne\n        showf ft4\n"
              "        fsub.s ft4, ft3, ft0, rne\n        showf ft4\n"
              "        fsqrt.s ft4, ft0, rne\n        showf ft4\n"
              "        fmadd.s ft4, ft3, ft3, ft0, rne\n        showf ft4\n"
              "        fmsub.s ft4, ft3, ft3, ft0, rne\n        showf ft4\n"
              "        fnmadd.s ft4, ft0, ft3, ft3, rne\n        showf ft4\n" + EPILOGUE)
    assert results(rars, tmp_path, source) == [
        (quiet, 0),  # the first operand wins, whatever the second is
        (other, 0),
        (other, 0),  # a signalling NaN does not win over a quiet one before it
        (quiet, 0),
        (other, 0),
        (quiet, 0),  # fsub does not negate the NaN it hands back
        (quiet, 0),
        (quiet, 0),
        (negate(quiet, BINARY32), 0),  # fmsub negates the addend, NaN and all
        (negate(quiet, BINARY32), 0),  # fnmadd negates the product
    ]
    # ours: the canonical NaN, and NV as soon as an operand is signalling
    assert add(quiet, other, BINARY32, RNE) == (BINARY32.canonical_nan, 0)
    assert add(other, signalling, BINARY32, RNE) == (BINARY32.canonical_nan, NV)
    assert square_root(quiet, BINARY32, RNE) == (BINARY32.canonical_nan, 0)
    assert fused_multiply_add(one, one, signalling, BINARY32,
                              RNE) == (BINARY32.canonical_nan, NV)


@pytest.mark.parametrize("mnemonic", ["fmadd.s", "fmsub.s", "fnmadd.s", "fnmsub.s"])
def test_rars_fails_on_a_fused_product_with_an_infinite_addend(rars, tmp_path, mnemonic):
    """DEV-40: jsoftfloat turns the addend into an exact value, which an
    infinity has none of, and RARS dies of a NullPointerException. It happens
    for all four fused instructions and in double precision as well; a zero or
    infinite product takes another path and works."""
    source = (".data\nv: .word 0x3f800000, 0x7f800000\n"
              ".text\nmain:   la s0, v\n        flw ft0, 0(s0)\n        flw ft1, 4(s0)\n"
              f"        {mnemonic} ft2, ft0, ft0, ft1, rne\n"
              "        li a7, 93\n        li a0, 0\n        ecall\n")
    path = tmp_path / "p.s"
    path.write_text(source)
    done = rars.run([path])
    assert done.exit_code != 0 and "NullPointerException" in done.stderr

    # ours: an infinite addend swallows a finite product (IEEE 754-2019 §5.4.1)
    one, infinity = 0x3F800000, 0x7F800000
    assert fused_multiply_add(one, one, infinity, BINARY32, RNE) == (infinity, 0)
    assert fused_multiply_add(one, one, negate(infinity, BINARY32),
                              BINARY32, RNE) == (negate(infinity, BINARY32), 0)
    assert fused_multiply_add(0x3FF0000000000000, 0x3FF0000000000000,
                              0x7FF0000000000000, BINARY64, RNE) == (0x7FF0000000000000, 0)
