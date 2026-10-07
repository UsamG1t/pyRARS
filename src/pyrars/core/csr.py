"""The control and status registers: the seventeen RARS keeps.

Four kinds, all verified by running RARS (2026-09-30):
  - plain: `uie`, `uip`, `utvec`, `uscratch`, `uepc`, `ucause`, `utval` take every
    bit of a word of the machine;
  - masked: `ustatus` keeps only the bits 0x11 (UIE and UPIE) of what is
    written, `fcsr` only the bits 0xFF;
  - a window into another register: `fflags` is the bits 0..4 of `fcsr`, `frm`
    its bits 5..7, and `cycleh`, `timeh`, `instreth` are the upper half of the
    counters. A window is written through its host and takes the mask of it;
  - read-only: the three counters and their halves. A program that tries to
    write one, in any of the six forms of the instruction, is refused - and the
    message names the register, where RARS says only "CSR" (DEV-54); a form
    whose source is zero is a plain read and passes.

`cycle` and `instret` count one per instruction, as in RARS, which has no model
of cycles; the pipeline of `pyrars.analysis` counts its own and never writes here
(INV-P). `time` is not stored: it asks the clock of the machine, which is the
wall clock in milliseconds by default and a given function in a test, so that a
run can be made repeatable (INV-D; user decision 2026-09-30).

Sources: R-CSR in `rars-behavior.md`; the numbers from `isa/registers.py`.
"""

import time as _time
from collections.abc import Callable
from dataclasses import dataclass

from pyrars.core import traps
from pyrars.core.history import Kind
from pyrars.core.options import Options
from pyrars.isa.registers import CSRS

# Bits of `uie` and `uip` (R-CSR).
SOFTWARE = 0x001
TIMER = 0x010
EXTERNAL = 0x100

# What `fcsr` holds: the flags of the exceptions and the rounding mode.
FFLAGS_BITS = 5
FRM_SHIFT = 5
FRM_BITS = 3


@dataclass(frozen=True, slots=True)
class Register:
    """One control and status register."""

    name: str
    number: int
    writable: int | None = None  # bits a program may write; None means all of them
    read_only: bool = False
    width: int = 0  # bits it holds; 0 means as wide as the machine
    host: str = ""  # the register this one is a window into
    shift: int = 0  # where the window sits in its host
    bits: int = 0  # how wide the window is


def _wall_clock() -> int:
    """Milliseconds since the epoch, which is what RARS reads."""
    return _time.time_ns() // 1_000_000


REGISTERS = (
    Register("ustatus", CSRS["ustatus"], writable=0x11),
    Register("fflags", CSRS["fflags"], host="fcsr", shift=0, bits=FFLAGS_BITS),
    Register("frm", CSRS["frm"], host="fcsr", shift=FRM_SHIFT, bits=FRM_BITS),
    Register("fcsr", CSRS["fcsr"], writable=0xFF),
    Register("uie", CSRS["uie"]),
    Register("utvec", CSRS["utvec"]),
    Register("uscratch", CSRS["uscratch"]),
    Register("uepc", CSRS["uepc"]),
    Register("ucause", CSRS["ucause"]),
    Register("utval", CSRS["utval"]),
    Register("uip", CSRS["uip"]),
    # The counters hold 64 bits whatever the machine is wide: the upper half is
    # what `cycleh`, `timeh` and `instreth` read.
    Register("cycle", CSRS["cycle"], read_only=True, width=64),
    Register("time", CSRS["time"], read_only=True, width=64),
    Register("instret", CSRS["instret"], read_only=True, width=64),
    Register("cycleh", CSRS["cycleh"], read_only=True, host="cycle", shift=32, bits=32),
    Register("timeh", CSRS["timeh"], read_only=True, host="time", shift=32, bits=32),
    Register("instreth", CSRS["instreth"], read_only=True, host="instret", shift=32, bits=32),
)

BY_NUMBER = {register.number: register for register in REGISTERS}
BY_NAME = {register.name: register for register in REGISTERS}


class ControlRegisters:
    """The control and status registers of one machine."""

    def __init__(self, options: Options = Options(),
                 clock: Callable[[], int] | None = None) -> None:
        self.options = options
        self.mask = (1 << options.xlen) - 1
        self.clock = _wall_clock if clock is None else clock
        self.journal = None  # the machine puts `core/history.py` here
        # `time` is not among them: it is read from the clock.
        self.values = {register.name: 0 for register in REGISTERS
                       if not register.host and register.name != "time"}

    # -------------------------------------------------------- what a program does

    def read(self, number: int) -> int:
        """The value of a register, as wide as the machine."""
        return self._value(self._register(number))

    def write(self, number: int, value: int) -> None:
        """What `csrrw` and its relatives do; a read-only register is refused."""
        register = self._register(number)
        if register.read_only:
            raise traps.Trap(traps.ILLEGAL_INSTRUCTION, number,
                             "Cannot write to the read-only control register "
                             f"{register.name}")
        self._store(register, value)

    # -------------------------------------------------------- what the machine does

    def poke(self, name: str, value: int) -> None:
        """Write by the machine's own right: the counters, and the registers a
        trap fills in. No rule of the program applies."""
        register = BY_NAME[name]
        if register.host:  # a window keeps the rest of its host
            self._store(register, value)
        else:
            self._keep(name)
            self.values[name] = value & self._limit(register)

    def retire(self) -> None:
        """One instruction has been carried out."""
        limit = (1 << 64) - 1
        self.values["cycle"] = (self.values["cycle"] + 1) & limit
        self.values["instret"] = (self.values["instret"] + 1) & limit

    def rounding_mode(self) -> int:
        """The mode of `frm`, which a floating point instruction uses for `dyn`."""
        return (self.values["fcsr"] >> FRM_SHIFT) & ((1 << FRM_BITS) - 1)

    def raise_flags(self, flags: int) -> None:
        """Add the exception flags of an operation to `fcsr`."""
        self._keep("fcsr")
        self.values["fcsr"] |= flags & ((1 << FFLAGS_BITS) - 1)

    def _keep(self, name: str) -> None:
        """Write down what a register holds, for a step back."""
        if self.journal is not None:
            self.journal.record(Kind.CSR, name, self.values[name])

    # ----------------------------------------------------------------- the parts

    def _register(self, number: int) -> Register:
        register = BY_NUMBER.get(number)
        if register is None:
            raise traps.Trap(traps.ILLEGAL_INSTRUCTION, number,
                             f"No such control register 0x{number:03x}")
        return register

    def _limit(self, register: Register) -> int:
        """How many bits the register itself holds."""
        return (1 << (register.width or self.options.xlen)) - 1

    def _held(self, register: Register) -> int:
        """Everything the register holds, before the width of the machine cuts
        it: a window reads the whole of its host from here."""
        return self.clock() if register.name == "time" else self.values[register.name]

    def _value(self, register: Register) -> int:
        if register.host:
            held = self._held(BY_NAME[register.host])
            return (held >> register.shift) & ((1 << register.bits) - 1)
        return self._held(register) & self.mask

    def _store(self, register: Register, value: int) -> None:
        if register.host:
            host = BY_NAME[register.host]
            window = ((1 << register.bits) - 1) << register.shift
            kept = self.values[host.name] & ~window
            self._store(host, kept | ((value << register.shift) & window))
            return
        writable = self._limit(register) if register.writable is None else register.writable
        self._keep(register.name)
        self.values[register.name] = ((self.values[register.name] & ~writable)
                                      | (value & writable))
