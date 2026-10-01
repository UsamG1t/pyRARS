"""What the floating point instructions do to the machine.

The arithmetic is checked in the tests of `pyrars.softfloat`; here it is the
wiring that matters - which register a value comes from and goes to, how wide it
is, that a single is boxed, that the flags land in `fcsr`, and that a reserved
rounding mode is refused with the message of RARS.

Expected values come from the ISA manual v20260120 (chapters F and D) and from the
verified behaviour of RARS recorded in R-FP and R-REG.
"""

import pytest

from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.traps import ILLEGAL_INSTRUCTION, Trap
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT
from pyrars.isa.registers import CSRS
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.rounding import DYN, NV, NX, RNE, RTZ, RUP

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
ONE, TWO, THREE = 0x3F800000, 0x40000000, 0x40400000
D_ONE, D_THREE = 0x3FF0000000000000, 0x4008000000000000
CANONICAL = BINARY32.canonical_nan


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def machine(*words: int, xlen: int = 32, singles: dict[int, int] | None = None,
            doubles: dict[int, int] | None = None, **values: int) -> Machine:
    m = Machine(Options(xlen=xlen))
    for index, value in enumerate(words):
        m.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in (singles or {}).items():
        m.f.set_single(number, value)
    for number, value in (doubles or {}).items():
        m.f.set_double(number, value)
    for name, value in values.items():
        m.x.write(int(name[1:]), value)
    return m


def step(m: Machine) -> None:
    execute(m, m.fetch())


def flags(m: Machine) -> int:
    return m.csr.read(CSRS["fflags"])


# ------------------------------------------------------------ loads and stores


def test_a_single_is_loaded_boxed_and_stored_as_it_lies():
    m = machine(word("flw", rd=1, rs1=5, imm=0), word("fsw", rs2=1, rs1=5, imm=8), x5=DATA)
    m.memory.write(DATA, 4, ONE)
    step(m)
    assert m.f.raw(1) == 0xFFFFFFFF3F800000 and m.f.single(1) == ONE
    step(m)
    assert m.memory.read(DATA + 8, 4) == ONE


def test_a_double_uses_the_whole_register():
    m = machine(word("fld", rd=2, rs1=5, imm=0), word("fsd", rs2=2, rs1=5, imm=8), x5=DATA)
    m.memory.write(DATA, 8, D_THREE)
    step(m)
    assert m.f.raw(2) == D_THREE
    step(m)
    assert m.memory.read(DATA + 8, 8) == D_THREE


def test_storing_a_register_that_is_no_boxed_single_takes_its_low_word():
    """Verified in RARS: `fsw` copies the bits, it does not read a number."""
    m = machine(word("fsw", rs2=3, rs1=5, imm=0), x5=DATA,
                doubles={3: 0x1122334455667788})
    step(m)
    assert m.memory.read(DATA, 4) == 0x55667788


# ---------------------------------------------------------------- arithmetic


@pytest.mark.parametrize("mnemonic, expected, raised", [
    ("fadd.s", 0x40800000, 0),  # 1 + 3
    ("fsub.s", 0xC0000000, 0),  # 1 - 3
    ("fmul.s", THREE, 0),
    ("fdiv.s", 0x3EAAAAAB, NX),  # one third
])
def test_an_operation_of_two_singles(mnemonic, expected, raised):
    m = machine(word(mnemonic, rd=4, rs1=1, rs2=2, rm=RNE), singles={1: ONE, 2: THREE})
    step(m)
    assert m.f.single(4) == expected and m.f.raw(4) >> 32 == 0xFFFFFFFF
    assert flags(m) == raised


def test_an_operation_of_two_doubles():
    m = machine(word("fdiv.d", rd=4, rs1=1, rs2=2, rm=RNE), doubles={1: D_ONE, 2: D_THREE})
    step(m)
    assert m.f.double(4) == 0x3FD5555555555555 and flags(m) == NX


def test_the_square_root():
    m = machine(word("fsqrt.s", rd=4, rs1=1, rm=RNE), singles={1: TWO})
    step(m)
    assert m.f.single(4) == 0x3FB504F3 and flags(m) == NX


@pytest.mark.parametrize("mnemonic, expected", [
    ("fmadd.s", 0x41200000),  # 3 * 3 + 1 is 10
    ("fmsub.s", 0x41000000),  # 3 * 3 - 1 is 8
    ("fnmsub.s", 0xC1000000),  # -(3 * 3) + 1 is -8
    ("fnmadd.s", 0xC1200000),  # -(3 * 3) - 1 is -10
])
def test_the_four_fused_instructions(mnemonic, expected):
    m = machine(word(mnemonic, rd=4, rs1=1, rs2=1, rs3=2, rm=RNE),
                singles={1: THREE, 2: ONE})
    step(m)
    assert m.f.single(4) == expected


def test_the_flags_of_the_operations_pile_up_in_fcsr():
    m = machine(word("fdiv.s", rd=4, rs1=1, rs2=2, rm=RNE),  # inexact
                word("fdiv.s", rd=5, rs1=3, rs2=3, rm=RNE),  # zero by zero: invalid
                singles={1: ONE, 2: THREE, 3: 0})
    step(m)
    assert flags(m) == NX
    step(m)
    assert flags(m) == NX | NV and m.f.single(5) == CANONICAL


# ------------------------------------------------------------ rounding modes


@pytest.mark.parametrize("mode, expected", [
    (RNE, 0x3EAAAAAB), (RTZ, 0x3EAAAAAA), (RUP, 0x3EAAAAAB)])
def test_the_mode_of_the_instruction_is_used(mode, expected):
    m = machine(word("fdiv.s", rd=4, rs1=1, rs2=2, rm=mode), singles={1: ONE, 2: THREE})
    step(m)
    assert m.f.single(4) == expected


def test_the_dynamic_mode_is_read_from_frm():
    m = machine(word("fdiv.s", rd=4, rs1=1, rs2=2, rm=DYN), singles={1: ONE, 2: THREE})
    m.csr.write(CSRS["frm"], RTZ)
    step(m)
    assert m.f.single(4) == 0x3EAAAAAA


@pytest.mark.parametrize("field, frm, text", [
    (5, 0, "Invalid rounding mode. RM = 5 and frm = 0"),
    (6, 0, "Invalid rounding mode. RM = 6 and frm = 0"),
    (DYN, 5, "Invalid rounding mode. RM = 7 and frm = 5"),
    (DYN, 7, "Invalid rounding mode. RM = 7 and frm = 7"),
])
def test_a_reserved_rounding_mode_is_refused(field, frm, text):
    """The message of RARS, word for word (verified)."""
    base = word("fadd.s", rd=4, rs1=1, rs2=2, rm=RNE)
    m = machine((base & ~(7 << 12)) | (field << 12), singles={1: ONE, 2: THREE})
    m.csr.write(CSRS["frm"], frm)
    with pytest.raises(Trap) as raised:
        step(m)
    assert (raised.value.cause, raised.value.message) == (ILLEGAL_INSTRUCTION, text)


# --------------------------------------------------- comparisons and the rest


@pytest.mark.parametrize("mnemonic, expected", [("fmin.s", ONE), ("fmax.s", THREE)])
def test_the_smaller_and_the_larger(mnemonic, expected):
    m = machine(word(mnemonic, rd=4, rs1=1, rs2=2), singles={1: ONE, 2: THREE})
    step(m)
    assert m.f.single(4) == expected


@pytest.mark.parametrize("mnemonic, expected", [
    ("feq.s", 0), ("flt.s", 1), ("fle.s", 1)])
def test_a_comparison_writes_an_integer_register(mnemonic, expected):
    m = machine(word(mnemonic, rd=6, rs1=1, rs2=2), singles={1: ONE, 2: THREE})
    step(m)
    assert m.x.read(6) == expected and flags(m) == 0


def test_a_comparison_with_a_nan_raises_the_invalid_flag():
    m = machine(word("flt.s", rd=6, rs1=1, rs2=2), singles={1: CANONICAL, 2: THREE})
    step(m)
    assert m.x.read(6) == 0 and flags(m) == NV


def test_the_class_of_a_value():
    m = machine(word("fclass.s", rd=6, rs1=1), word("fclass.d", rd=7, rs1=2),
                singles={1: 0x80000000}, doubles={2: D_ONE})
    step(m)
    assert m.x.read(6) == 0x008  # a negative zero
    step(m)
    assert m.x.read(7) == 0x040  # a positive normal number


@pytest.mark.parametrize("mnemonic, expected", [
    ("fsgnj.s", 0xBF800000),  # the sign of -3 on the value 1
    ("fsgnjn.s", ONE),  # and that sign turned around
    ("fsgnjx.s", 0xBF800000),  # the two signs together
])
def test_the_sign_of_one_value_on_another(mnemonic, expected):
    m = machine(word(mnemonic, rd=4, rs1=1, rs2=2), singles={1: ONE, 2: 0xC0400000})
    step(m)
    assert m.f.single(4) == expected and flags(m) == 0


def test_the_sign_injection_reads_its_operands_as_numbers():
    """Verified in RARS: a register that holds no boxed single reads as the
    canonical NaN here too, so its value is the one that gets a sign."""
    m = machine(word("fsgnj.s", rd=4, rs1=1, rs2=2), doubles={1: 0x1122334455667788},
                singles={2: 0xBF800000})
    step(m)
    assert m.f.single(4) == CANONICAL | 0x80000000


# --------------------------------------------------------------- conversions


@pytest.mark.parametrize("mnemonic, value, expected, raised", [
    ("fcvt.w.s", 0x40490FDB, 3, NX),  # pi, toward zero
    ("fcvt.w.s", 0xC0490FDB, 0xFFFFFFFD, NX),  # -pi
    ("fcvt.w.s", 0x4F000000, 0x7FFFFFFF, NV),  # 2**31 does not fit
    ("fcvt.wu.s", 0xBF800000, 0, NV),  # -1 has no unsigned value
    ("fcvt.wu.s", 0x4F7FFFFF, 0xFFFFFF00, 0),  # a large unsigned value
])
def test_a_conversion_to_an_integer(mnemonic, value, expected, raised):
    m = machine(word(mnemonic, rd=6, rs1=1, rm=RTZ), singles={1: value})
    step(m)
    assert m.x.read(6) == expected and flags(m) == raised


@pytest.mark.parametrize("mnemonic, value, expected", [
    ("fcvt.s.w", 3, THREE),
    ("fcvt.s.w", 0xFFFFFFFF, 0xBF800000),  # -1
    ("fcvt.s.wu", 0xFFFFFFFF, 0x4F800000),  # 2**32 - 1 rounded
])
def test_a_conversion_from_an_integer(mnemonic, value, expected):
    m = machine(word(mnemonic, rd=4, rs1=6, rm=RNE), x6=value)
    step(m)
    assert m.f.single(4) == expected


def test_a_conversion_between_the_formats():
    m = machine(word("fcvt.d.s", rd=4, rs1=1, rm=RNE),
                word("fcvt.s.d", rd=5, rs1=2, rm=RNE),
                singles={1: ONE}, doubles={2: 0x3FD5555555555555})
    step(m)
    assert m.f.double(4) == D_ONE and flags(m) == 0
    step(m)
    assert m.f.single(5) == 0x3EAAAAAB and flags(m) == NX


def test_the_conversions_of_a_64_bit_machine():
    m = machine(word("fcvt.l.s", xlen=64, rd=6, rs1=1, rm=RTZ),
                word("fcvt.lu.s", xlen=64, rd=7, rs1=1, rm=RTZ),
                word("fcvt.s.l", xlen=64, rd=4, rs1=8, rm=RNE),
                word("fcvt.w.s", xlen=64, rd=9, rs1=2, rm=RTZ),
                xlen=64, singles={1: 0x5E800000, 2: 0xC0490FDB}, x8=-3)
    step(m)
    assert m.x.read(6) == 1 << 62
    step(m)
    assert m.x.read(7) == 1 << 62
    step(m)
    assert m.f.single(4) == 0xC0400000  # -3.0
    step(m)
    # a result of 32 bits is written with its sign extended
    assert m.x.read(9) == 0xFFFFFFFFFFFFFFFD


def test_an_unsigned_result_of_32_bits_is_extended_by_its_sign_too():
    """Verified in RARS: fcvt.wu.s of 3e9 in RV64 gives 0xffffffffb2d05e00."""
    m = machine(word("fcvt.wu.s", xlen=64, rd=6, rs1=1, rm=RTZ),
                xlen=64, singles={1: 0x4F32D05E})  # 3e9
    step(m)
    assert m.x.read(6) == 0xFFFFFFFFB2D05E00


# ---------------------------------------------------------------- the moves


def test_the_bits_of_a_register_move_to_the_other_file():
    m = machine(word("fmv.x.w", rd=6, rs1=1), word("fmv.w.x", rd=4, rs1=7),
                singles={1: 0xC0000000}, x7=ONE)
    step(m)
    assert m.x.read(6) == 0xC0000000  # the bits, read as a number of 32 bits
    step(m)
    assert m.f.raw(4) == 0xFFFFFFFF3F800000  # and boxed on the way back


def test_a_move_of_32_bits_extends_the_sign_on_a_64_bit_machine():
    m = machine(word("fmv.x.w", xlen=64, rd=6, rs1=1), xlen=64, singles={1: 0xC0000000})
    step(m)
    assert m.x.read(6) == 0xFFFFFFFFC0000000


def test_a_move_of_the_whole_register():
    m = machine(word("fmv.x.d", xlen=64, rd=6, rs1=1),
                word("fmv.d.x", xlen=64, rd=4, rs1=7),
                xlen=64, doubles={1: 0x1122334455667788}, x7=0x8899AABBCCDDEEFF)
    step(m)
    assert m.x.read(6) == 0x1122334455667788
    step(m)
    assert m.f.raw(4) == 0x8899AABBCCDDEEFF


def test_every_instruction_of_the_two_extensions_is_carried_out():
    """Nothing of F and D is left over: what the table holds, the machine does."""
    from pyrars.core.floats import MNEMONICS
    assert len(MNEMONICS) == 62
    for mnemonic in MNEMONICS:
        name, _, rest = mnemonic.partition(".")
        assert (mnemonic in ("flw", "fsw", "fld", "fsd") or name in
                {"fadd", "fsub", "fmul", "fdiv", "fsqrt", "fmadd", "fmsub", "fnmadd",
                 "fnmsub", "fmin", "fmax", "feq", "flt", "fle", "fclass", "fsgnj",
                 "fsgnjn", "fsgnjx", "fcvt", "fmv"}), mnemonic
