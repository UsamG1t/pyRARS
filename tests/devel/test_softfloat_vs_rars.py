"""T-FP, stage 12: classification, comparisons and rounding as RARS does them.

The oracle runs a program that prints, for every case, the result and the
exception flags it raised; our side calls `pyrars.softfloat` with the same bit
patterns. Rounding is reached through `fcvt.s.d`: narrowing a double to a
single is exactly "round this exact value to binary32", so the whole table of
`round_value` can be compared without any arithmetic instruction.

Two places differ on purpose: RARS decides the overflow flag from the exponent
of the exact result, so it misses an overflow that the rounding itself creates
(DEV-38), and its FLT and FLE answer by the sign of the first operand when that
operand is an infinity (DEV-39). Classification, FEQ, FMIN and FMAX agree.
"""

import pytest

from pyrars.softfloat import formats
from pyrars.softfloat.compare import equal, less, less_equal, maximum, minimum
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import NX, OF, RDN, RMM, RNE, RTZ, RUP, round_value

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
