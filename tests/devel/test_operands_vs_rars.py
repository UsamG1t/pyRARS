"""Statements with basic instructions go through lexer, parser and operand
matching to the same machine words and operand errors as RARS.

1. Every basic instruction with two operand variants (the program of
   test_isa_vs_rars): our words == RARS words.
2. Operand errors where RARS and pyrars agree: same line, column, text (the
   text after "Expected:" differs by DEV-14 and is compared only up to it).
3. Approved deviations DEV-12, DEV-13, DEV-15, DEV-16: RARS still behaves as recorded.
"""

import pytest

from pyrars.asm.expressions import ExprError, Value
from pyrars.asm.lexer import tokenize_line
from pyrars.asm.operands import OperandError, field_value, match_operands
from pyrars.asm.parser import parse_statement
from pyrars.asm.source import SourceLine
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, instructions, mnemonics
from test_isa_vs_rars import ECALL, NOP, PAD, TEXT_BASE, sample

pytestmark = pytest.mark.devel


def assemble_line(text, xlen, pc, symbols):
    """Machine word of one basic instruction line, or the error (column, message)."""
    tokens, errors = tokenize_line(text, mnemonics(xlen), "t.s", 1)
    assert errors == []
    statement, errors = parse_statement(SourceLine("t.s", 1, text, text, tuple(tokens)))
    if errors:
        return errors[0].loc.column, errors[0].message
    instr = find(statement.name.text.lower(), xlen)

    def resolve(ref):
        if ref.name not in symbols:
            raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
        return symbols[ref.name]

    try:
        fields = {name: field_value(instr, name, operand, resolve, pc)
                  for name, operand in match_operands(statement, instr).items()}
    except (OperandError, ExprError) as e:
        return e.column, e.message
    return encode(instr, fields)


@pytest.mark.parametrize("xlen", [32, 64])
def test_every_basic_instruction(rars, tmp_path, xlen):
    table = [(instr, variant) for instr in instructions(xlen) for variant in (0, 1)]
    start = TEXT_BASE + 4 * PAD
    last = start + 4 * (len(table) + PAD)
    symbols = {"first": Value(TEXT_BASE, "text"), "last": Value(last, "text")}
    lines = [sample(instr, variant, start + 4 * n, last)[0] for n, (instr, variant) in enumerate(table)]
    ours = [assemble_line(line, xlen, start + 4 * n, symbols) for n, line in enumerate(lines)]

    pad = ["addi x0, x0, 0"] * PAD
    source = tmp_path / "all.s"
    source.write_text("\n".join([".text", "first:", *pad, *lines, *pad, "last:", "ecall", ""]))
    result = rars.assemble([source], options=("rv64",) if xlen == 64 else ())

    assert result.messages == []
    assert result.text[:PAD] == [NOP] * PAD and result.text[-1] == ECALL
    wrong = [f"{line}: ours {word}, rars {theirs:08x}"
             for line, word, theirs in zip(lines, ours, result.text[PAD:]) if word != theirs]
    assert wrong == []


AGREED_ERRORS = [
    "add t0, t1, 5",
    "addi t0, t1, t2",
    "fadd.s fa0, fa1, t2, dyn",
    "lw t0, 8(fa0)",
    "csrrw t0, t1, t2",
    "addi t0, t0, 2048",
    "addi t0, t0, 0xFFF",
    "addi t0, t0, -2049",
    "slli t0, t0, 32",
    "lui t0, 0x100000",
    "beq t0, t1, 8",
    "addi t0, t0",
    "addi t0, t0, 1, 2",
    "ecall 1",
]


def until_expected(message):
    return message.split(" Expected:")[0]


def test_same_operand_errors(rars, tmp_path):
    source = tmp_path / "errors.s"
    source.write_text(".text\n" + "\n".join(AGREED_ERRORS) + "\n")
    result = rars.assemble([source])
    theirs = sorted({(m.line, m.column, until_expected(m.text)) for m in result.messages})
    ours = []
    for number, line in enumerate(AGREED_ERRORS, start=2):
        column, message = assemble_line(line, 32, TEXT_BASE, {})
        ours.append((number, column, until_expected(message)))
    assert sorted(ours) == theirs


def rars_result(rars, tmp_path, text):
    source = tmp_path / "dev.s"
    source.write_text(text)
    result = rars.assemble([source])
    return result, sorted({(m.line, m.column, m.text) for m in result.messages})


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    # DEV-13: RARS takes 0xFFFFFFFF in addi as -1; strict ranges reject it
    result, errors = rars_result(rars, tmp_path, ".text\naddi t0, t0, 0xFFFFFFFF\n")
    assert errors == [] and result.text == [0xFFF28293]
    assert assemble_line("addi t0, t0, 0xFFFFFFFF", 32, 0, {}) == (14, '"0xFFFFFFFF": operand is out of range')

    # DEV-12: RARS has no expressions
    result, errors = rars_result(rars, tmp_path, ".text\naddi t0, t0, 1+2\n")
    assert errors and result.text == []
    assert assemble_line("addi t0, t0, 1+2", 32, 0, {}) == 0x00328293

    # DEV-12: a name in an immediate is a symbol of the expression; RARS rejects it by token type
    result, errors = rars_result(rars, tmp_path, ".text\naddi t0, t0, missing\n")
    assert errors == [(2, 14, '"missing": operand is of incorrect type')]
    assert assemble_line("addi t0, t0, missing", 32, 0, {}) == (14, 'Symbol "missing" not found in symbol table.')
    assert assemble_line("addi t0, t0, N", 32, 0, {"N": Value(5)}) == 0x00528293

    # DEV-16: RARS treats a comma as a blank
    result, errors = rars_result(rars, tmp_path, ".text\naddi t0 t0 1\n")
    assert errors == [] and result.text == [0x00128293]
    assert assemble_line("addi t0 t0 1", 32, 0, {})[1].startswith('"addi": Too few')

    # DEV-15: RARS allows one label per line
    result, errors = rars_result(rars, tmp_path, ".text\na: c: addi t0, t0, 1\n")
    assert errors and result.text == []
    tokens, _ = tokenize_line("a: c: addi t0, t0, 1", mnemonics(32))
    statement, errors = parse_statement(SourceLine("t.s", 1, "", "", tuple(tokens)))
    assert errors == [] and [t.text for t in statement.labels] == ["a", "c"]
