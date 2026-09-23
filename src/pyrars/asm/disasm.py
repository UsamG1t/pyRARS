"""Disassembler: a machine word back to the text of a basic instruction.

    >>> text(0x00128293)
    'addi x5,x5,1'
    >>> text(0x00128293, abi=True)
    'addi t0,t0,1'
    >>> text(0x00000000) is None
    True

A word that is no instruction of our set gives None: the caller decides what to
show (the listing leaves the column empty, a memory view shows the word itself,
the simulator raises an illegal instruction). Such words are real: `.insn` with
a value of its own, a program that writes into its text segment, or memory that
was never written.

How a value is written (user decision 2026-09-23): registers by their number
(`x5`, `f2`) or, with abi=True, by their name of the calling convention (`t0`,
`ft2`); an immediate in signed decimal; the upper immediate of `lui` and
`auipc` in hexadecimal, because it is a bit pattern; a branch or jump target as
its signed distance, as RARS writes it. Pseudo-instructions are not recognized
back (`addi x0,x0,0` stays `addi`), like in RARS.
"""

import re

from pyrars.isa.codec import decode
from pyrars.isa.registers import CSRS, F_NAMES, ROUNDING_MODES, X_NAMES
from pyrars.isa.spec import Csr, Instr, Offset, Reg, RoundingMode, UImm

_ROUNDING_NAMES = {value: name for name, value in ROUNDING_MODES.items()}
_CSR_NAMES = {number: name for name, number in CSRS.items()}
_UPPER = ("lui", "auipc")  # their immediate is the upper 20 bits of a value


def text(word: int, xlen: int = 32, abi: bool = False) -> str | None:
    """Text of an instruction word, or None if it is not an instruction."""
    decoded = decode(word, xlen)
    if decoded is None:
        return None
    operands = ",".join(_group(decoded.instr, group, decoded.operands, abi)
                        for group in decoded.instr.syntax.split(",") if group.strip())
    return f"{decoded.instr.mnemonic} {operands}".rstrip()


def _group(instr: Instr, group: str, values: dict[str, int], abi: bool) -> str:
    """One operand of the syntax; "imm(rs1)" is one operand with two values."""
    names = re.findall(r"[a-z][a-z0-9]*", group)
    if len(names) == 2:  # the memory form
        return f"{_value(instr, names[0], values, abi)}({_value(instr, names[1], values, abi)})"
    return _value(instr, names[0], values, abi)


def _value(instr: Instr, name: str, values: dict[str, int], abi: bool) -> str:
    kind = instr.format.fields[name].kind
    value = values[name]
    if kind is Reg:
        return _register(value, instr.is_fp(name), abi)
    if kind is RoundingMode:
        return _ROUNDING_NAMES.get(value, str(value))
    if kind is Csr:
        return _CSR_NAMES.get(value, str(value)) if abi else str(value)
    if kind is UImm and instr.mnemonic in _UPPER:
        return f"0x{value:05x}"
    if kind is Offset:
        return str(value)
    return str(value)


def _register(number: int, floating: bool, abi: bool) -> str:
    if not abi:
        return f"{'f' if floating else 'x'}{number}"
    return F_NAMES[number] if floating else X_NAMES[number]
