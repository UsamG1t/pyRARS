"""Disassembling a word gives the same instruction as the listing of RARS.

The program of T-ISA holds every basic instruction with two operand variants.
RARS assembles it and its listing says, for every word, which instruction it
is; we read the words back and compare.

Numbers are compared as numbers: RARS writes a value of its listing in decimal
when it fits five bits and in hexadecimal otherwise (a leftover of its token
classes), while we always write signed decimal (DEV-30). The comparison also
maps the two instructions RARS calls by their old names (DEV-1).
"""

import re

import pytest

from pyrars.asm.disasm import text
from pyrars.isa.instructions import instructions
from test_isa_vs_rars import PAD, RENAMED, TEXT_BASE, sample

pytestmark = pytest.mark.devel


def parts(written: str) -> tuple[str, list[str | int]]:
    """Mnemonic and operands of an instruction text; numbers become numbers."""
    mnemonic, _, rest = written.partition(" ")
    operands: list[str | int] = []
    for operand in re.findall(r"[^,()]+|\(|\)", rest):
        operand = operand.strip()
        if re.fullmatch(r"-?0[xX][0-9a-fA-F]+", operand):
            number = int(operand, 16)
        elif re.fullmatch(r"-?\d+", operand):
            number = int(operand)
        else:
            if operand:
                operands.append(operand)
            continue
        if number >= 1 << 31:  # RARS writes a negative value as 8 hexadecimal digits
            number -= 1 << 32
        operands.append(number)
    return RENAMED.get(mnemonic, mnemonic), operands


def program_of(xlen):
    """The program of T-ISA: every basic instruction with two operand variants."""
    table = [(instr, variant) for instr in instructions(xlen) for variant in (0, 1)]
    start = TEXT_BASE + 4 * PAD
    last = start + 4 * (len(table) + PAD)
    lines = [sample(instr, variant, start + 4 * n, last)[0]
             for n, (instr, variant) in enumerate(table)]
    pad = ["addi x0, x0, 0"] * PAD
    return "\n".join([".text", "first:", *pad, *lines, *pad, "last:", "ecall", ""])


@pytest.mark.parametrize("xlen", [32, 64])
def test_every_instruction_reads_back_like_the_rars_listing(rars, tmp_path, xlen):
    path = tmp_path / "all.s"
    path.write_text(program_of(xlen))
    result = rars.assemble([path], options=("rv64",) if xlen == 64 else ())
    assert result.messages == []

    wrong = []
    for row in result.listing[PAD:-PAD]:  # the padding is "addi x0, x0, 0"
        ours = text(row.code, xlen)
        if ours is None or parts(ours) != parts(row.basic):
            wrong.append(f"{row.code:08x}: ours {ours!r}, rars {row.basic!r}")
    assert wrong == []


def test_the_listing_of_a_program_matches_ours(rars, tmp_path):
    """The basic column that the assembler fills == the column of RARS."""
    source = (".text\nmain: li t0, 5\nla t1, msg\nlw t2, msg\nbeqz t0, main\n"
              "fadd.s ft0, ft1, ft2\ncsrr a0, fcsr\nret\n.data\nmsg: .asciz \"hi\"\n")
    path = tmp_path / "p.s"
    path.write_text(source)
    result = rars.assemble([path])
    assert result.messages == []

    from pyrars.asm.assembler import assemble
    program = assemble([str(path)])
    assert program.diagnostics == ()
    ours = [(entry.address, parts(entry.basic)) for entry in program.text]
    assert ours == [(row.address, parts(row.basic)) for row in result.listing]
    assert program.text[0].address == TEXT_BASE
