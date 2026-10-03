"""What each instruction does to the machine.

One function carries out one instruction: `execute(machine, fetched)`. The
program counter is moved on before the instruction runs, so that a branch or a
jump only has to write it again, while `auipc` and the jumps read the address of
the instruction itself from `fetched`.

The families of instructions are tables of small functions over unsigned values
of the width of the machine; the width is a parameter throughout (INV-X), and the
32-bit forms of a 64-bit machine (`addw` and its kind) are the same tables read
with a width of 32 and the result extended back to 64 bits.

This stage carries out the integer instructions: the base set, the multiplication
and division of M, the control registers of Zicsr, and the fences. The floating
point instructions follow in stage 18; until then they end in the same place as a
word that encodes nothing - an illegal instruction.

Sources: RISC-V ISA manual v20260120, chapters "RV32I Base Integer Instruction
Set" (the arithmetic, the loads and stores, the branches and jumps), "M"
Extension (the table of division by zero and of the one overflow), and "Zicsr"
(which forms write and which only read).
"""

from pyrars.core import floats, syscalls, traps
from pyrars.core.machine import Machine
from pyrars.core.memory import Fetched
from pyrars.core.regs import as_signed
from pyrars.core.traps import Trap
from pyrars.isa.registers import CSRS


# ----------------------------------------------------------- the arithmetic


def _divide(a: int, b: int, bits: int) -> int:
    """Signed division, truncated toward zero. Division by zero gives all ones
    and the one overflow gives the dividend back (ISA manual, M extension)."""
    left, right = as_signed(a, bits), as_signed(b, bits)
    if right == 0:
        return -1
    if left == -(1 << (bits - 1)) and right == -1:
        return left
    quotient = abs(left) // abs(right)
    return quotient if (left < 0) == (right < 0) else -quotient


def _remainder(a: int, b: int, bits: int) -> int:
    """The remainder of that division: the dividend when dividing by zero, zero
    at the overflow."""
    left, right = as_signed(a, bits), as_signed(b, bits)
    if right == 0:
        return left
    if left == -(1 << (bits - 1)) and right == -1:
        return 0
    return left - _divide(a, b, bits) * right


# Every operation takes two unsigned values and the width, and gives a value the
# caller cuts to that width.
ALU = {
    "add": lambda a, b, n: a + b,
    "sub": lambda a, b, n: a - b,
    "and": lambda a, b, n: a & b,
    "or": lambda a, b, n: a | b,
    "xor": lambda a, b, n: a ^ b,
    "sll": lambda a, b, n: a << (b & (n - 1)),
    "srl": lambda a, b, n: a >> (b & (n - 1)),
    "sra": lambda a, b, n: as_signed(a, n) >> (b & (n - 1)),
    "slt": lambda a, b, n: int(as_signed(a, n) < as_signed(b, n)),
    "sltu": lambda a, b, n: int(a < b),
    "mul": lambda a, b, n: as_signed(a, n) * as_signed(b, n),
    "mulh": lambda a, b, n: (as_signed(a, n) * as_signed(b, n)) >> n,
    "mulhu": lambda a, b, n: (a * b) >> n,
    "mulhsu": lambda a, b, n: (as_signed(a, n) * b) >> n,
    "div": _divide,
    "divu": lambda a, b, n: (1 << n) - 1 if b == 0 else a // b,
    "rem": _remainder,
    "remu": lambda a, b, n: a if b == 0 else a % b,
}

# Which table entry a mnemonic uses. A name ending in "w" is the 32-bit form of a
# 64-bit machine: the same operation, read with a width of 32.
REGISTER_FORMS = {name: name for name in ALU}
REGISTER_FORMS.update({f"{name}w": name for name in
                       ("add", "sub", "sll", "srl", "sra", "mul", "div", "divu", "rem", "remu")})
IMMEDIATE_FORMS = {"addi": "add", "slti": "slt", "sltiu": "sltu", "xori": "xor",
                   "ori": "or", "andi": "and", "addiw": "add"}
SHIFT_FORMS = {"slli": "sll", "srli": "srl", "srai": "sra",
               "slliw": "sll", "srliw": "srl", "sraiw": "sra"}

# Loads and stores: how many bytes, and whether a load extends the sign.
LOADS = {"lb": (1, True), "lh": (2, True), "lw": (4, True), "ld": (8, True),
         "lbu": (1, False), "lhu": (2, False), "lwu": (4, False)}
STORES = {"sb": 1, "sh": 2, "sw": 4, "sd": 8}

BRANCHES = {
    "beq": lambda a, b, n: a == b,
    "bne": lambda a, b, n: a != b,
    "blt": lambda a, b, n: as_signed(a, n) < as_signed(b, n),
    "bge": lambda a, b, n: as_signed(a, n) >= as_signed(b, n),
    "bltu": lambda a, b, n: a < b,
    "bgeu": lambda a, b, n: a >= b,
}


# --------------------------------------------------------------- one instruction


def execute(machine: Machine, fetched: Fetched) -> None:
    """Carry out one instruction. Raises Trap when it cannot be carried out."""
    if fetched.instr is None:
        raise Trap(traps.ILLEGAL_INSTRUCTION, fetched.word,
                   f"undefined instruction (0x{fetched.word:08x})")
    mnemonic = fetched.instr.instr.mnemonic
    machine.x.pc = (fetched.address + 4) & machine.mask
    _carry_out(machine, mnemonic, fetched.instr.operands, fetched.address)


def _carry_out(machine: Machine, mnemonic: str, operands: dict[str, int],
               address: int) -> None:
    width = machine.xlen
    if mnemonic in REGISTER_FORMS:
        narrow = mnemonic.endswith("w")
        bits = 32 if narrow else width
        left = machine.x.read(operands["rs1"]) & ((1 << bits) - 1)
        right = machine.x.read(operands["rs2"]) & ((1 << bits) - 1)
        _put(machine, operands["rd"], ALU[REGISTER_FORMS[mnemonic]](left, right, bits), bits)
        return
    if mnemonic in IMMEDIATE_FORMS:
        bits = 32 if mnemonic.endswith("w") else width
        left = machine.x.read(operands["rs1"]) & ((1 << bits) - 1)
        right = operands["imm"] & ((1 << bits) - 1)
        _put(machine, operands["rd"], ALU[IMMEDIATE_FORMS[mnemonic]](left, right, bits), bits)
        return
    if mnemonic in SHIFT_FORMS:
        bits = 32 if mnemonic.endswith("w") else width
        left = machine.x.read(operands["rs1"]) & ((1 << bits) - 1)
        _put(machine, operands["rd"],
             ALU[SHIFT_FORMS[mnemonic]](left, operands["shamt"], bits), bits)
        return
    if mnemonic in LOADS:
        size, extend = LOADS[mnemonic]
        value = machine.memory.read(_address(machine, operands), size)
        machine.x.write(operands["rd"], as_signed(value, 8 * size) if extend else value)
        return
    if mnemonic in STORES:
        size = STORES[mnemonic]
        machine.memory.write(_address(machine, operands), size,
                             machine.x.read(operands["rs2"]))
        return
    if mnemonic in BRANCHES:
        left, right = machine.x.read(operands["rs1"]), machine.x.read(operands["rs2"])
        if BRANCHES[mnemonic](left, right, width):
            machine.x.pc = (address + operands["imm"]) & machine.mask
        return
    if mnemonic in floats.MNEMONICS:
        floats.execute(machine, mnemonic, operands)
        return
    handler = HANDLERS.get(mnemonic)
    if handler is None:  # every instruction of the set has its place by now
        raise Trap(traps.ILLEGAL_INSTRUCTION, 0, f'"{mnemonic}" is not carried out yet')
    handler(machine, operands, address)


def _put(machine: Machine, number: int, value: int, bits: int) -> None:
    """Write a result of `bits` bits into a register, extending its sign when the
    machine is wider than the result (the 32-bit forms of RV64)."""
    value &= (1 << bits) - 1
    machine.x.write(number, as_signed(value, bits) if bits < machine.xlen else value)


def _address(machine: Machine, operands: dict[str, int]) -> int:
    return (machine.x.read(operands["rs1"]) + operands["imm"]) & machine.mask


# ------------------------------------------------------- the single instructions


def _lui(machine: Machine, operands: dict[str, int], address: int) -> None:
    _put(machine, operands["rd"], operands["imm"] << 12, 32)


def _auipc(machine: Machine, operands: dict[str, int], address: int) -> None:
    # The offset is a 32-bit number; the addition is as wide as the machine.
    offset = as_signed((operands["imm"] << 12) & 0xFFFFFFFF, 32)
    machine.x.write(operands["rd"], (address + offset) & machine.mask)


def _jal(machine: Machine, operands: dict[str, int], address: int) -> None:
    machine.x.write(operands["rd"], (address + 4) & machine.mask)
    machine.x.pc = (address + operands["imm"]) & machine.mask


def _jalr(machine: Machine, operands: dict[str, int], address: int) -> None:
    # The target is computed first: `jalr rd, rd, 0` must still jump right. Its
    # lowest bit is cleared, as the manual says, so an odd target becomes even.
    target = (machine.x.read(operands["rs1"]) + operands["imm"]) & ~1
    machine.x.write(operands["rd"], (address + 4) & machine.mask)
    machine.x.pc = target & machine.mask


def _ecall(machine: Machine, operands: dict[str, int], address: int) -> None:
    """A request to the world outside: `core/syscalls.py` serves it."""
    syscalls.call(machine)


def _ebreak(machine: Machine, operands: dict[str, int], address: int) -> None:
    raise Trap(traps.BREAKPOINT, 0, "ebreak")


def _uret(machine: Machine, operands: dict[str, int], address: int) -> None:
    """Back from a handler: what interrupts were allowed before is allowed again,
    and the machine carries on where `uepc` says."""
    status = machine.csr.read(CSRS["ustatus"])
    allowed = traps.UIE_BIT if status & traps.UPIE_BIT else 0
    machine.csr.poke("ustatus", (status & ~(traps.UIE_BIT | traps.UPIE_BIT)) | allowed)
    machine.x.pc = machine.csr.read(CSRS["uepc"]) & machine.mask


def _wfi(machine: Machine, operands: dict[str, int], address: int) -> None:
    """Wait for an interrupt. With an external or timer event already waiting
    there is nothing to wait for; otherwise the simulator is told so."""
    if machine.pending.external is None and machine.pending.timer is None:
        raise traps.Waiting()


def _fence(machine: Machine, operands: dict[str, int], address: int) -> None:
    """Nothing to order: the memory of the machine answers in the order it is
    asked, and there is no cache between them."""


def _csrrw(machine: Machine, operands: dict[str, int], address: int) -> None:
    value = machine.x.read(operands["rs1"])
    old = machine.csr.read(operands["csr"])
    machine.csr.write(operands["csr"], value)
    machine.x.write(operands["rd"], old)


def _csrrs(machine: Machine, operands: dict[str, int], address: int) -> None:
    _csr_set_or_clear(machine, operands, machine.x.read(operands["rs1"]), clear=False)


def _csrrc(machine: Machine, operands: dict[str, int], address: int) -> None:
    _csr_set_or_clear(machine, operands, machine.x.read(operands["rs1"]), clear=True)


def _csrrwi(machine: Machine, operands: dict[str, int], address: int) -> None:
    old = machine.csr.read(operands["csr"])
    machine.csr.write(operands["csr"], operands["uimm"])
    machine.x.write(operands["rd"], old)


def _csrrsi(machine: Machine, operands: dict[str, int], address: int) -> None:
    _csr_set_or_clear(machine, operands, operands["uimm"], clear=False)


def _csrrci(machine: Machine, operands: dict[str, int], address: int) -> None:
    _csr_set_or_clear(machine, operands, operands["uimm"], clear=True)


def _csr_set_or_clear(machine: Machine, operands: dict[str, int], bits: int,
                      clear: bool) -> None:
    """What `csrrs`, `csrrc` and their forms with an immediate do. A form whose
    bits are zero writes nothing, so it may read a register that is read-only."""
    old = machine.csr.read(operands["csr"])
    if bits:
        machine.csr.write(operands["csr"], old & ~bits if clear else old | bits)
    machine.x.write(operands["rd"], old)


HANDLERS = {
    "lui": _lui, "auipc": _auipc, "jal": _jal, "jalr": _jalr,
    "ecall": _ecall, "ebreak": _ebreak, "fence": _fence, "fence.i": _fence,
    "uret": _uret, "wfi": _wfi,
    "csrrw": _csrrw, "csrrs": _csrrs, "csrrc": _csrrc,
    "csrrwi": _csrrwi, "csrrsi": _csrrsi, "csrrci": _csrrci,
}
