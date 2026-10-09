"""What kind of thing an instruction is, and which registers it touches.

This is the part of the instruction set that `pyrars.analysis` asks for and that
M1 left until something did: the pipeline needs to know that an instruction is a
load (so that the use of its value must wait), that it is a branch (so that a
wrong guess costs a flush), that it is a division (so that it holds the stage
longer), and which registers it reads and writes (so that a dependence can be
seen at all). The statistics want the same kinds to count by, and the help of the
interface will want them to group instructions.

The kind of an instruction is read off its OPCODE, which is how the hardware
itself tells them apart; only two refinements are needed. The opcodes of the base
set hold the multiplication and division of the M extension as well, so those are
told by their mnemonics, and the opcode 0x73 holds both the control registers and
the four instructions of the environment, which the format tells apart. Nothing
here is a judgement: every instruction of every width lands in exactly one kind,
and a test says so.

The five kinds RARS counts by (ALU, Jump, Branch, Memory, Other) are derived from
ours, so a program can be compared with its tool of statistics: its ALU holds the
multiplication and division, because they are written as the same kind of thing in
its own sources, and its Memory holds only the integer loads and stores - the
floating point ones are among its Other.

The registers come from the operands: `rd` is written, `rs1`, `rs2` and `rs3` are
read, and `Instr.fp` says which of them are floating point registers. The register
x0 is left out of both: it holds its zero whatever is written to it, so no
dependence on it can exist. The control registers are not followed here; a
dependence through them is a thing of its own, and nothing yet asks for it.
"""

from dataclasses import dataclass
from enum import Enum, auto

from pyrars.isa.codec import Decoded
from pyrars.isa.spec import Instr


class Kind(Enum):
    """What an instruction is, for whoever counts or times it."""

    ALU = auto()  # the base set: arithmetic, logic, shifts, lui, auipc
    MULTIPLY = auto()
    DIVIDE = auto()
    LOAD = auto()
    STORE = auto()
    BRANCH = auto()
    JUMP = auto()  # jal, jalr
    CSR = auto()
    SYSTEM = auto()  # ecall, ebreak, uret, wfi
    FENCE = auto()
    FLOAT = auto()  # every computation, comparison, conversion and move of F and D
    FLOAT_LOAD = auto()
    FLOAT_STORE = auto()


# The opcode says the kind. Where one opcode holds more than one kind, the two
# refinements below settle it.
BY_OPCODE = {
    0x03: Kind.LOAD,
    0x07: Kind.FLOAT_LOAD,
    0x0F: Kind.FENCE,
    0x13: Kind.ALU,
    0x17: Kind.ALU,  # auipc
    0x1B: Kind.ALU,
    0x23: Kind.STORE,
    0x27: Kind.FLOAT_STORE,
    0x33: Kind.ALU,  # and the M extension, told by its mnemonics
    0x37: Kind.ALU,  # lui
    0x3B: Kind.ALU,  # and the M extension again
    0x43: Kind.FLOAT,
    0x47: Kind.FLOAT,
    0x4B: Kind.FLOAT,
    0x4F: Kind.FLOAT,
    0x53: Kind.FLOAT,
    0x63: Kind.BRANCH,
    0x67: Kind.JUMP,  # jalr
    0x6F: Kind.JUMP,  # jal
    0x73: Kind.CSR,  # and the instructions of the environment, told by the format
}

# The five RARS counts by (`tools/InstructionStatistics`), from ours.
CATEGORIES = {
    Kind.ALU: "ALU", Kind.MULTIPLY: "ALU", Kind.DIVIDE: "ALU",
    Kind.JUMP: "Jump",
    Kind.BRANCH: "Branch",
    Kind.LOAD: "Memory", Kind.STORE: "Memory",
    Kind.CSR: "Other", Kind.SYSTEM: "Other", Kind.FENCE: "Other",
    Kind.FLOAT: "Other", Kind.FLOAT_LOAD: "Other", Kind.FLOAT_STORE: "Other",
}

# The operands that name a register, and what each one does with it.
WRITTEN = ("rd",)
READ = ("rs1", "rs2", "rs3")


@dataclass(frozen=True, slots=True)
class RegRef:
    """One register an instruction touches: which file it is in, and its number."""

    file: str  # "x" for the integer registers, "f" for the floating point ones
    number: int


def kind(instr: Instr) -> Kind:
    """What kind of thing an instruction is."""
    found = BY_OPCODE[instr.fixed["opcode"]]
    if instr.ext == "M":
        return Kind.MULTIPLY if instr.mnemonic.startswith("mul") else Kind.DIVIDE
    if found is Kind.CSR and "csr" not in instr.operands:
        return Kind.SYSTEM  # ecall, ebreak, uret and wfi share the opcode
    return found


def category(instr: Instr) -> str:
    """The kind as RARS counts it: ALU, Jump, Branch, Memory or Other."""
    return CATEGORIES[kind(instr)]


def writes(decoded: Decoded) -> tuple[RegRef, ...]:
    """The registers an instruction writes; x0 is no dependence and is left out."""
    return _refs(decoded, WRITTEN)


def reads(decoded: Decoded) -> tuple[RegRef, ...]:
    """The registers an instruction reads; x0 is left out for the same reason."""
    return _refs(decoded, READ)


def _refs(decoded: Decoded, operands: tuple[str, ...]) -> tuple[RegRef, ...]:
    floating = decoded.instr.fp.split()
    found = []
    for name in operands:
        if name not in decoded.operands:
            continue
        number = decoded.operands[name]
        file = "f" if name in floating else "x"
        if file == "x" and number == 0:
            continue
        found.append(RegRef(file, number))
    return tuple(found)
