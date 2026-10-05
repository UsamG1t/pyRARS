"""What the floating point instructions do.

The arithmetic itself is `pyrars.softfloat`, closed in stage 14; this module takes
the operands out of the registers, gives the result its place, and adds the flags
of the operation to `fcsr`. Which registers an instruction uses as floating point
ones is written in the instruction table (`Instr.fp`), and the names say the rest:
`fcvt.w.s` reads a single and writes a signed 32-bit integer.

A single precision value lives in a register boxed, so a result of `.s` is written
boxed and read with the rule that a register holding anything else reads as the
canonical NaN. That holds for the sign injection as well, and for `fsw` and
`fmv.x.w` it does not: those take the low word as it lies (all verified in RARS).

The rounding mode is the `rm` field of the instruction, or `frm` where the field
says "dynamic". A reserved mode is refused, naming the number that was actually
asked for: `Invalid rounding mode 7`, or `Invalid rounding mode 5 in frm` when the
field said dynamic. RARS prints both numbers and a full stop in the middle of its
sentence (DEV-54).

Sources: RISC-V ISA manual v20260120, chapters F and D; the verified behaviour of
RARS in R-FP and R-REG.
"""

from pyrars.core import traps
from pyrars.core.regs import as_signed
from pyrars.core.traps import Trap
from pyrars.isa.instructions import instructions
from pyrars.softfloat.arith import (add, divide, fused_multiply_add, multiply, negate,
                                    square_root, subtract)
from pyrars.softfloat.compare import equal, less, less_equal, maximum, minimum
from pyrars.softfloat.convert import from_integer, to_format, to_integer
from pyrars.softfloat.formats import BINARY32, BINARY64, Format, classify
from pyrars.softfloat.rounding import DYN, MODES

# Every instruction of the two extensions comes through here.
MNEMONICS = frozenset(instr.mnemonic for instr in instructions(64) if instr.ext in ("F", "D"))

FORMATS = {"s": BINARY32, "d": BINARY64}
# The integer a conversion reads or writes: how wide, and whether it has a sign.
INTEGERS = {"w": (32, True), "wu": (32, False), "l": (64, True), "lu": (64, False)}

ARITHMETIC = {"fadd": add, "fsub": subtract, "fmul": multiply, "fdiv": divide}
# Which of the product and the addend a fused instruction turns around.
FUSED = {"fmadd": (False, False), "fmsub": (False, True),
         "fnmsub": (True, False), "fnmadd": (True, True)}
COMPARISONS = {"feq": equal, "flt": less, "fle": less_equal}
EXTREMES = {"fmin": minimum, "fmax": maximum}
SIGNS = ("fsgnj", "fsgnjn", "fsgnjx")
LOADS = {"flw": 4, "fld": 8}
STORES = {"fsw": 4, "fsd": 8}


def execute(machine, mnemonic: str, operands: dict[str, int]) -> None:
    """Carry out one floating point instruction."""
    if mnemonic in LOADS:
        _load(machine, mnemonic, operands)
        return
    if mnemonic in STORES:
        _store(machine, mnemonic, operands)
        return
    name, _, rest = mnemonic.partition(".")
    if name == "fcvt":
        _convert(machine, rest, operands)
        return
    if name == "fmv":
        _move(machine, rest, operands)
        return
    fmt = FORMATS[rest]
    if name in ARITHMETIC or name == "fsqrt":
        _arithmetic(machine, name, operands, fmt)
    elif name in FUSED:
        _fused(machine, name, operands, fmt)
    elif name in COMPARISONS:
        value, flags = COMPARISONS[name](_value(machine, operands["rs1"], fmt),
                                         _value(machine, operands["rs2"], fmt), fmt)
        machine.x.write(operands["rd"], int(value))
        machine.csr.raise_flags(flags)
    elif name in EXTREMES:
        bits, flags = EXTREMES[name](_value(machine, operands["rs1"], fmt),
                                     _value(machine, operands["rs2"], fmt), fmt)
        _result(machine, operands["rd"], bits, fmt)
        machine.csr.raise_flags(flags)
    elif name in SIGNS:
        _inject_sign(machine, name, operands, fmt)
    elif name == "fclass":
        machine.x.write(operands["rd"], classify(_value(machine, operands["rs1"], fmt), fmt))
    else:  # every mnemonic of the two extensions is named above
        raise Trap(traps.ILLEGAL_INSTRUCTION, 0, f'"{mnemonic}" is not carried out yet')


# ------------------------------------------------------------------ the parts


def _value(machine, number: int, fmt: Format) -> int:
    """The value of a floating point register in that format."""
    return machine.f.single(number) if fmt is BINARY32 else machine.f.double(number)


def _result(machine, number: int, bits: int, fmt: Format) -> None:
    if fmt is BINARY32:
        machine.f.set_single(number, bits)
    else:
        machine.f.set_double(number, bits)


def _mode(machine, operands: dict[str, int]) -> int:
    """The rounding mode of an instruction; a reserved one is refused."""
    asked = operands["rm"]
    dynamic = machine.csr.rounding_mode()
    mode = dynamic if asked == DYN else asked
    if mode not in MODES:
        # The number that matters is the one that was asked for: the field of
        # the instruction, or `frm` when the field says dynamic (DEV-54).
        raise Trap(traps.ILLEGAL_INSTRUCTION, 0,
                   f"Invalid rounding mode {dynamic} in frm" if asked == DYN
                   else f"Invalid rounding mode {asked}")
    return mode


def _address(machine, operands: dict[str, int]) -> int:
    return (machine.x.read(operands["rs1"]) + operands["imm"]) & machine.mask


def _load(machine, mnemonic: str, operands: dict[str, int]) -> None:
    size = LOADS[mnemonic]
    value = machine.memory.read(_address(machine, operands), size)
    if size == 4:
        machine.f.set_single(operands["rd"], value)
    else:
        machine.f.set_double(operands["rd"], value)


def _store(machine, mnemonic: str, operands: dict[str, int]) -> None:
    size = STORES[mnemonic]
    value = (machine.f.low_word(operands["rs2"]) if size == 4
             else machine.f.raw(operands["rs2"]))
    machine.memory.write(_address(machine, operands), size, value)


def _arithmetic(machine, name: str, operands: dict[str, int], fmt: Format) -> None:
    mode = _mode(machine, operands)
    left = _value(machine, operands["rs1"], fmt)
    if name == "fsqrt":
        bits, flags = square_root(left, fmt, mode)
    else:
        bits, flags = ARITHMETIC[name](left, _value(machine, operands["rs2"], fmt), fmt, mode)
    _result(machine, operands["rd"], bits, fmt)
    machine.csr.raise_flags(flags)


def _fused(machine, name: str, operands: dict[str, int], fmt: Format) -> None:
    turn_product, turn_addend = FUSED[name]
    mode = _mode(machine, operands)
    first = _value(machine, operands["rs1"], fmt)
    second = _value(machine, operands["rs2"], fmt)
    addend = _value(machine, operands["rs3"], fmt)
    if turn_product:
        first = negate(first, fmt)
    if turn_addend:
        addend = negate(addend, fmt)
    bits, flags = fused_multiply_add(first, second, addend, fmt, mode)
    _result(machine, operands["rd"], bits, fmt)
    machine.csr.raise_flags(flags)


def _inject_sign(machine, name: str, operands: dict[str, int], fmt: Format) -> None:
    """The sign of one operand on the value of another; no flag is raised."""
    left = _value(machine, operands["rs1"], fmt)
    right = _value(machine, operands["rs2"], fmt)
    rest = left & ~fmt.sign_mask
    if name == "fsgnj":
        bits = rest | (right & fmt.sign_mask)
    elif name == "fsgnjn":
        bits = rest | (~right & fmt.sign_mask)
    else:  # fsgnjx: the two signs together
        bits = left ^ (right & fmt.sign_mask)
    _result(machine, operands["rd"], bits, fmt)


def _convert(machine, kinds: str, operands: dict[str, int]) -> None:
    """`fcvt.<to>.<from>`: between the formats, from an integer, or to one."""
    to, _, source = kinds.partition(".")
    mode = _mode(machine, operands)
    if to in FORMATS and source in FORMATS:
        bits, flags = to_format(_value(machine, operands["rs1"], FORMATS[source]),
                                FORMATS[source], FORMATS[to], mode)
        _result(machine, operands["rd"], bits, FORMATS[to])
    elif to in FORMATS:
        width, signed = INTEGERS[source]
        held = machine.x.read(operands["rs1"]) & ((1 << width) - 1)
        bits, flags = from_integer(as_signed(held, width) if signed else held,
                                  FORMATS[to], mode)
        _result(machine, operands["rd"], bits, FORMATS[to])
    else:
        width, signed = INTEGERS[to]
        value, flags = to_integer(_value(machine, operands["rs1"], FORMATS[source]),
                                  FORMATS[source], width, signed, mode)
        # A result of 32 bits is written with its sign extended, the unsigned one
        # as well (ISA manual, chapter F; verified in RARS).
        machine.x.write(operands["rd"],
                        as_signed(value & 0xFFFFFFFF, 32) if width == 32 else value)
    machine.csr.raise_flags(flags)


def _move(machine, kinds: str, operands: dict[str, int]) -> None:
    """`fmv.x.w` and its three relatives: bits from one file to the other."""
    to, _, source = kinds.partition(".")
    if to == "x":
        if source == "w":
            machine.x.write(operands["rd"],
                            as_signed(machine.f.low_word(operands["rs1"]), 32))
        else:
            machine.x.write(operands["rd"], machine.f.raw(operands["rs1"]))
    elif to == "w":
        machine.f.set_single(operands["rd"], machine.x.read(operands["rs1"]) & 0xFFFFFFFF)
    else:
        machine.f.set_raw(operands["rd"], machine.x.read(operands["rs1"]))
