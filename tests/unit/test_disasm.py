"""Disassembler: a machine word back to the text of a basic instruction."""

import pytest

from pyrars.asm.disasm import text
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, instructions


@pytest.mark.parametrize("word, expected", [
    (0x00128293, "addi x5,x5,1"),
    (0xFFF28293, "addi x5,x5,-1"),  # a negative immediate is signed decimal
    (0x006282B3, "add x5,x5,x6"),
    (0x01F29293, "slli x5,x5,31"),
    (0x0FC10297, "auipc x5,0x0fc10"),  # the upper immediate is a bit pattern
    (0x000182B7, "lui x5,0x00018"),
    (0xFE0298E3, "bne x5,x0,-16"),  # a branch keeps its distance, as in RARS
    (0x0080006F, "jal x0,8"),
    (0x00008067, "jalr x0,x1,0"),
    (0xFEC3A383, "lw x7,-20(x7)"),  # the memory form
    (0x00732423, "sw x7,8(x6)"),
    (0x0020F053, "fadd.s f0,f1,f2,dyn"),  # the rounding mode by its name
    (0x002081D3, "fadd.s f3,f1,f2,rne"),
    (0x00329073, "csrrw x0,3,x5"),  # the CSR by its number
    (0x0FF0000F, "fence 15,15"),
    (0x00000073, "ecall"),
])
def test_words_become_text(word, expected):
    assert text(word) == expected


@pytest.mark.parametrize("word, expected", [
    (0x00128293, "addi t0,t0,1"),
    (0x00008067, "jalr zero,ra,0"),
    (0x0020F053, "fadd.s ft0,ft1,ft2,dyn"),
    (0x00329073, "csrrw zero,fcsr,t0"),  # the CSR by its name as well
    (0xFEC3A383, "lw t2,-20(t2)"),
])
def test_names_of_the_calling_convention(word, expected):
    assert text(word, abi=True) == expected


@pytest.mark.parametrize("word", [0x00000000, 0xFFFFFFFF, 0x0000007F, 0x000000FF])
def test_a_word_that_is_no_instruction(word):
    assert text(word) is None


def test_the_instruction_set_of_the_xlen_decides():
    word = encode(find("addiw", 64), dict(rd=5, rs1=5, imm=1))
    assert text(word, 64) == "addiw x5,x5,1"
    assert text(word, 32) is None


@pytest.mark.parametrize("xlen", [32, 64])
def test_every_instruction_can_be_written_back(xlen):
    """Encoding the operands of an instruction and reading the word gives its text."""
    for instr in instructions(xlen):
        fields = {name: 0 for name in instr.format.fields if name not in instr.fixed}
        word = encode(instr, fields)
        written = text(word, xlen)
        assert written is not None, f"{instr.mnemonic}: the word does not decode"
        assert written.split(" ")[0] == instr.mnemonic
        assert written.count(",") == instr.syntax.count(",")
