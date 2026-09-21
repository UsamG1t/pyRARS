"""Encoding of instructions, checked against the RISC-V ISA manual.

Expected words are built by the format formulas below, written directly from
the RV32I "Base Instruction Formats" / "Immediate Encoding Variants" figures,
independently of pyrars.isa.formats.
"""

import pytest

from pyrars.isa.codec import decode, encode
from pyrars.isa.instructions import find, instructions


def r(funct7, rs2, rs1, funct3, rd, opcode):
    return funct7 << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def r4(rs3, funct2, rs2, rs1, rm, rd, opcode):
    return rs3 << 27 | funct2 << 25 | rs2 << 20 | rs1 << 15 | rm << 12 | rd << 7 | opcode


def i(imm, rs1, funct3, rd, opcode):
    return (imm & 0xFFF) << 20 | rs1 << 15 | funct3 << 12 | rd << 7 | opcode


def s(imm, rs2, rs1, funct3, opcode):
    return ((imm >> 5) & 0x7F) << 25 | rs2 << 20 | rs1 << 15 | funct3 << 12 | (imm & 0x1F) << 7 | opcode


def b(imm, rs2, rs1, funct3, opcode=0b1100011):
    return (((imm >> 12) & 1) << 31 | ((imm >> 5) & 0x3F) << 25 | rs2 << 20 | rs1 << 15
            | funct3 << 12 | ((imm >> 1) & 0xF) << 8 | ((imm >> 11) & 1) << 7 | opcode)


def u(imm20, rd, opcode):
    return imm20 << 12 | rd << 7 | opcode


def j(imm, rd, opcode=0b1101111):
    return (((imm >> 20) & 1) << 31 | ((imm >> 1) & 0x3FF) << 21 | ((imm >> 11) & 1) << 20
            | ((imm >> 12) & 0xFF) << 12 | rd << 7 | opcode)


CASES = [
    # mnemonic, xlen, operands, expected word
    ("add", 32, dict(rd=5, rs1=6, rs2=7), r(0, 7, 6, 0b000, 5, 0b0110011)),
    ("sub", 32, dict(rd=31, rs1=0, rs2=31), r(0b0100000, 31, 0, 0b000, 31, 0b0110011)),
    ("addi", 32, dict(rd=1, rs1=2, imm=-2048), i(-2048, 2, 0b000, 1, 0b0010011)),
    ("addi", 32, dict(rd=1, rs1=2, imm=2047), i(2047, 2, 0b000, 1, 0b0010011)),
    ("jalr", 32, dict(rd=0, rs1=1, imm=0), 0x00008067),  # ret
    ("lw", 32, dict(rd=10, rs1=2, imm=-4), i(-4, 2, 0b010, 10, 0b0000011)),
    ("sw", 32, dict(rs2=31, rs1=2, imm=-2048), s(-2048, 31, 2, 0b010, 0b0100011)),
    ("sb", 32, dict(rs2=1, rs1=3, imm=2047), s(2047, 1, 3, 0b000, 0b0100011)),
    ("beq", 32, dict(rs1=1, rs2=2, imm=-4096), b(-4096, 2, 1, 0b000)),
    ("bne", 32, dict(rs1=1, rs2=2, imm=4094), b(4094, 2, 1, 0b001)),
    ("bgeu", 32, dict(rs1=31, rs2=30, imm=-2), b(-2, 30, 31, 0b111)),
    ("blt", 32, dict(rs1=0, rs2=0, imm=2048), b(2048, 0, 0, 0b100)),
    ("jal", 32, dict(rd=0, imm=0), 0x0000006F),
    ("jal", 32, dict(rd=1, imm=-(1 << 20)), j(-(1 << 20), 1)),
    ("jal", 32, dict(rd=1, imm=(1 << 20) - 2), j((1 << 20) - 2, 1)),
    ("jal", 32, dict(rd=1, imm=2048), j(2048, 1)),
    ("lui", 32, dict(rd=5, imm=0xFFFFF), u(0xFFFFF, 5, 0b0110111)),
    ("auipc", 32, dict(rd=10, imm=0x0FC10), u(0x0FC10, 10, 0b0010111)),
    ("slli", 32, dict(rd=1, rs1=2, shamt=31), r(0, 31, 2, 0b001, 1, 0b0010011)),
    ("srai", 32, dict(rd=1, rs1=2, shamt=1), r(0b0100000, 1, 2, 0b101, 1, 0b0010011)),
    ("slli", 64, dict(rd=1, rs1=2, shamt=63), 0b000000 << 26 | 63 << 20 | 2 << 15 | 0b001 << 12 | 1 << 7 | 0b0010011),
    ("srai", 64, dict(rd=1, rs1=2, shamt=63), 0b010000 << 26 | 63 << 20 | 2 << 15 | 0b101 << 12 | 1 << 7 | 0b0010011),
    ("sraiw", 64, dict(rd=1, rs1=2, shamt=31), r(0b0100000, 31, 2, 0b101, 1, 0b0011011)),
    ("ld", 64, dict(rd=1, rs1=2, imm=8), i(8, 2, 0b011, 1, 0b0000011)),
    ("csrrw", 32, dict(rd=1, csr=0xC82, rs1=31), i(0xC82, 31, 0b001, 1, 0b1110011)),
    ("csrrwi", 32, dict(rd=1, csr=0x003, uimm=31), i(0x003, 31, 0b101, 1, 0b1110011)),
    ("fence", 32, dict(pred=15, succ=1), 15 << 24 | 1 << 20 | 0b0001111),
    ("fence.i", 32, {}, 0x0000100F),
    ("ecall", 32, {}, 0x00000073),
    ("ebreak", 32, {}, 0x00100073),
    ("uret", 32, {}, 0x00200073),
    ("wfi", 32, {}, 0x10500073),
    ("mulhsu", 32, dict(rd=3, rs1=4, rs2=5), r(1, 5, 4, 0b010, 3, 0b0110011)),
    ("remuw", 64, dict(rd=3, rs1=4, rs2=5), r(1, 5, 4, 0b111, 3, 0b0111011)),
    ("flw", 32, dict(rd=1, rs1=2, imm=-100), i(-100, 2, 0b010, 1, 0b0000111)),
    ("fsd", 32, dict(rs2=1, rs1=2, imm=-100), s(-100, 1, 2, 0b011, 0b0100111)),
    ("fadd.s", 32, dict(rd=1, rs1=2, rs2=3, rm=0b111), r(0b0000000, 3, 2, 0b111, 1, 0b1010011)),
    ("fsqrt.d", 32, dict(rd=1, rs1=2, rm=0b001), r(0b0101101, 0, 2, 0b001, 1, 0b1010011)),
    ("fmadd.d", 32, dict(rd=1, rs1=2, rs2=3, rs3=31, rm=0b100), r4(31, 0b01, 3, 2, 0b100, 1, 0b1000011)),
    ("fnmadd.s", 32, dict(rd=1, rs1=2, rs2=3, rs3=4, rm=0), r4(4, 0b00, 3, 2, 0, 1, 0b1001111)),
    ("fcvt.d.w", 32, dict(rd=1, rs1=2, rm=0b001), r(0b1101001, 0, 2, 0b001, 1, 0b1010011)),
    ("fcvt.s.d", 32, dict(rd=1, rs1=2, rm=0b111), r(0b0100000, 1, 2, 0b111, 1, 0b1010011)),
    ("fcvt.lu.s", 64, dict(rd=1, rs1=2, rm=0b000), r(0b1100000, 3, 2, 0b000, 1, 0b1010011)),
    ("fmv.x.w", 32, dict(rd=1, rs1=2), r(0b1110000, 0, 2, 0b000, 1, 0b1010011)),
    ("fclass.d", 32, dict(rd=1, rs1=2), r(0b1110001, 0, 2, 0b001, 1, 0b1010011)),
    ("feq.d", 32, dict(rd=1, rs1=2, rs2=3), r(0b1010001, 3, 2, 0b010, 1, 0b1010011)),
]


@pytest.mark.parametrize("mnemonic, xlen, operands, expected", CASES)
def test_encode(mnemonic, xlen, operands, expected):
    assert encode(find(mnemonic, xlen), operands) == expected


@pytest.mark.parametrize("mnemonic, xlen, operands, expected", CASES)
def test_decode(mnemonic, xlen, operands, expected):
    decoded = decode(expected, xlen)
    assert decoded.instr.mnemonic == mnemonic
    assert decoded.operands == operands


@pytest.mark.parametrize("mnemonic, xlen, operands", [
    ("addi", 32, dict(rd=1, rs1=2, imm=2048)),
    ("addi", 32, dict(rd=1, rs1=2, imm=-2049)),
    ("addi", 32, dict(rd=32, rs1=2, imm=0)),
    ("addi", 32, dict(rd=-1, rs1=2, imm=0)),
    ("beq", 32, dict(rs1=1, rs2=2, imm=4096)),
    ("beq", 32, dict(rs1=1, rs2=2, imm=-4098)),
    ("beq", 32, dict(rs1=1, rs2=2, imm=3)),
    ("jal", 32, dict(rd=1, imm=1 << 20)),
    ("jal", 32, dict(rd=1, imm=1)),
    ("lui", 32, dict(rd=1, imm=-1)),
    ("lui", 32, dict(rd=1, imm=1 << 20)),
    ("slli", 32, dict(rd=1, rs1=2, shamt=32)),
    ("slli", 64, dict(rd=1, rs1=2, shamt=64)),
    ("fence", 32, dict(pred=16, succ=0)),
    ("csrrwi", 32, dict(rd=1, csr=4096, uimm=0)),
    ("fadd.s", 32, dict(rd=1, rs1=2, rs2=3, rm=8)),
    ("add", 32, dict(rd=1, rs1=2)),
    ("add", 32, dict(rd=1, rs1=2, rs2=3, imm=0)),
])
def test_encode_rejects(mnemonic, xlen, operands):
    with pytest.raises(ValueError):
        encode(find(mnemonic, xlen), operands)


def sample_operands(instr, pick):
    """Operand values of instr: pick=min uses the smallest, pick=max the largest ones."""
    values = {}
    for n, name in enumerate(instr.operands):
        field = instr.format.fields[name]
        if field.kind.signed:
            low, high = -(1 << (field.width - 1)), (1 << (field.width - 1)) - (1 << field.low)
        else:
            low, high = n, (1 << field.width) - 1 - n  # n: distinct values per operand
        values[name] = low if pick is min else high
    return values


@pytest.mark.parametrize("xlen", [32, 64])
@pytest.mark.parametrize("pick", [min, max])
def test_decode_inverts_encode_for_every_instruction(xlen, pick):
    for instr in instructions(xlen):
        operands = sample_operands(instr, pick)
        decoded = decode(encode(instr, operands), xlen)
        assert (decoded.instr, decoded.operands) == (instr, operands), instr.mnemonic


def test_decode_unknown_words():
    assert decode(0x00000000, 32) is None  # all zeros is an illegal instruction
    assert decode(0xFFFFFFFF, 32) is None
    ld = encode(find("ld", 64), dict(rd=1, rs1=2, imm=0))
    assert decode(ld, 32) is None  # RV64-only
    slli_63 = encode(find("slli", 64), dict(rd=1, rs1=2, shamt=63))
    assert decode(slli_63, 32) is None  # shamt[5] must be 0 in RV32
