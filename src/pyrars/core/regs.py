"""The registers of the machine: the integer file, the floating point file, pc.

Values are kept unsigned, in as many bits as the machine is wide; an instruction
that reads a register as a signed number asks for it (`signed`), because that is
a property of the instruction and not of the register.

The floating point file is 64 bits wide whatever the machine is. A single
precision value lives in it NaN-boxed, as the D extension of the ISA manual
requires: the upper 32 bits are all ones. Reading a single from a register that
holds something else gives the canonical NaN - that is what every instruction
which takes a single sees - while the bit move `fmv.x.w` and the store `fsw`
take the low 32 bits as they lie. Both rules are verified against RARS
(2026-09-30): `fadd.s` of a register holding a double gives the canonical NaN,
`fmv.x.w` of the same register gives its low word.

Sources: R-REG in `rars-behavior.md`; ISA manual v20260120, chapter D ("NaN
boxing of narrower values") and chapter F for the bit moves.
"""

from pyrars.core.options import Options
from pyrars.isa.registers import X_NAMES
from pyrars.softfloat.formats import box, unbox

COUNT = 32


def as_signed(value: int, bits: int) -> int:
    """An unsigned value read as the number it stands for in two's complement."""
    return value - (1 << bits) if value >> (bits - 1) else value


class Registers:
    """x0..x31 and the program counter.

    x0 is hardwired to zero: a write to it is dropped. `sp` and `gp` start at
    the addresses of the memory configuration, everything else at zero
    (verified against RARS).
    """

    def __init__(self, options: Options = Options(), pc: int | None = None) -> None:
        self.options = options
        self.mask = (1 << options.xlen) - 1
        self.values = [0] * COUNT
        self.values[X_NAMES.index("sp")] = options.config.stack_pointer & self.mask
        self.values[X_NAMES.index("gp")] = options.config.global_pointer & self.mask
        self.pc = options.config.text_base if pc is None else pc & self.mask

    def read(self, number: int) -> int:
        return self.values[number]

    def signed(self, number: int) -> int:
        """The value as the number it stands for in two's complement."""
        return as_signed(self.values[number], self.options.xlen)

    def write(self, number: int, value: int) -> None:
        if number:  # x0 keeps its zero
            self.values[number] = value & self.mask


class FloatRegisters:
    """f0..f31, each 64 bits wide, all starting at zero."""

    def __init__(self) -> None:
        self.values = [0] * COUNT

    def raw(self, number: int) -> int:
        """The 64 bits as they lie: for `fmv.x.d`, `fsd` and the views."""
        return self.values[number]

    def set_raw(self, number: int, value: int) -> None:
        self.values[number] = value & 0xFFFFFFFFFFFFFFFF

    def single(self, number: int) -> int:
        """The single precision value of a register: the canonical NaN unless
        the register holds a boxed single."""
        return unbox(self.values[number])

    def set_single(self, number: int, bits: int) -> None:
        """A single precision result, boxed so that it can be read back."""
        self.values[number] = box(bits & 0xFFFFFFFF)

    def double(self, number: int) -> int:
        return self.values[number]

    def set_double(self, number: int, bits: int) -> None:
        self.values[number] = bits & 0xFFFFFFFFFFFFFFFF

    def low_word(self, number: int) -> int:
        """The low 32 bits as they lie, which is what `fmv.x.w` and `fsw` take."""
        return self.values[number] & 0xFFFFFFFF
