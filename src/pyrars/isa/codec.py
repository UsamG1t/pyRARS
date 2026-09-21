"""Instruction word encoding and decoding."""

from collections.abc import Mapping
from dataclasses import dataclass

from pyrars.isa.instructions import instructions
from pyrars.isa.spec import Instr


def encode(instr: Instr, operands: Mapping[str, int]) -> int:
    """Machine word of instr with operand values given by field name.

    Raises ValueError if an operand is missing, unknown or does not fit its field.
    """
    if set(operands) != set(instr.operands):
        raise ValueError(f"{instr.mnemonic}: operands {sorted(operands)}, expected {sorted(instr.operands)}")
    word = instr.match
    for name, value in operands.items():
        field = instr.format.fields[name]
        field.check(value)
        word |= field.put(value)
    return word


@dataclass(frozen=True)
class Decoded:
    instr: Instr
    operands: dict[str, int]


def decode(word: int, xlen: int) -> Decoded | None:
    """The instruction encoded by word in RV32 or RV64, or None if there is none."""
    for instr in instructions(xlen):
        if word & instr.mask == instr.match:
            fields = instr.format.fields
            return Decoded(instr, {name: fields[name].get(word) for name in instr.operands})
    return None
