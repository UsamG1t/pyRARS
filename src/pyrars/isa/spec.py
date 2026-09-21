"""Schema of the instruction set description.

An instruction format is a class whose fields are declared as

    name: Annotated[Kind, Bits(hi, lo, at=...), ...]

Kind says what the field holds; each Bits says that word bits hi..lo hold the
value bits starting at `at`. Formats are never instantiated: when a Format
subclass is created, its annotations are read once into `fields` and checked.

An instruction (Instr) is a format plus: the operand syntax (field names in
assembly order) and the values of all other fields (fixed fields).
"""

import annotationlib
import re
import typing
from dataclasses import dataclass
from functools import cached_property
from typing import ClassVar

# ---------------------------------------------------------------- field kinds


class Kind:
    """What a field holds. `signed`: the value is two's complement."""

    signed: ClassVar[bool] = False


class Fixed(Kind):
    """Opcode or function code: its value is given by the instruction."""


class Reg(Kind):
    """Register number 0..31 (integer or floating point, see Instr.fp)."""


class UImm(Kind):
    """Unsigned immediate: shift amount, CSR immediate, fence set, upper immediate."""


class SImm(Kind):
    """Signed immediate."""

    signed = True


class Offset(Kind):
    """Signed PC-relative byte offset of a branch or jump."""

    signed = True


class Csr(Kind):
    """CSR number."""


class RoundingMode(Kind):
    """Floating point rounding mode (rm)."""


# --------------------------------------------------------------- bit layout


@dataclass(frozen=True)
class Bits:
    """Instruction word bits hi..lo hold value bits at .. at+(hi-lo)."""

    hi: int
    lo: int
    at: int = 0

    @property
    def size(self) -> int:
        return self.hi - self.lo + 1

    @property
    def word_mask(self) -> int:
        return ((1 << self.size) - 1) << self.lo


@dataclass(frozen=True)
class Field:
    name: str
    kind: type[Kind]
    bits: tuple[Bits, ...]

    @property
    def word_mask(self) -> int:
        mask = 0
        for b in self.bits:
            mask |= b.word_mask
        return mask

    @property
    def low(self) -> int:
        """Value bits below `low` are not stored and must be zero (branch offsets)."""
        return min(b.at for b in self.bits)

    @property
    def width(self) -> int:
        """Number of value bits, including the unstored low bits."""
        return max(b.at + b.size for b in self.bits)

    def check(self, value: int) -> None:
        """Raise ValueError if value does not fit this field."""
        if self.kind.signed:
            lo, hi = -(1 << (self.width - 1)), (1 << (self.width - 1)) - 1
        else:
            lo, hi = 0, (1 << self.width) - 1
        if not lo <= value <= hi:
            raise ValueError(f"{self.name}: {value} is out of range {lo}..{hi}")
        if value & ((1 << self.low) - 1):
            raise ValueError(f"{self.name}: {value} is not a multiple of {1 << self.low}")

    def put(self, value: int) -> int:
        """Word bits holding value (value must be checked)."""
        word = 0
        for b in self.bits:
            word |= ((value >> b.at) & ((1 << b.size) - 1)) << b.lo
        return word

    def get(self, word: int) -> int:
        value = 0
        for b in self.bits:
            value |= ((word >> b.lo) & ((1 << b.size) - 1)) << b.at
        if self.kind.signed and value >> (self.width - 1):
            value -= 1 << self.width
        return value


class Format:
    """Base class of instruction formats (see module docstring)."""

    fields: ClassVar[dict[str, Field]]

    def __init_subclass__(cls) -> None:
        cls.fields = {}
        covered = 0
        for name, annotation in annotationlib.get_annotations(cls).items():
            kind, *bits = typing.get_args(annotation) or (None,)
            if not (isinstance(kind, type) and issubclass(kind, Kind)
                    and bits and all(isinstance(b, Bits) for b in bits)):
                raise ValueError(f"{cls.__name__}.{name}: expected Annotated[Kind, Bits, ...]")
            f = Field(name, kind, tuple(bits))
            value_bits = 0
            for b in bits:
                if not 0 <= b.lo <= b.hi <= 31 or b.at < 0:
                    raise ValueError(f"{cls.__name__}.{name}: bad bits {b}")
                if covered & b.word_mask:
                    raise ValueError(f"{cls.__name__}.{name}: bits {b} overlap another field")
                covered |= b.word_mask
                b_value_bits = ((1 << b.size) - 1) << b.at
                if value_bits & b_value_bits:
                    raise ValueError(f"{cls.__name__}.{name}: bits {b} repeat value bits")
                value_bits |= b_value_bits
            if value_bits != (1 << f.width) - (1 << f.low):
                raise ValueError(f"{cls.__name__}.{name}: value bits are not contiguous")
            cls.fields[name] = f
        if covered != 0xFFFFFFFF:
            raise ValueError(f"{cls.__name__}: fields do not cover all 32 bits")


# ------------------------------------------------------------- instructions


@dataclass(frozen=True, eq=False)
class Instr:
    """A basic instruction: one 32-bit machine word.

    syntax - operands in assembly order, as format field names, e.g. "rd, imm(rs1)"
    fixed  - values of all fields that are not operands
    fp     - names of Reg operands holding floating point registers, e.g. "rd rs1"
    xlen   - 32 or 64 if the instruction exists only in RV32 or only in RV64
    """

    mnemonic: str
    format: type[Format]
    syntax: str
    fixed: dict[str, int]
    ext: str
    fp: str = ""
    xlen: int | None = None

    def __post_init__(self) -> None:
        fields = self.format.fields
        for name in self.operands:
            if name not in fields:
                raise ValueError(f"{self.mnemonic}: operand {name!r} is not a field of {self.format.__name__}")
            if name in self.fixed:
                raise ValueError(f"{self.mnemonic}: {name!r} is both operand and fixed")
        if len(set(self.operands)) != len(self.operands):
            raise ValueError(f"{self.mnemonic}: repeated operand")
        for name, value in self.fixed.items():
            if name not in fields:
                raise ValueError(f"{self.mnemonic}: fixed {name!r} is not a field of {self.format.__name__}")
            fields[name].check(value)
        missing = set(fields) - set(self.operands) - set(self.fixed)
        if missing:
            raise ValueError(f"{self.mnemonic}: fields {sorted(missing)} are neither operands nor fixed")
        for name in self.fp.split():
            if name not in self.operands or fields[name].kind is not Reg:
                raise ValueError(f"{self.mnemonic}: fp {name!r} is not a Reg operand")
        if self.xlen not in (None, 32, 64):
            raise ValueError(f"{self.mnemonic}: xlen must be None, 32 or 64")

    @cached_property
    def operands(self) -> tuple[str, ...]:
        return tuple(re.findall(r"[a-z][a-z0-9]*", self.syntax))

    @cached_property
    def mask(self) -> int:
        """Word bits that identify the instruction."""
        mask = 0
        for name in self.fixed:
            mask |= self.format.fields[name].word_mask
        return mask

    @cached_property
    def match(self) -> int:
        """Values of the identifying bits."""
        word = 0
        for name, value in self.fixed.items():
            word |= self.format.fields[name].put(value)
        return word

    def is_fp(self, operand: str) -> bool:
        return operand in self.fp.split()

    def exists_in(self, xlen: int) -> bool:
        return self.xlen is None or self.xlen == xlen
