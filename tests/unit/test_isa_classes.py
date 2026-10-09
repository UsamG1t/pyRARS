"""The kind of an instruction and the registers it touches.

Expected values are derived by hand from the RISC-V ISA manual v20260120: the
opcode of every instruction, which of its operands name registers, and what each
does with them. The five kinds RARS counts by are recorded from its own sources
(`tools/InstructionStatistics` compares against the classes `Arithmetic` - which
the multiplication and division of RARS extend - `JAL`, `JALR`, `Branch`, `Load`
and `Store`, and calls everything else Other; `FLW` and `FSW` extend neither
`Load` nor `Store`, so they are Other there).
"""

import pytest

from pyrars.isa.classes import (CATEGORIES, Kind, RegRef, category, kind, reads,
                                writes)
from pyrars.isa.codec import decode, encode
from pyrars.isa.instructions import find, instructions
from pyrars.isa.spec import Reg


def decoded(mnemonic: str, xlen: int = 64, **fields: int):
    return decode(encode(find(mnemonic, xlen), fields), xlen)


# ------------------------------------------------------------------- the kinds


@pytest.mark.parametrize("mnemonic, expected", [
    ("add", Kind.ALU), ("sub", Kind.ALU), ("and", Kind.ALU), ("slt", Kind.ALU),
    ("addi", Kind.ALU), ("slli", Kind.ALU), ("srai", Kind.ALU), ("andi", Kind.ALU),
    ("lui", Kind.ALU), ("auipc", Kind.ALU), ("addw", Kind.ALU), ("slliw", Kind.ALU),
    ("mul", Kind.MULTIPLY), ("mulh", Kind.MULTIPLY), ("mulhsu", Kind.MULTIPLY),
    ("mulw", Kind.MULTIPLY),
    ("div", Kind.DIVIDE), ("divu", Kind.DIVIDE), ("rem", Kind.DIVIDE),
    ("remuw", Kind.DIVIDE),
    ("lb", Kind.LOAD), ("lw", Kind.LOAD), ("lwu", Kind.LOAD), ("ld", Kind.LOAD),
    ("sb", Kind.STORE), ("sw", Kind.STORE), ("sd", Kind.STORE),
    ("beq", Kind.BRANCH), ("bgeu", Kind.BRANCH),
    ("jal", Kind.JUMP), ("jalr", Kind.JUMP),
    ("csrrw", Kind.CSR), ("csrrsi", Kind.CSR),
    ("ecall", Kind.SYSTEM), ("ebreak", Kind.SYSTEM), ("uret", Kind.SYSTEM),
    ("wfi", Kind.SYSTEM),
    ("fence", Kind.FENCE), ("fence.i", Kind.FENCE),
    ("fadd.s", Kind.FLOAT), ("fdiv.d", Kind.FLOAT), ("fsqrt.s", Kind.FLOAT),
    ("fmadd.s", Kind.FLOAT), ("feq.d", Kind.FLOAT), ("fcvt.w.s", Kind.FLOAT),
    ("fmv.x.w", Kind.FLOAT), ("fclass.d", Kind.FLOAT),
    ("flw", Kind.FLOAT_LOAD), ("fld", Kind.FLOAT_LOAD),
    ("fsw", Kind.FLOAT_STORE), ("fsd", Kind.FLOAT_STORE),
])
def test_what_kind_an_instruction_is(mnemonic, expected):
    assert kind(find(mnemonic, 64)) is expected


# How many instructions of each kind there are, which pins the whole table: a
# mnemonic that moved from one kind to another shows up here.
COUNTS = {
    32: {Kind.ALU: 21, Kind.MULTIPLY: 4, Kind.DIVIDE: 4, Kind.LOAD: 5, Kind.STORE: 3,
         Kind.BRANCH: 6, Kind.JUMP: 2, Kind.CSR: 6, Kind.SYSTEM: 4, Kind.FENCE: 2,
         Kind.FLOAT: 48, Kind.FLOAT_LOAD: 2, Kind.FLOAT_STORE: 2},
    64: {Kind.ALU: 30, Kind.MULTIPLY: 5, Kind.DIVIDE: 8, Kind.LOAD: 7, Kind.STORE: 4,
         Kind.BRANCH: 6, Kind.JUMP: 2, Kind.CSR: 6, Kind.SYSTEM: 4, Kind.FENCE: 2,
         Kind.FLOAT: 58, Kind.FLOAT_LOAD: 2, Kind.FLOAT_STORE: 2},
}


@pytest.mark.parametrize("xlen", [32, 64])
def test_how_many_of_each_kind(xlen):
    """The numbers also say which instructions a width has: 109 for RV32 and 136 for
    RV64 (M1), and a 64-bit machine has nine more of the base set, four more
    divisions and ten more floating point conversions."""
    counted = {}
    for instr in instructions(xlen):
        counted[kind(instr)] = counted.get(kind(instr), 0) + 1
    assert counted == COUNTS[xlen]
    assert sum(counted.values()) == len(instructions(xlen))


@pytest.mark.parametrize("xlen", [32, 64])
def test_every_instruction_has_one_kind(xlen):
    for instr in instructions(xlen):
        assert isinstance(kind(instr), Kind), instr.mnemonic


def test_every_kind_is_used_and_counted_somewhere():
    """No kind is invented for nothing, and none is left out of the five of RARS."""
    used = {kind(instr) for instr in instructions(64)}
    assert used == set(Kind)
    assert set(CATEGORIES) == set(Kind)


# -------------------------------------------------------- the five kinds of RARS


@pytest.mark.parametrize("mnemonic, expected", [
    ("add", "ALU"), ("addi", "ALU"), ("lui", "ALU"), ("srai", "ALU"),
    ("mul", "ALU"), ("div", "ALU"),  # RARS writes them as the same kind as `add`
    ("jal", "Jump"), ("jalr", "Jump"),
    ("beq", "Branch"),
    ("lw", "Memory"), ("sb", "Memory"),
    ("flw", "Other"), ("fsw", "Other"),  # neither is a Load or a Store there
    ("fadd.s", "Other"), ("csrrw", "Other"), ("ecall", "Other"), ("fence", "Other"),
])
def test_the_kind_rars_counts_it_as(mnemonic, expected):
    assert category(find(mnemonic, 64)) == expected


def test_the_five_kinds_hold_every_instruction():
    counted = {}
    for instr in instructions(64):
        counted[category(instr)] = counted.get(category(instr), 0) + 1
    assert counted == {"ALU": 43, "Jump": 2, "Branch": 6, "Memory": 11, "Other": 74}


# ------------------------------------------------------------------ the registers


@pytest.mark.parametrize("mnemonic, fields, read, written", [
    ("add", dict(rd=5, rs1=6, rs2=7), [("x", 6), ("x", 7)], [("x", 5)]),
    ("addi", dict(rd=5, rs1=6, imm=1), [("x", 6)], [("x", 5)]),
    ("lui", dict(rd=5, imm=1), [], [("x", 5)]),
    ("lw", dict(rd=5, rs1=6, imm=0), [("x", 6)], [("x", 5)]),
    ("sw", dict(rs1=6, rs2=7, imm=0), [("x", 6), ("x", 7)], []),
    ("beq", dict(rs1=6, rs2=7, imm=8), [("x", 6), ("x", 7)], []),
    ("jal", dict(rd=1, imm=8), [], [("x", 1)]),
    ("jalr", dict(rd=1, rs1=6, imm=0), [("x", 6)], [("x", 1)]),
    ("csrrw", dict(rd=5, rs1=6, csr=1), [("x", 6)], [("x", 5)]),
    ("fadd.s", dict(rd=1, rs1=2, rs2=3, rm=0), [("f", 2), ("f", 3)], [("f", 1)]),
    ("fmadd.d", dict(rd=1, rs1=2, rs2=3, rs3=4, rm=0),
     [("f", 2), ("f", 3), ("f", 4)], [("f", 1)]),
    ("flw", dict(rd=1, rs1=6, imm=0), [("x", 6)], [("f", 1)]),
    ("fsw", dict(rs1=6, rs2=1, imm=0), [("x", 6), ("f", 1)], []),
    ("fcvt.w.s", dict(rd=5, rs1=1, rm=0), [("f", 1)], [("x", 5)]),
    ("fcvt.s.w", dict(rd=1, rs1=5, rm=0), [("x", 5)], [("f", 1)]),
    ("fmv.x.w", dict(rd=5, rs1=1), [("f", 1)], [("x", 5)]),
    ("fmv.w.x", dict(rd=1, rs1=5), [("x", 5)], [("f", 1)]),
])
def test_which_registers_an_instruction_touches(mnemonic, fields, read, written):
    found = decoded(mnemonic, **fields)
    assert reads(found) == tuple(RegRef(file, number) for file, number in read)
    assert writes(found) == tuple(RegRef(file, number) for file, number in written)


def test_the_register_that_holds_zero_is_no_dependence():
    """x0 keeps its zero whatever is written to it, so nothing can depend on it."""
    assert writes(decoded("addi", rd=0, rs1=1, imm=1)) == (RegRef("x", 1),) * 0
    assert reads(decoded("add", rd=5, rs1=0, rs2=0)) == ()
    # but a floating point register 0 is an ordinary register
    assert reads(decoded("fadd.s", rd=1, rs1=0, rs2=0, rm=0)) == (RegRef("f", 0),) * 2


@pytest.mark.parametrize("xlen", [32, 64])
def test_no_register_of_an_instruction_is_overlooked(xlen):
    """Every operand that names a register is one of the four the rules know, so
    `reads` and `writes` cannot miss one."""
    known = {"rd", "rs1", "rs2", "rs3"}
    for instr in instructions(xlen):
        for name in instr.operands:
            if instr.format.fields[name].kind is Reg:
                assert name in known, f"{instr.mnemonic}: {name}"


@pytest.mark.parametrize("xlen", [32, 64])
def test_every_floating_point_operand_is_a_register(xlen):
    """`fp` names operands, and every one of them must be a register operand."""
    for instr in instructions(xlen):
        for name in instr.fp.split():
            assert instr.format.fields[name].kind is Reg, f"{instr.mnemonic}: {name}"
