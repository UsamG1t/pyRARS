"""Basic instructions of the RARS dialect: one Instr per machine instruction.

Encodings: RISC-V ISA manual, Volume I, v20260120 (instruction chapters and
"RV32/64G Instruction Set Listings"); uret and wfi: Volume II.
Syntax and mnemonics: RARS 1.6 (src/rars/riscv/instructions/*.java), e.g.
- floating point arithmetic and conversions take an explicit rounding mode
  ("fadd.s f1, f2, f3, dyn"); the short forms are pseudo-instructions;
- jalr is "jalr rd, rs1, imm"; fence takes two numbers "fence pred, succ";
Set: exactly the RARS basic instructions, 109 in RV32 and 136 in RV64.
Deviation from RARS: fmv.x.w / fmv.w.x have their F v2.2 names; RARS uses the
older names fmv.x.s / fmv.s.x, which the ISA manual keeps as aliases.
"""

from pyrars.isa.formats import B, CsrImm, CsrReg, Fence, I, J, R, R4, RRm, S, Shift5, Shift6, U
from pyrars.isa.spec import Instr

# Major opcodes (bits 6..0).
LOAD = 0b0000011
LOAD_FP = 0b0000111
MISC_MEM = 0b0001111
OP_IMM = 0b0010011
AUIPC = 0b0010111
OP_IMM_32 = 0b0011011
STORE = 0b0100011
STORE_FP = 0b0100111
OP = 0b0110011
LUI = 0b0110111
OP_32 = 0b0111011
MADD = 0b1000011
MSUB = 0b1000111
NMSUB = 0b1001011
NMADD = 0b1001111
OP_FP = 0b1010011
BRANCH = 0b1100011
JALR = 0b1100111
JAL = 0b1101111
SYSTEM = 0b1110011


# Fixed fields of an instruction.


def f7_f3(funct7, funct3, opcode=OP):
    return {"funct7": funct7, "funct3": funct3, "opcode": opcode}


def f3(funct3, opcode):
    return {"funct3": funct3, "opcode": opcode}


def fp_op(funct7, **fields):
    return {"funct7": funct7, "opcode": OP_FP, **fields}


def system(imm):
    return {"imm": imm, "rs1": 0, "funct3": 0, "rd": 0, "opcode": SYSTEM}


INSTRUCTIONS = (
    # ---------------------------------------------------------------- RV32I
    Instr("lui",    U, "rd, imm", {"opcode": LUI}, "I"),
    Instr("auipc",  U, "rd, imm", {"opcode": AUIPC}, "I"),
    Instr("jal",    J, "rd, imm", {"opcode": JAL}, "I"),
    Instr("jalr",   I, "rd, rs1, imm", f3(0b000, JALR), "I"),

    Instr("beq",  B, "rs1, rs2, imm", f3(0b000, BRANCH), "I"),
    Instr("bne",  B, "rs1, rs2, imm", f3(0b001, BRANCH), "I"),
    Instr("blt",  B, "rs1, rs2, imm", f3(0b100, BRANCH), "I"),
    Instr("bge",  B, "rs1, rs2, imm", f3(0b101, BRANCH), "I"),
    Instr("bltu", B, "rs1, rs2, imm", f3(0b110, BRANCH), "I"),
    Instr("bgeu", B, "rs1, rs2, imm", f3(0b111, BRANCH), "I"),

    Instr("lb",  I, "rd, imm(rs1)", f3(0b000, LOAD), "I"),
    Instr("lh",  I, "rd, imm(rs1)", f3(0b001, LOAD), "I"),
    Instr("lw",  I, "rd, imm(rs1)", f3(0b010, LOAD), "I"),
    Instr("lbu", I, "rd, imm(rs1)", f3(0b100, LOAD), "I"),
    Instr("lhu", I, "rd, imm(rs1)", f3(0b101, LOAD), "I"),

    Instr("sb", S, "rs2, imm(rs1)", f3(0b000, STORE), "I"),
    Instr("sh", S, "rs2, imm(rs1)", f3(0b001, STORE), "I"),
    Instr("sw", S, "rs2, imm(rs1)", f3(0b010, STORE), "I"),

    Instr("addi",  I, "rd, rs1, imm", f3(0b000, OP_IMM), "I"),
    Instr("slti",  I, "rd, rs1, imm", f3(0b010, OP_IMM), "I"),
    Instr("sltiu", I, "rd, rs1, imm", f3(0b011, OP_IMM), "I"),
    Instr("xori",  I, "rd, rs1, imm", f3(0b100, OP_IMM), "I"),
    Instr("ori",   I, "rd, rs1, imm", f3(0b110, OP_IMM), "I"),
    Instr("andi",  I, "rd, rs1, imm", f3(0b111, OP_IMM), "I"),

    Instr("slli", Shift5, "rd, rs1, shamt", f7_f3(0b0000000, 0b001, OP_IMM), "I", xlen=32),
    Instr("srli", Shift5, "rd, rs1, shamt", f7_f3(0b0000000, 0b101, OP_IMM), "I", xlen=32),
    Instr("srai", Shift5, "rd, rs1, shamt", f7_f3(0b0100000, 0b101, OP_IMM), "I", xlen=32),

    Instr("add",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b000), "I"),
    Instr("sub",  R, "rd, rs1, rs2", f7_f3(0b0100000, 0b000), "I"),
    Instr("sll",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b001), "I"),
    Instr("slt",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b010), "I"),
    Instr("sltu", R, "rd, rs1, rs2", f7_f3(0b0000000, 0b011), "I"),
    Instr("xor",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b100), "I"),
    Instr("srl",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b101), "I"),
    Instr("sra",  R, "rd, rs1, rs2", f7_f3(0b0100000, 0b101), "I"),
    Instr("or",   R, "rd, rs1, rs2", f7_f3(0b0000000, 0b110), "I"),
    Instr("and",  R, "rd, rs1, rs2", f7_f3(0b0000000, 0b111), "I"),

    Instr("fence", Fence, "pred, succ",
          {"fm": 0, "rs1": 0, "funct3": 0b000, "rd": 0, "opcode": MISC_MEM}, "I"),
    Instr("ecall",  I, "", system(0x000), "I"),
    Instr("ebreak", I, "", system(0x001), "I"),

    # ---------------------------------------------------------------- RV64I
    Instr("lwu", I, "rd, imm(rs1)", f3(0b110, LOAD), "I", xlen=64),
    Instr("ld",  I, "rd, imm(rs1)", f3(0b011, LOAD), "I", xlen=64),
    Instr("sd",  S, "rs2, imm(rs1)", f3(0b011, STORE), "I", xlen=64),

    Instr("slli", Shift6, "rd, rs1, shamt", {"funct6": 0b000000, "funct3": 0b001, "opcode": OP_IMM}, "I", xlen=64),
    Instr("srli", Shift6, "rd, rs1, shamt", {"funct6": 0b000000, "funct3": 0b101, "opcode": OP_IMM}, "I", xlen=64),
    Instr("srai", Shift6, "rd, rs1, shamt", {"funct6": 0b010000, "funct3": 0b101, "opcode": OP_IMM}, "I", xlen=64),

    Instr("addiw", I,      "rd, rs1, imm",   f3(0b000, OP_IMM_32), "I", xlen=64),
    Instr("slliw", Shift5, "rd, rs1, shamt", f7_f3(0b0000000, 0b001, OP_IMM_32), "I", xlen=64),
    Instr("srliw", Shift5, "rd, rs1, shamt", f7_f3(0b0000000, 0b101, OP_IMM_32), "I", xlen=64),
    Instr("sraiw", Shift5, "rd, rs1, shamt", f7_f3(0b0100000, 0b101, OP_IMM_32), "I", xlen=64),

    Instr("addw", R, "rd, rs1, rs2", f7_f3(0b0000000, 0b000, OP_32), "I", xlen=64),
    Instr("subw", R, "rd, rs1, rs2", f7_f3(0b0100000, 0b000, OP_32), "I", xlen=64),
    Instr("sllw", R, "rd, rs1, rs2", f7_f3(0b0000000, 0b001, OP_32), "I", xlen=64),
    Instr("srlw", R, "rd, rs1, rs2", f7_f3(0b0000000, 0b101, OP_32), "I", xlen=64),
    Instr("sraw", R, "rd, rs1, rs2", f7_f3(0b0100000, 0b101, OP_32), "I", xlen=64),

    # ------------------------------------------------------ Zifencei, Zicsr
    Instr("fence.i", I, "", {"imm": 0, "rs1": 0, "funct3": 0b001, "rd": 0, "opcode": MISC_MEM}, "Zifencei"),

    Instr("csrrw",  CsrReg, "rd, csr, rs1",  f3(0b001, SYSTEM), "Zicsr"),
    Instr("csrrs",  CsrReg, "rd, csr, rs1",  f3(0b010, SYSTEM), "Zicsr"),
    Instr("csrrc",  CsrReg, "rd, csr, rs1",  f3(0b011, SYSTEM), "Zicsr"),
    Instr("csrrwi", CsrImm, "rd, csr, uimm", f3(0b101, SYSTEM), "Zicsr"),
    Instr("csrrsi", CsrImm, "rd, csr, uimm", f3(0b110, SYSTEM), "Zicsr"),
    Instr("csrrci", CsrImm, "rd, csr, uimm", f3(0b111, SYSTEM), "Zicsr"),

    # --------------------------------------------------- privileged (N, wfi)
    Instr("uret", I, "", system(0x002), "N"),
    Instr("wfi",  I, "", system(0x105), "Priv"),

    # -------------------------------------------------------------------- M
    Instr("mul",    R, "rd, rs1, rs2", f7_f3(0b0000001, 0b000), "M"),
    Instr("mulh",   R, "rd, rs1, rs2", f7_f3(0b0000001, 0b001), "M"),
    Instr("mulhsu", R, "rd, rs1, rs2", f7_f3(0b0000001, 0b010), "M"),
    Instr("mulhu",  R, "rd, rs1, rs2", f7_f3(0b0000001, 0b011), "M"),
    Instr("div",    R, "rd, rs1, rs2", f7_f3(0b0000001, 0b100), "M"),
    Instr("divu",   R, "rd, rs1, rs2", f7_f3(0b0000001, 0b101), "M"),
    Instr("rem",    R, "rd, rs1, rs2", f7_f3(0b0000001, 0b110), "M"),
    Instr("remu",   R, "rd, rs1, rs2", f7_f3(0b0000001, 0b111), "M"),

    Instr("mulw",  R, "rd, rs1, rs2", f7_f3(0b0000001, 0b000, OP_32), "M", xlen=64),
    Instr("divw",  R, "rd, rs1, rs2", f7_f3(0b0000001, 0b100, OP_32), "M", xlen=64),
    Instr("divuw", R, "rd, rs1, rs2", f7_f3(0b0000001, 0b101, OP_32), "M", xlen=64),
    Instr("remw",  R, "rd, rs1, rs2", f7_f3(0b0000001, 0b110, OP_32), "M", xlen=64),
    Instr("remuw", R, "rd, rs1, rs2", f7_f3(0b0000001, 0b111, OP_32), "M", xlen=64),

    # -------------------------------------------------------------------- F
    Instr("flw", I, "rd, imm(rs1)",  f3(0b010, LOAD_FP), "F", fp="rd"),
    Instr("fsw", S, "rs2, imm(rs1)", f3(0b010, STORE_FP), "F", fp="rs2"),

    Instr("fmadd.s",  R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b00, "opcode": MADD},  "F", fp="rd rs1 rs2 rs3"),
    Instr("fmsub.s",  R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b00, "opcode": MSUB},  "F", fp="rd rs1 rs2 rs3"),
    Instr("fnmsub.s", R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b00, "opcode": NMSUB}, "F", fp="rd rs1 rs2 rs3"),
    Instr("fnmadd.s", R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b00, "opcode": NMADD}, "F", fp="rd rs1 rs2 rs3"),

    Instr("fadd.s",  RRm, "rd, rs1, rs2, rm", fp_op(0b0000000), "F", fp="rd rs1 rs2"),
    Instr("fsub.s",  RRm, "rd, rs1, rs2, rm", fp_op(0b0000100), "F", fp="rd rs1 rs2"),
    Instr("fmul.s",  RRm, "rd, rs1, rs2, rm", fp_op(0b0001000), "F", fp="rd rs1 rs2"),
    Instr("fdiv.s",  RRm, "rd, rs1, rs2, rm", fp_op(0b0001100), "F", fp="rd rs1 rs2"),
    Instr("fsqrt.s", RRm, "rd, rs1, rm",      fp_op(0b0101100, rs2=0), "F", fp="rd rs1"),

    Instr("fsgnj.s",  R, "rd, rs1, rs2", fp_op(0b0010000, funct3=0b000), "F", fp="rd rs1 rs2"),
    Instr("fsgnjn.s", R, "rd, rs1, rs2", fp_op(0b0010000, funct3=0b001), "F", fp="rd rs1 rs2"),
    Instr("fsgnjx.s", R, "rd, rs1, rs2", fp_op(0b0010000, funct3=0b010), "F", fp="rd rs1 rs2"),
    Instr("fmin.s",   R, "rd, rs1, rs2", fp_op(0b0010100, funct3=0b000), "F", fp="rd rs1 rs2"),
    Instr("fmax.s",   R, "rd, rs1, rs2", fp_op(0b0010100, funct3=0b001), "F", fp="rd rs1 rs2"),

    Instr("fcvt.w.s",  RRm, "rd, rs1, rm", fp_op(0b1100000, rs2=0b00000), "F", fp="rs1"),
    Instr("fcvt.wu.s", RRm, "rd, rs1, rm", fp_op(0b1100000, rs2=0b00001), "F", fp="rs1"),
    Instr("fcvt.s.w",  RRm, "rd, rs1, rm", fp_op(0b1101000, rs2=0b00000), "F", fp="rd"),
    Instr("fcvt.s.wu", RRm, "rd, rs1, rm", fp_op(0b1101000, rs2=0b00001), "F", fp="rd"),

    Instr("fmv.x.w",  R, "rd, rs1", fp_op(0b1110000, rs2=0, funct3=0b000), "F", fp="rs1"),
    Instr("fclass.s", R, "rd, rs1", fp_op(0b1110000, rs2=0, funct3=0b001), "F", fp="rs1"),
    Instr("fmv.w.x",  R, "rd, rs1", fp_op(0b1111000, rs2=0, funct3=0b000), "F", fp="rd"),

    Instr("feq.s", R, "rd, rs1, rs2", fp_op(0b1010000, funct3=0b010), "F", fp="rs1 rs2"),
    Instr("flt.s", R, "rd, rs1, rs2", fp_op(0b1010000, funct3=0b001), "F", fp="rs1 rs2"),
    Instr("fle.s", R, "rd, rs1, rs2", fp_op(0b1010000, funct3=0b000), "F", fp="rs1 rs2"),

    Instr("fcvt.l.s",  RRm, "rd, rs1, rm", fp_op(0b1100000, rs2=0b00010), "F", fp="rs1", xlen=64),
    Instr("fcvt.lu.s", RRm, "rd, rs1, rm", fp_op(0b1100000, rs2=0b00011), "F", fp="rs1", xlen=64),
    Instr("fcvt.s.l",  RRm, "rd, rs1, rm", fp_op(0b1101000, rs2=0b00010), "F", fp="rd", xlen=64),
    Instr("fcvt.s.lu", RRm, "rd, rs1, rm", fp_op(0b1101000, rs2=0b00011), "F", fp="rd", xlen=64),

    # -------------------------------------------------------------------- D
    Instr("fld", I, "rd, imm(rs1)",  f3(0b011, LOAD_FP), "D", fp="rd"),
    Instr("fsd", S, "rs2, imm(rs1)", f3(0b011, STORE_FP), "D", fp="rs2"),

    Instr("fmadd.d",  R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b01, "opcode": MADD},  "D", fp="rd rs1 rs2 rs3"),
    Instr("fmsub.d",  R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b01, "opcode": MSUB},  "D", fp="rd rs1 rs2 rs3"),
    Instr("fnmsub.d", R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b01, "opcode": NMSUB}, "D", fp="rd rs1 rs2 rs3"),
    Instr("fnmadd.d", R4, "rd, rs1, rs2, rs3, rm", {"funct2": 0b01, "opcode": NMADD}, "D", fp="rd rs1 rs2 rs3"),

    Instr("fadd.d",  RRm, "rd, rs1, rs2, rm", fp_op(0b0000001), "D", fp="rd rs1 rs2"),
    Instr("fsub.d",  RRm, "rd, rs1, rs2, rm", fp_op(0b0000101), "D", fp="rd rs1 rs2"),
    Instr("fmul.d",  RRm, "rd, rs1, rs2, rm", fp_op(0b0001001), "D", fp="rd rs1 rs2"),
    Instr("fdiv.d",  RRm, "rd, rs1, rs2, rm", fp_op(0b0001101), "D", fp="rd rs1 rs2"),
    Instr("fsqrt.d", RRm, "rd, rs1, rm",      fp_op(0b0101101, rs2=0), "D", fp="rd rs1"),

    Instr("fsgnj.d",  R, "rd, rs1, rs2", fp_op(0b0010001, funct3=0b000), "D", fp="rd rs1 rs2"),
    Instr("fsgnjn.d", R, "rd, rs1, rs2", fp_op(0b0010001, funct3=0b001), "D", fp="rd rs1 rs2"),
    Instr("fsgnjx.d", R, "rd, rs1, rs2", fp_op(0b0010001, funct3=0b010), "D", fp="rd rs1 rs2"),
    Instr("fmin.d",   R, "rd, rs1, rs2", fp_op(0b0010101, funct3=0b000), "D", fp="rd rs1 rs2"),
    Instr("fmax.d",   R, "rd, rs1, rs2", fp_op(0b0010101, funct3=0b001), "D", fp="rd rs1 rs2"),

    Instr("fcvt.s.d", RRm, "rd, rs1, rm", fp_op(0b0100000, rs2=0b00001), "D", fp="rd rs1"),
    Instr("fcvt.d.s", RRm, "rd, rs1, rm", fp_op(0b0100001, rs2=0b00000), "D", fp="rd rs1"),

    Instr("feq.d", R, "rd, rs1, rs2", fp_op(0b1010001, funct3=0b010), "D", fp="rs1 rs2"),
    Instr("flt.d", R, "rd, rs1, rs2", fp_op(0b1010001, funct3=0b001), "D", fp="rs1 rs2"),
    Instr("fle.d", R, "rd, rs1, rs2", fp_op(0b1010001, funct3=0b000), "D", fp="rs1 rs2"),
    Instr("fclass.d", R, "rd, rs1",   fp_op(0b1110001, rs2=0, funct3=0b001), "D", fp="rs1"),

    Instr("fcvt.w.d",  RRm, "rd, rs1, rm", fp_op(0b1100001, rs2=0b00000), "D", fp="rs1"),
    Instr("fcvt.wu.d", RRm, "rd, rs1, rm", fp_op(0b1100001, rs2=0b00001), "D", fp="rs1"),
    Instr("fcvt.d.w",  RRm, "rd, rs1, rm", fp_op(0b1101001, rs2=0b00000), "D", fp="rd"),
    Instr("fcvt.d.wu", RRm, "rd, rs1, rm", fp_op(0b1101001, rs2=0b00001), "D", fp="rd"),

    Instr("fcvt.l.d",  RRm, "rd, rs1, rm", fp_op(0b1100001, rs2=0b00010), "D", fp="rs1", xlen=64),
    Instr("fcvt.lu.d", RRm, "rd, rs1, rm", fp_op(0b1100001, rs2=0b00011), "D", fp="rs1", xlen=64),
    Instr("fcvt.d.l",  RRm, "rd, rs1, rm", fp_op(0b1101001, rs2=0b00010), "D", fp="rd", xlen=64),
    Instr("fcvt.d.lu", RRm, "rd, rs1, rm", fp_op(0b1101001, rs2=0b00011), "D", fp="rd", xlen=64),
    Instr("fmv.x.d",   R, "rd, rs1", fp_op(0b1110001, rs2=0, funct3=0b000), "D", fp="rs1", xlen=64),
    Instr("fmv.d.x",   R, "rd, rs1", fp_op(0b1111001, rs2=0, funct3=0b000), "D", fp="rd", xlen=64),
)


def instructions(xlen: int) -> tuple[Instr, ...]:
    """Basic instructions available in RV32 (xlen=32) or RV64 (xlen=64)."""
    return tuple(i for i in INSTRUCTIONS if i.exists_in(xlen))


def find(mnemonic: str, xlen: int) -> Instr | None:
    for i in INSTRUCTIONS:
        if i.mnemonic == mnemonic and i.exists_in(xlen):
            return i
    return None
