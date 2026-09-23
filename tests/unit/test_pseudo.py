"""Pseudo-instructions: the table itself, the choice of a variant, expansion and errors."""

import pytest

from pyrars.asm import pseudo
from pyrars.asm.expressions import ExprError, Value
from pyrars.asm.lexer import tokenize_line
from pyrars.asm.operands import OperandError
from pyrars.asm.parser import parse_statement
from pyrars.asm.source import SourceLine
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, mnemonics

TEXT, DATA = 0x00400000, 0x10010000
SYMBOLS = {"loop": Value(TEXT + 0x10, "text"), "msg": Value(DATA, "data"), "N": Value(20)}


def resolve(ref):
    if ref.name not in SYMBOLS:
        raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
    return SYMBOLS[ref.name]


def known_only(*names):
    """A resolver of pass 1: only these symbols are known yet."""
    def resolver(ref):
        if ref.name not in names:
            raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
        return SYMBOLS[ref.name]
    return resolver


def statement(text, xlen=32):
    operators = mnemonics(xlen) | pseudo.mnemonics(xlen)
    tokens, errors = tokenize_line(text, operators, "p.s", 1)
    assert errors == []
    result, errors = parse_statement(SourceLine("p.s", 1, text, text, tuple(tokens)))
    assert errors == []
    return result


def candidates(text, xlen=32):
    return pseudo.match(statement(text, xlen), xlen)


def expansion(text, pc=TEXT, xlen=32, resolver=resolve):
    """(mnemonic, fields) of every basic instruction the statement becomes."""
    matched = candidates(text, xlen)
    chosen = pseudo.choose(matched, resolver, pseudo.size(matched, resolver))
    return [(e.instr.mnemonic, e.fields) for e in pseudo.expand(chosen, resolver, pc, xlen)]


def words(text, pc=TEXT, xlen=32):
    matched = candidates(text, xlen)
    chosen = pseudo.choose(matched, resolve, pseudo.size(matched, resolve))
    return [encode(e.instr, e.fields) for e in pseudo.expand(chosen, resolve, pc, xlen)]


# ------------------------------------------------------------------- the table


def test_every_template_is_a_basic_instruction_with_matching_operands():
    for row in pseudo.TABLE:
        for template in row.templates:
            instr = find(template.mnemonic, row.xlen or 64)
            assert instr is not None, f"{row.mnemonic}: no basic instruction {template.mnemonic}"
            assert len(instr.operands) == len(template.parts), f"{row.mnemonic} -> {template.mnemonic}"


def test_every_template_part_refers_to_an_operand_of_the_row():
    for row in pseudo.TABLE:
        for template in row.templates:
            for part in template.parts:
                if isinstance(part, pseudo.Const):
                    continue
                assert 1 <= part.n <= len(row.kinds), f"{row.mnemonic}: {part}"


def test_operand_kinds_are_known():
    known = set(pseudo._INTEGER_REGISTER) | set(pseudo._FP_REGISTER) | set(pseudo._RANGES) | {"csr", "symbol"}
    for row in pseudo.TABLE:
        assert set(row.kinds) <= known, f"{row.mnemonic}: {row.kinds}"


def test_mnemonics_of_both_xlens():
    assert {"li", "la", "mv", "ret", "call", "fence", "pause", "lla"} <= pseudo.mnemonics(32)
    assert "sext.w" in pseudo.mnemonics(64) and "sext.w" not in pseudo.mnemonics(32)
    assert "ld" in pseudo.mnemonics(64) and "ld" not in pseudo.mnemonics(32)


def test_a_basic_instruction_is_not_a_pseudo_instruction():
    assert candidates("addi t0, t1, 1") == []


# --------------------------------------------------------------- expansions


@pytest.mark.parametrize("text, expected", [
    ("nop", [("addi", dict(rd=0, rs1=0, imm=0))]),
    ("mv t0, t1", [("addi", dict(rd=5, rs1=6, imm=0))]),  # DEV-22: the asm manual, not "add"
    ("not t0, t1", [("xori", dict(rd=5, rs1=6, imm=-1))]),
    ("neg t0, t1", [("sub", dict(rd=5, rs1=0, rs2=6))]),
    ("seqz t0, t1", [("sltiu", dict(rd=5, rs1=6, imm=1))]),
    ("sgt t0, t1, t2", [("slt", dict(rd=5, rs1=7, rs2=6))]),
    ("zext.b t0, t1", [("andi", dict(rd=5, rs1=6, imm=255))]),
    ("sext.b t0, t1", [("slli", dict(rd=5, rs1=6, shamt=24)),
                       ("srai", dict(rd=5, rs1=5, shamt=24))]),
    ("fmv.s ft0, ft1", [("fsgnj.s", dict(rd=0, rs1=1, rs2=1))]),
    ("fge.s t0, ft1, ft2", [("fle.s", dict(rd=5, rs1=2, rs2=1))]),
    ("ret", [("jalr", dict(rd=0, rs1=1, imm=0))]),
    ("jr t0", [("jalr", dict(rd=0, rs1=5, imm=0))]),
    ("jr -4(t0)", [("jalr", dict(rd=0, rs1=5, imm=-4))]),  # DEV-26 (asm manual)
    ("jalr t0, t1", [("jalr", dict(rd=5, rs1=6, imm=0))]),  # DEV-26
    ("fence", [("fence", dict(pred=15, succ=15))]),  # DEV-3
    ("pause", [("fence", dict(pred=1, succ=0))]),  # DEV-26
    ("csrr t0, fcsr", [("csrrs", dict(rd=5, csr=3, rs1=0))]),
    ("csrw fcsr, t0", [("csrrw", dict(rd=0, csr=3, rs1=5))]),  # DEV-23: the CSR comes first
    ("csrwi 0x300, 7", [("csrrwi", dict(rd=0, csr=0x300, uimm=7))]),
    ("frcsr t0", [("csrrs", dict(rd=5, csr=3, rs1=0))]),
    ("fscsr t0, t1", [("csrrw", dict(rd=5, csr=3, rs1=6))]),
    ("fscsr t0", [("csrrw", dict(rd=0, csr=3, rs1=5))]),
    ("rdinstreth t0", [("csrrs", dict(rd=5, csr=0xC82, rs1=0))]),
])
def test_expansion_fields(text, expected):
    assert expansion(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("j loop", [("jal", dict(rd=0, imm=0x10))]),
    ("b loop", [("jal", dict(rd=0, imm=0x10))]),
    ("jal loop", [("jal", dict(rd=1, imm=0x10))]),
    ("beqz t0, loop", [("beq", dict(rs1=5, rs2=0, imm=0x10))]),
    ("bgtz t0, loop", [("blt", dict(rs1=0, rs2=5, imm=0x10))]),
    ("ble t0, t1, loop", [("bge", dict(rs1=6, rs2=5, imm=0x10))]),
])
def test_targets_are_relative_to_the_instruction(text, expected):
    assert expansion(text) == expected


def test_a_target_of_the_second_instruction_uses_its_own_address():
    # call: auipc gets the distance from the statement, jalr the lower part of it
    assert expansion("call loop") == [("auipc", dict(rd=6, imm=0)),
                                      ("jalr", dict(rd=1, rs1=6, imm=0x10))]


def test_a_target_in_a_later_template_uses_the_address_of_that_instruction():
    # No row of the table branches from its second instruction, so the rule is
    # checked on a row built here.
    row = pseudo.Pseudo("two", "symbol", (pseudo.t("addi", pseudo.X0, pseudo.X0, pseudo.Const(0)),
                                          pseudo.t("jal", pseudo.X0, pseudo.Target(1))))
    candidate = pseudo.Candidate(row, candidates("j loop")[0].operands)
    expanded = pseudo.expand(candidate, resolve, TEXT)
    assert [(e.instr.mnemonic, e.fields) for e in expanded] == [
        ("addi", dict(rd=0, rs1=0, imm=0)), ("jal", dict(rd=0, imm=0x10 - 4))]


def test_the_expansion_takes_the_instruction_of_the_program_width():
    """A row of both widths must use the description of the running width:
    `slli` holds 5 bits of shift amount in RV32 and 6 in RV64. No row of the
    table uses such an instruction today, so the rule is checked on a row
    built here."""
    row = pseudo.Pseudo("shift", "rd, rs", (pseudo.t("slli", pseudo.Reg(1), pseudo.Reg(2),
                                                     pseudo.Const(40)),))
    candidate = pseudo.Candidate(row, candidates("mv t0, t1")[0].operands)
    expanded = pseudo.expand(candidate, resolve, TEXT, 64)
    assert expanded[0].instr.format.__name__ == "Shift6"
    assert encode(expanded[0].instr, expanded[0].fields) == 0x02831293  # slli x5, x6, 40
    narrow = pseudo.expand(candidate, resolve, TEXT, 32)
    assert narrow[0].instr.format.__name__ == "Shift5"
    with pytest.raises(ValueError):  # 40 does not fit the 5 bits of RV32
        encode(narrow[0].instr, narrow[0].fields)


def test_addresses_split_into_upper_and_lower_parts():
    # msg - pc = 0x10010000 - 0x00400000 = 0x0FC10000, bit 11 is 0
    assert expansion("la t0, msg") == [("auipc", dict(rd=5, imm=0x0FC10)),
                                       ("addi", dict(rd=5, rs1=5, imm=0))]
    # a distance whose bit 11 is set: the upper part is increased by one
    assert expansion("la t0, msg", pc=TEXT + 0x800) == [("auipc", dict(rd=5, imm=0x0FC10)),
                                                        ("addi", dict(rd=5, rs1=5, imm=-0x800))]


def test_loads_and_stores_of_an_address():
    assert expansion("lw t0, msg") == [("auipc", dict(rd=5, imm=0x0FC10)),
                                       ("lw", dict(rd=5, imm=0, rs1=5))]
    assert expansion("sw t0, msg, t1") == [("auipc", dict(rd=6, imm=0x0FC10)),
                                           ("sw", dict(rs2=5, imm=0, rs1=6))]
    assert expansion("flw ft0, msg, t1") == [("auipc", dict(rd=6, imm=0x0FC10)),
                                             ("flw", dict(rd=0, imm=0, rs1=6))]


# ------------------------------------------------------- choice of a variant


@pytest.mark.parametrize("text, count", [
    ("li t0, 0", 1), ("li t0, 2047", 1), ("li t0, -2048", 1),
    ("li t0, 2048", 2), ("li t0, -2049", 2), ("li t0, N * 1000", 2),
    ("lw t0, 8", 1), ("lw t0, 100000", 2), ("lw t0, msg", 2),
    ("sw t0, 8", 1), ("sw t0, 100000, t1", 2),
])
def test_number_of_instructions_follows_the_value(text, count):
    assert len(words(text)) == count


def test_values_of_the_long_and_short_forms():
    assert words("li t0, 5") == [encode(find("addi", 32), dict(rd=5, rs1=0, imm=5))]
    # 100000 = 0x186A0: upper part 0x18, lower part 0x6A0 (bit 11 is 0)
    assert expansion("li t0, 100000") == [("lui", dict(rd=5, imm=0x18)),
                                          ("addi", dict(rd=5, rs1=5, imm=0x6A0))]
    # 0xFFFFFFFF is -1 in 32 bits (DEV-13): the upper part carries over to 0
    assert expansion("li t0, 0xFFFFFFFF") == [("lui", dict(rd=5, imm=0)),
                                              ("addi", dict(rd=5, rs1=5, imm=-1))]


def test_rv64_uses_addiw_for_a_32_bit_value():
    assert expansion("li t0, 100000", xlen=64) == [("lui", dict(rd=5, imm=0x18)),
                                                   ("addiw", dict(rd=5, rs1=5, imm=0x6A0))]


def test_an_unknown_value_reserves_the_longest_variant():  # DEV-24
    matched = candidates("li t0, N")  # N is not known in pass 1 yet
    assert pseudo.size(matched, known_only()) == 2
    # in pass 2 the value is known and would fit the short variant, but the
    # reserved size decides; the long variant gives the same value
    chosen = pseudo.choose(matched, resolve, 2)
    assert [(e.instr.mnemonic, e.fields) for e in pseudo.expand(chosen, resolve, TEXT)] == [
        ("lui", dict(rd=5, imm=0)), ("addi", dict(rd=5, rs1=5, imm=20))]


def test_a_short_variant_is_used_when_the_value_is_known_in_pass_1():
    matched = candidates("lw t0, 8")
    assert pseudo.size(matched, known_only()) == 1


def test_the_long_variant_is_correct_for_a_small_value_as_well():
    matched = candidates("li t0, 5")
    long = [c for c in matched if len(c.pseudo.templates) == 2][0]
    expanded = pseudo.expand(long, resolve, TEXT)
    assert [(e.instr.mnemonic, e.fields) for e in expanded] == [("lui", dict(rd=5, imm=0)),
                                                                ("addi", dict(rd=5, rs1=5, imm=5))]


# ------------------------------------------------------------------- errors


@pytest.mark.parametrize("text, column, message", [
    ("li t0", 1, '"li": Too few or incorrectly formatted operands. Expected: li rd, imm'),
    ("ret t0", 1, '"ret": Too many or incorrectly formatted operands. Expected: ret'),
    ("mv t0, t1, t2", 1, '"mv": Too many or incorrectly formatted operands. Expected: mv rd, rs'),
    ("mv 5, t1", 4, '"5": operand is of incorrect type'),
    ("fmv.s t0, ft1", 7, '"t0": operand is of incorrect type'),
    ("csrw t0, fcsr", 1, '"csrw": operands are reversed. Expected: csrw csr, rs'),  # DEV-23
    ("csrs t0, fcsr", 1, '"csrs": operands are reversed. Expected: csrs csr, rs'),
])
def test_matching_errors(text, column, message):
    with pytest.raises(OperandError) as error:
        candidates(text)
    assert (error.value.column, error.value.message) == (column, message)


@pytest.mark.parametrize("text, column, message", [
    ("la t0, 8", 8, '"8": operand is of incorrect type'),  # an address is needed
    ("li t0, msg", 8, '"msg": operand is of incorrect type'),  # a number is needed
    ("li t0, 0x100000000", 8, '"0x100000000": operand is out of range'),
    ("csrwi 0x300, 32", 14, '"32": operand is out of range'),
    ("j msg", 3, "Jump target word address beyond 20-bit range"),
])
def test_value_errors(text, column, message):
    with pytest.raises(OperandError) as error:
        words(text)
    assert (error.value.column, error.value.message) == (column, message)


def test_an_undefined_symbol_is_reported_in_pass_2():
    matched = candidates("la t0, missing")
    with pytest.raises(ExprError) as error:
        pseudo.choose(matched, resolve, 2)
    assert error.value.message == 'Symbol "missing" not found in symbol table.'
