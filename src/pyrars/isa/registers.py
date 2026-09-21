"""Register, CSR and rounding mode names as RARS accepts them.

Sources: RARS riscv/hardware/{RegisterFile, FloatingPointRegisterFile,
ControlAndStatusRegisterFile}.java; rounding mode encoding from the F extension
chapter of the RISC-V ISA manual.
"""

# ABI names by register number. Parsing of "xN"/"fN" names belongs to the lexer.
X_NAMES = (
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
)

# Extra integer register names (RARS RegisterFile.getRegister).
X_ALIASES = {"fp": 8}

# ABI names by register number.
F_NAMES = (
    "ft0", "ft1", "ft2", "ft3", "ft4", "ft5", "ft6", "ft7",
    "fs0", "fs1", "fa0", "fa1", "fa2", "fa3", "fa4", "fa5",
    "fa6", "fa7", "fs2", "fs3", "fs4", "fs5", "fs6", "fs7",
    "fs8", "fs9", "fs10", "fs11", "ft8", "ft9", "ft10", "ft11",
)

# CSR name -> number. RARS implements the user-level (N extension) CSRs.
CSRS = {
    "ustatus": 0x000,
    "fflags": 0x001,
    "frm": 0x002,
    "fcsr": 0x003,
    "uie": 0x004,
    "utvec": 0x005,
    "uscratch": 0x040,
    "uepc": 0x041,
    "ucause": 0x042,
    "utval": 0x043,
    "uip": 0x044,
    "cycle": 0xC00,
    "time": 0xC01,
    "instret": 0xC02,
    "cycleh": 0xC80,
    "timeh": 0xC81,
    "instreth": 0xC82,
}

# Rounding mode name -> rm field value.
ROUNDING_MODES = {
    "rne": 0b000,  # to nearest, ties to even
    "rtz": 0b001,  # towards zero
    "rdn": 0b010,  # down (towards -infinity)
    "rup": 0b011,  # up (towards +infinity)
    "rmm": 0b100,  # to nearest, ties to max magnitude
    "dyn": 0b111,  # dynamic: use frm
}

