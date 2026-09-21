"""Consistency of the declarative ISA description."""

from typing import Annotated

import pytest

from pyrars.isa import formats
from pyrars.isa.instructions import INSTRUCTIONS, instructions
from pyrars.isa.registers import CSRS, F_NAMES, X_NAMES
from pyrars.isa.spec import Bits, Fixed, Format, Instr, Reg, SImm


def test_instruction_counts():
    # RARS 1.6 basic instruction set (compared with RARS in tests/devel)
    assert len(instructions(32)) == 109
    assert len(instructions(64)) == 136


@pytest.mark.parametrize("xlen", [32, 64])
def test_mnemonics_unique(xlen):
    mnemonics = [i.mnemonic for i in instructions(xlen)]
    assert len(mnemonics) == len(set(mnemonics))


@pytest.mark.parametrize("xlen", [32, 64])
def test_no_word_matches_two_instructions(xlen):
    table = instructions(xlen)
    for n, a in enumerate(table):
        for b in table[n + 1:]:
            # some bit is fixed in both and differs
            assert (a.match ^ b.match) & a.mask & b.mask, (a.mnemonic, b.mnemonic)


def test_every_format_is_used():
    used = {i.format for i in INSTRUCTIONS}
    declared = {f for f in vars(formats).values()
                if isinstance(f, type) and issubclass(f, Format) and f is not Format}
    assert used == declared


def test_register_tables():
    assert len(X_NAMES) == len(set(X_NAMES)) == 32
    assert len(F_NAMES) == len(set(F_NAMES)) == 32
    assert len(CSRS) == len(set(CSRS.values())) == 17


# ------------------------------------------------ invalid descriptions fail


def test_format_with_gap():
    with pytest.raises(ValueError, match="cover"):
        class Gap(Format):
            a: Annotated[Fixed, Bits(31, 1)]


def test_format_with_overlap():
    with pytest.raises(ValueError, match="overlap"):
        class Overlap(Format):
            a: Annotated[Fixed, Bits(31, 0)]
            b: Annotated[Fixed, Bits(0, 0)]


def test_format_with_gap_in_value_bits():
    with pytest.raises(ValueError, match="contiguous"):
        class Holes(Format):
            a: Annotated[SImm, Bits(31, 16, at=0), Bits(15, 0, at=17)]


def test_format_with_repeated_value_bits():
    with pytest.raises(ValueError, match="repeat"):
        class Repeat(Format):
            a: Annotated[SImm, Bits(31, 16, at=0), Bits(15, 0, at=15)]


def test_format_field_without_bits():
    with pytest.raises(ValueError, match="Annotated"):
        class NoBits(Format):
            a: Reg


@pytest.mark.parametrize("syntax, fixed, fp, message", [
    ("rd, rs1, rs9", {"funct7": 0, "funct3": 0, "opcode": 0}, "", "not a field"),
    ("rd, rs1", {"funct7": 0, "funct3": 0, "opcode": 0}, "", "neither"),
    ("rd, rs1, rs2", {"funct7": 128, "funct3": 0, "opcode": 0}, "", "out of range"),
    ("rd, rs1, rs2", {"funct7": 0, "funct3": 0, "opcode": 0, "rd": 0}, "", "both"),
    ("rd, rs1, rs2", {"funct7": 0, "funct3": 0, "opcode": 0}, "rs3", "fp"),
])
def test_invalid_instruction(syntax, fixed, fp, message):
    with pytest.raises(ValueError, match=message):
        Instr("bad", formats.R, syntax, fixed, "I", fp=fp)
