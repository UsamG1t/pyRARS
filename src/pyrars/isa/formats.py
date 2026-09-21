"""Instruction formats (bit layouts).

Source: RISC-V ISA manual, Volume I, v20260120 - RV32I "Base Instruction Formats"
and "Immediate Encoding Variants"; R4 and rounding mode fields from the F
extension; shift, CSR and fence layouts from the RV32I/RV64I and Zicsr chapters.

A field's register class (integer or floating point) is not part of the format:
it is given per instruction (Instr.fp).
"""

from typing import Annotated

from pyrars.isa.spec import Bits, Csr, Fixed, Format, Offset, Reg, RoundingMode, SImm, UImm


class R(Format):
    funct7: Annotated[Fixed, Bits(31, 25)]
    rs2:    Annotated[Reg,   Bits(24, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class RRm(Format):
    """R with a rounding mode in place of funct3 (floating point)."""

    funct7: Annotated[Fixed,        Bits(31, 25)]
    rs2:    Annotated[Reg,          Bits(24, 20)]
    rs1:    Annotated[Reg,          Bits(19, 15)]
    rm:     Annotated[RoundingMode, Bits(14, 12)]
    rd:     Annotated[Reg,          Bits(11, 7)]
    opcode: Annotated[Fixed,        Bits(6, 0)]


class R4(Format):
    """Fused multiply-add: three sources and a rounding mode."""

    rs3:    Annotated[Reg,          Bits(31, 27)]
    funct2: Annotated[Fixed,        Bits(26, 25)]
    rs2:    Annotated[Reg,          Bits(24, 20)]
    rs1:    Annotated[Reg,          Bits(19, 15)]
    rm:     Annotated[RoundingMode, Bits(14, 12)]
    rd:     Annotated[Reg,          Bits(11, 7)]
    opcode: Annotated[Fixed,        Bits(6, 0)]


class I(Format):
    imm:    Annotated[SImm,  Bits(31, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class Shift5(Format):
    """Shift by immediate, 5-bit shift amount (RV32I, RV64I *W)."""

    funct7: Annotated[Fixed, Bits(31, 25)]
    shamt:  Annotated[UImm,  Bits(24, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class Shift6(Format):
    """Shift by immediate, 6-bit shift amount (RV64I)."""

    funct6: Annotated[Fixed, Bits(31, 26)]
    shamt:  Annotated[UImm,  Bits(25, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class S(Format):
    imm:    Annotated[SImm,  Bits(31, 25, at=5), Bits(11, 7, at=0)]
    rs2:    Annotated[Reg,   Bits(24, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class B(Format):
    imm:    Annotated[Offset, Bits(31, 31, at=12), Bits(30, 25, at=5),
                              Bits(11, 8, at=1), Bits(7, 7, at=11)]
    rs2:    Annotated[Reg,    Bits(24, 20)]
    rs1:    Annotated[Reg,    Bits(19, 15)]
    funct3: Annotated[Fixed,  Bits(14, 12)]
    opcode: Annotated[Fixed,  Bits(6, 0)]


class U(Format):
    """imm is the upper 20 bits as a number: lui x1, 0x12345 puts 0x12345000."""

    imm:    Annotated[UImm,  Bits(31, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class J(Format):
    imm:    Annotated[Offset, Bits(31, 31, at=20), Bits(30, 21, at=1),
                              Bits(20, 20, at=11), Bits(19, 12, at=12)]
    rd:     Annotated[Reg,    Bits(11, 7)]
    opcode: Annotated[Fixed,  Bits(6, 0)]


class CsrReg(Format):
    csr:    Annotated[Csr,   Bits(31, 20)]
    rs1:    Annotated[Reg,   Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class CsrImm(Format):
    """CSR instruction with a 5-bit unsigned immediate in place of rs1."""

    csr:    Annotated[Csr,   Bits(31, 20)]
    uimm:   Annotated[UImm,  Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Reg,   Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]


class Fence(Format):
    fm:     Annotated[Fixed, Bits(31, 28)]
    pred:   Annotated[UImm,  Bits(27, 24)]
    succ:   Annotated[UImm,  Bits(23, 20)]
    rs1:    Annotated[Fixed, Bits(19, 15)]
    funct3: Annotated[Fixed, Bits(14, 12)]
    rd:     Annotated[Fixed, Bits(11, 7)]
    opcode: Annotated[Fixed, Bits(6, 0)]
