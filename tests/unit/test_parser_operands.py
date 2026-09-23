"""Statement structure (parser) and operand matching (operands): DEV-3, DEV-12..16."""

import pytest

from pyrars.asm.expressions import ExprError, LocalRef, Value
from pyrars.asm.lexer import tokenize_line
from pyrars.asm.operands import OperandError, field_value, match_operands
from pyrars.asm.parser import parse_statement
from pyrars.asm.source import SourceLine
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, mnemonics

OPERATORS = mnemonics(64) | {"li", "la", "j"}


def statement(text):
    tokens, errors = tokenize_line(text, OPERATORS, "p.s", 1)
    assert errors == []
    result, errors = parse_statement(SourceLine("p.s", 1, text, text, tuple(tokens)))
    assert errors == [], errors
    return result


def parse_error(text):
    tokens, _ = tokenize_line(text, OPERATORS, "p.s", 1)
    result, errors = parse_statement(SourceLine("p.s", 1, text, text, tuple(tokens)))
    assert result is None
    return [(e.loc.column, e.message) for e in errors]


# ------------------------------------------------------------------ parser


def test_statement_parts():
    s = statement("loop: addi t0, t0, -1  # count")
    assert [t.text for t in s.labels] == ["loop"]
    assert s.name.text == "addi"
    assert [[t.text for t in group] for group in s.operands] == [["t0"], ["t0"], ["-", "1"]]


def test_several_labels_and_numeric_labels():  # DEV-15, DEV-4
    s = statement("a: 1: j: 22: nop")
    assert [t.text for t in s.labels] == ["a", "1", "j", "22"]
    assert s.name.text == "nop"


def test_labels_only_and_empty_lines():
    assert statement("done:").name is None
    assert statement("   # comment").labels == () and statement("").name is None


def test_operand_groups_keep_parentheses_and_expressions():
    s = statement(".word 1 + 2 * (3 - 4), label - 8, 'a'")
    assert [len(group) for group in s.operands] == [9, 3, 1]


@pytest.mark.parametrize("text, column, message", [
    ("t0: nop", 1, '"t0" is not a recognized operator'),
    ("5 addi", 1, '"5" is not a recognized operator'),
    ("0x10: nop", 1, '"0x10" is not a recognized operator'),  # numeric labels are decimal digits
    ("addi , t0", 6, 'Missing operand before ","'),
    ("addi t0,, t0", 9, 'Missing operand before ","'),
    ("addi t0, t0,", 12, 'Missing operand after ","'),
])
def test_structure_errors(text, column, message):
    assert parse_error(text) == [(column, message)]


# ---------------------------------------------------------------- operands


def operands(text, xlen=32):
    s = statement(text)
    return match_operands(s, find(s.name.text.lower(), xlen))


def values(text, xlen=32, resolve=None, pc=0):
    s = statement(text)
    instr = find(s.name.text.lower(), xlen)
    return {name: field_value(instr, name, operand, resolve, pc)
            for name, operand in match_operands(s, instr).items()}


SYMBOLS = {"here": Value(0x400000, "text"), "far": Value(0x400000 + 4096, "text"),
           "data": Value(0x10010000, "data"), "N": Value(3)}


def resolve(ref):
    if isinstance(ref, LocalRef):
        return Value(0x400008 if ref.forward else 0x3FFFF8, "text")
    if ref.name not in SYMBOLS:
        raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
    return SYMBOLS[ref.name]


@pytest.mark.parametrize("text, expected", [
    ("add a0, x1, t6", dict(rd=10, rs1=1, rs2=31)),
    ("ADDI t0, zero, -N * 4 + 1", dict(rd=5, rs1=0, imm=-11)),
    ("lw a0, 8(sp)", dict(rd=10, imm=8, rs1=2)),
    ("lw a0, (sp)", dict(rd=10, imm=0, rs1=2)),
    ("lw a0, (N + 1) * 4(sp)", dict(rd=10, imm=16, rs1=2)),
    ("sw ra, -4(sp)", dict(rs2=1, imm=-4, rs1=2)),
    ("lw a0, %lo(data + 4)(a0)", dict(rd=10, imm=4, rs1=10)),
    ("lui a0, %hi(data)", dict(rd=10, imm=0x10010)),
    ("fadd.s fa0, fa1, f2, rtz", dict(rd=10, rs1=11, rs2=2, rm=1)),
    ("fadd.s fa0, fa1, f2", dict(rd=10, rs1=11, rs2=2, rm=7)),  # DEV-25: "dyn" by default
    ("fsqrt.d fa0, fa1", dict(rd=10, rs1=11, rm=7)),
    ("fcvt.w.s a0, fa0", dict(rd=10, rs1=10, rm=7)),
    ("fcvt.w.s a0, fa0, dyn", dict(rd=10, rs1=10, rm=7)),
    ("fsw fs0, 0(a0)", dict(rs2=8, imm=0, rs1=10)),
    ("fmv.x.s a0, fa0", dict(rd=10, rs1=10)),  # DEV-1 alias
    ("csrrw t0, fcsr, t1", dict(rd=5, csr=3, rs1=6)),
    ("csrrs t0, 0xC00, x0", dict(rd=5, csr=0xC00, rs1=0)),
    ("csrrwi t0, ustatus, 31", dict(rd=5, csr=0, uimm=31)),
    ("fence rw, w", dict(pred=3, succ=1)),  # DEV-3
    ("fence iorw, 1 + 1", dict(pred=15, succ=2)),
    ("slli t0, t0, 31", dict(rd=5, rs1=5, shamt=31)),
    ("ecall", {}),
])
def test_operand_values(text, expected):
    assert values(text, resolve=resolve) == expected


def test_branch_and_jump_offsets_are_relative_to_the_instruction():
    assert values("beq t0, t1, here", resolve=resolve, pc=0x400010) == dict(rs1=5, rs2=6, imm=-16)
    assert values("bne t0, t1, 1f", resolve=resolve, pc=0x400000) == dict(rs1=5, rs2=6, imm=8)
    assert values("jal ra, here + 8", resolve=resolve, pc=0x400000) == dict(rd=1, imm=8)


def test_encoding_of_matched_operands():
    s = statement("addi t0, t0, 4 * 8")
    instr = find("addi", 32)
    fields = {name: field_value(instr, name, op, resolve, 0) for name, op in match_operands(s, instr).items()}
    assert encode(instr, fields) == (32 << 20 | 5 << 15 | 5 << 7 | 0b0010011)


@pytest.mark.parametrize("text, column, message", [
    ("addi t0, t0", 1, '"addi": Too few or incorrectly formatted operands. Expected: addi rd, rs1, imm'),
    ("ADDI t0, t0, 1, 2", 1, '"ADDI": Too many or incorrectly formatted operands. Expected: addi rd, rs1, imm'),
    ("ecall 1", 1, '"ecall": Too many or incorrectly formatted operands. Expected: ecall'),
    ("fadd.s fa0, fa1", 1, '"fadd.s": Too few or incorrectly formatted operands. '
                           "Expected: fadd.s rd, rs1, rs2, rm"),  # only the rounding mode is optional
    ("lw t0, 8", 1, '"lw": Too few or incorrectly formatted operands. Expected: lw rd, imm(rs1)'),
    ("addi t0 t0, 1", 1, '"addi": Too few or incorrectly formatted operands. Expected: addi rd, rs1, imm'),
    ("add t0 t1, t2, t3", 1, '"add": Too many or incorrectly formatted operands. Expected: add rd, rs1, rs2'),
    ("add t0, t1, 5", 13, '"5": operand is of incorrect type'),
    ("addi t0, t1, t2", 14, '"t2": operand is of incorrect type'),
    ("fadd.s fa0, fa1, t2, dyn", 18, '"t2": operand is of incorrect type'),
    ("fadd.s fa0, fa1, fa2, 7", 23, '"7": operand is of incorrect type'),
    ("fcvt.w.s fa0, fa0, dyn", 10, '"fa0": operand is of incorrect type'),
    ("lw t0, 8(fa0)", 10, '"fa0": operand is of incorrect type'),
    ("csrrw t0, t1, t2", 11, '"t1": operand is of incorrect type'),
    ("addi t0, t1, 1 +", 16, "Incomplete expression"),
    ("addi t0, t1, (1", 14, '"(": missing ")"'),
])
def test_operand_errors(text, column, message):
    with pytest.raises(OperandError) as error:
        operands(text)
    assert (error.value.column, error.value.message) == (column, message)


@pytest.mark.parametrize("text, message", [
    ("addi t0, t0, 2048", '"2048": Unsigned value is too large to fit into a sign-extended immediate'),
    ("addi t0, t0, 0xFFF", '"0xFFF": Unsigned value is too large to fit into a sign-extended immediate'),
    ("addi t0, t0, 0xFFFFFFFF", '"0xFFFFFFFF": operand is out of range'),  # DEV-13: RARS takes -1
    ("addi t0, t0, -2049", '"-2049": operand is out of range'),
    ("slli t0, t0, 32", '"32": operand is out of range'),
    ("lui t0, 0x100000", '"0x100000": operand is out of range'),
    ("lui t0, -1", '"-1": operand is out of range'),
    ("csrrs t0, 4096, x0", '"4096": operand is out of range'),
    ("fence 16, 1", '"16": operand is out of range'),
    ("addi t0, t0, data", '"data": operand is of incorrect type'),  # an address is not a number
    ("beq t0, t1, 8", '"8": operand is of incorrect type'),  # a branch target is an address
    ("beq t0, t1, far", "Branch target word address beyond 12-bit range"),
    ("jal ra, data", "Jump target word address beyond 20-bit range"),
    ("addi t0, t0, missing", 'Symbol "missing" not found in symbol table.'),
])
def test_value_errors(text, message):
    with pytest.raises((OperandError, ExprError)) as error:
        values(text, resolve=resolve, pc=0x400000)
    assert error.value.message == message


def test_ranges_at_the_limits():
    assert values("addi t0, t0, -2048")["imm"] == -2048
    assert values("addi t0, t0, 2047")["imm"] == 2047
    assert values("slli t0, t0, 63", xlen=64)["shamt"] == 63
    assert values("lui t0, 0xFFFFF")["imm"] == 0xFFFFF
    assert values("beq t0, t1, far", resolve=resolve, pc=0x400002)["imm"] == 4094
