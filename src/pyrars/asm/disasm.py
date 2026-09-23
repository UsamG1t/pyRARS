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

from pyrars.asm import pseudo
from pyrars.isa.codec import decode
from pyrars.isa.registers import CSRS, F_NAMES, ROUNDING_MODES, X_NAMES
from pyrars.isa.spec import Csr, Instr, Offset, Reg, RoundingMode, UImm

_ROUNDING_NAMES = {value: name for name, value in ROUNDING_MODES.items()}
_CSR_NAMES = {number: name for name, number in CSRS.items()}
_UPPER = ("lui", "auipc")  # their immediate is the upper 20 bits of a value


def text(word: int, xlen: int = 32, abi: bool = False, pseudos: bool = False) -> str | None:
    """Text of an instruction word, or None if it is not an instruction.

    pseudos=True names the pseudo-instruction a word stands for when it is one
    word long (`addi x0,x0,0` becomes `nop`); a pseudo-instruction of several
    words stays what it is, as in objdump.
    """
    decoded = decode(word, xlen)
    if decoded is None:
        return None
    if pseudos:
        written = _as_pseudo(decoded, xlen, abi)
        if written is not None:
            return written
    operands = ",".join(_group(decoded.instr, group, decoded.operands, abi)
                        for group in decoded.instr.syntax.split(",") if group.strip())
    return f"{decoded.instr.mnemonic} {operands}".rstrip()


# ------------------------------------------------- naming a pseudo-instruction

# what a template may write into a field and still be read back
_READABLE = (pseudo.Const, pseudo.Reg, pseudo.Imm, pseudo.Lo, pseudo.Target)


def _as_pseudo(decoded, xlen: int, abi: bool) -> str | None:
    """The pseudo-instruction this single word stands for, if there is one.

    The row with the fewest operands wins, because it says the most about the
    word: `jalr x0,x1,0` is `ret`, not `jr x1`.
    """
    found = []
    for row in pseudo.TABLE:
        if row.alias or len(row.templates) != 1 or not row.exists_in(xlen):
            continue
        template = row.templates[0]
        if template.mnemonic != decoded.instr.mnemonic:
            continue
        values = _source_values(decoded, template)
        if values is None or len(values) != len(row.kinds):
            continue
        found.append((len(row.kinds), row, values))
    if not found:
        return None
    _, row, values = min(found, key=lambda item: item[0])
    return _write_pseudo(row, values, abi)


def _source_values(decoded, template) -> dict[int, int] | None:
    """Operands of the pseudo-instruction that give these fields, or None."""
    values: dict[int, int] = {}
    for name, part in zip(decoded.instr.operands, template.parts):
        value = decoded.operands[name]
        if not isinstance(part, _READABLE):
            return None
        if isinstance(part, pseudo.Const):
            if value != part.value:
                return None
        elif values.setdefault(part.n, value) != value:  # one operand, two fields
            return None
    return values


def _write_pseudo(row, values: dict[int, int], abi: bool) -> str:
    operands = []
    for number, kind in enumerate(row.kinds, start=1):
        value = values[number]
        if kind in ("rd", "rs", "rt"):
            operands.append(_register(value, False, abi))
        elif kind in ("fd", "fs", "ft"):
            operands.append(_register(value, True, abi))
        elif kind == "csr":
            operands.append(_CSR_NAMES.get(value, str(value)) if abi else str(value))
        else:
            operands.append(str(value))
    return f"{row.mnemonic} {','.join(operands)}".rstrip()


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
