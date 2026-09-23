"""Pseudo-instructions expand to the same machine words as RARS.

1. A program of pseudo-instructions is laid out and expanded here (a small two
   pass assembler over pyrars.asm.pseudo) and compared word by word with RARS.
2. Messages of errors where RARS and pyrars agree.
3. Approved deviations DEV-13, DEV-22..DEV-26: RARS still behaves as recorded.
"""

import pytest

from pyrars.asm import pseudo
from pyrars.asm.expressions import ExprError, Value
from pyrars.asm.lexer import tokenize_line
from pyrars.asm.operands import OperandError, field_value, match_operands
from pyrars.asm.parser import parse_statement
from pyrars.asm.source import SourceLine
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, mnemonics
from test_isa_vs_rars import TEXT_BASE

pytestmark = pytest.mark.devel

DATA_BASE = 0x10010000

# Pseudo-instructions where RARS and pyrars agree; "start" is the first
# instruction of the program and "msg" the only word of the data segment.
PROGRAM = """\
li t0, 5
li t1, 100000
li t2, 0xFFFFFF
li t3, -2049
la t4, msg
lw t5, msg
sw t6, msg, t0
lb a0, 8
sb a1, 12
lw a2, 100000
j start
b start
jal start
beqz t0, start
bnez t0, start
blez t0, start
bgt t0, t1, start
bleu t0, t1, start
call start
tail start
ret
jr t0
jalr t0
nop
not t0, t1
neg t0, t1
seqz t0, t1
snez t0, t1
sgt t0, t1, t2
sgtu t0, t1, t2
zext.b t0, t1
sext.b t0, t1
sext.h t0, t1
fmv.s ft0, ft1
fabs.s ft0, ft1
fneg.s ft0, ft1
fgt.s t0, ft1, ft2
fge.d t0, ft1, ft2
fadd.s ft0, ft1, ft2
fsqrt.d ft0, ft1
csrr t0, fcsr
csrwi fcsr, 3
frcsr t0
fscsr t0, t1
frrm t0
fsflags t0
rdcycle t0
rdinstret t1
rdtimeh t2
flw ft0, msg, t0
fsw ft1, msg, t0
"""


def statement(text, xlen=32):
    operators = mnemonics(xlen) | pseudo.mnemonics(xlen)
    tokens, errors = tokenize_line(text, operators, "p.s", 1)
    assert errors == []
    result, errors = parse_statement(SourceLine("p.s", 1, text, text, tuple(tokens)))
    assert errors == []
    return result


def resolver(symbols):
    def resolve(ref):
        if ref.name not in symbols:
            raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
        return symbols[ref.name]
    return resolve


def assemble(lines, symbols, xlen=32):
    """Words of a program: sizes first (pass 1), then the expansion (pass 2).

    A line whose mnemonic is not a pseudo-instruction is a basic one and takes
    one word (a floating point instruction without a rounding mode, DEV-25).
    """
    resolve = resolver(symbols)
    statements = [statement(line, xlen) for line in lines]
    matched = [pseudo.match(s, xlen) for s in statements]
    sizes = [pseudo.size(c, resolve) if c else 1 for c in matched]
    words = []
    address = TEXT_BASE
    for s, candidates, size in zip(statements, matched, sizes):
        if candidates:
            chosen = pseudo.choose(candidates, resolve, size)
            words += [encode(e.instr, e.fields)
                      for e in pseudo.expand(chosen, resolve, address, xlen)]
        else:
            words.append(basic_word(s, resolve, address, xlen))
        address += 4 * size
    return words


def basic_word(s, resolve, address, xlen):
    instr = find(s.name.text.lower(), xlen)
    fields = {name: field_value(instr, name, operand, resolve, address)
              for name, operand in match_operands(s, instr).items()}
    return encode(instr, fields)


def test_program_expands_like_rars(rars, tmp_path):
    lines = PROGRAM.splitlines()
    source = tmp_path / "p.s"
    source.write_text(".text\nstart:\n" + PROGRAM + ".data\nmsg: .word 0\n")
    result = rars.assemble([source])
    assert result.messages == []

    symbols = {"start": Value(TEXT_BASE, "text"), "msg": Value(DATA_BASE, "data")}
    assert assemble(lines, symbols) == result.text


AGREED_ERRORS = [
    ("li t0\n", '"li": Too few or incorrectly formatted operands.'),
    ("la t0, 8\n", '"8": operand is of incorrect type'),
    ("li t0, msg\n.data\nmsg: .word 0\n", '"msg": operand is of incorrect type'),
    ("mv t0, 5\n", '"5": operand is of incorrect type'),
]


@pytest.mark.parametrize("text, message", AGREED_ERRORS)
def test_same_pseudo_errors(rars, tmp_path, text, message):
    source = tmp_path / "e.s"
    source.write_text(".text\n" + text)
    result = rars.assemble([source])
    theirs = [(m.line, m.column, m.text.split(" Expected:")[0]) for m in result.messages]
    assert theirs and theirs[0][2] == message

    with pytest.raises(OperandError) as error:
        line = text.splitlines()[0]
        candidates = pseudo.match(statement(line), 32)
        chosen = pseudo.choose(candidates, resolver({"msg": Value(DATA_BASE, "data")}))
        pseudo.expand(chosen, resolver({"msg": Value(DATA_BASE, "data")}), TEXT_BASE)
    assert error.value.message.split(" Expected:")[0] == message
    assert (2, error.value.column) == theirs[0][:2]


def test_the_64_bit_li_matches_rars(rars, tmp_path):
    """RV64: a value wider than 32 bits becomes the eight instructions of RARS."""
    lines = ["li t0, 0x1122334455667788", "li t1, 0x100000000", "li t2, 5",
             "li t3, 100000", "li t4, -1", "li t5, 0x7FFFFFFF"]
    source = tmp_path / "li64.s"
    source.write_text(".text\n" + "\n".join(lines) + "\n")
    result = rars.assemble([source], ("rv64",))
    assert result.messages == []
    assert assemble(lines, {}, xlen=64) == result.text


def rars_result(rars, tmp_path, text):
    source = tmp_path / "d.s"
    source.write_text(text)
    result = rars.assemble([source])
    return result, [(m.line, m.column, m.text) for m in result.messages]


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    symbols = {"start": Value(TEXT_BASE, "text")}

    # DEV-22: RARS expands mv to "add rd, x0, rs"
    result, errors = rars_result(rars, tmp_path, ".text\nmv t0, t1\n")
    assert errors == [] and result.text == [0x006002B3]  # add x5, x0, x6
    assert assemble(["mv t0, t1"], symbols) == [0x00030293]  # addi x5, x6, 0

    # DEV-23: RARS writes a CSR with the register first
    result, errors = rars_result(rars, tmp_path, ".text\ncsrw t0, fcsr\n")
    assert errors == [] and result.text == [0x00329073]
    assert assemble(["csrw fcsr, t0"], symbols) == result.text
    with pytest.raises(OperandError) as error:
        pseudo.match(statement("csrw t0, fcsr"), 32)
    assert error.value.message == '"csrw": operands are reversed. Expected: csrw csr, rs'

    # DEV-13: RARS reads 0xFFFFFFFF as -1, so one instruction is enough for it
    result, errors = rars_result(rars, tmp_path, ".text\nli t0, 0xFFFFFFFF\n")
    assert errors == [] and result.text == [0xFFF00293]  # addi x5, x0, -1
    assert assemble(["li t0, 0xFFFFFFFF"], symbols) == [0x000002B7, 0xFFF28293]  # lui + addi

    # DEV-26: pseudo-instructions of the asm manual that RARS does not know
    for line in ("lla t0, start", "pause", "fence", "jalr t0, t1", "jr 4(t0)",
                 "jump start, t0", "call t0, start"):
        _, errors = rars_result(rars, tmp_path, ".text\nstart: " + line + "\n")
        assert errors, line
        assert assemble([line], symbols)  # ours assembles them

    # DEV-25: for RARS a floating point instruction without a rounding mode is
    # a pseudo-instruction; for us the operand is optional. Same words.
    result, errors = rars_result(rars, tmp_path, ".text\nfadd.s ft0, ft1, ft2\n")
    assert errors == [] and result.text == [0x0020F053]  # rounding mode dyn = 7
    assert pseudo.match(statement("fadd.s ft0, ft1, ft2"), 32) == []  # a basic instruction for us
    assert assemble(["fadd.s ft0, ft1, ft2"], symbols) == result.text
