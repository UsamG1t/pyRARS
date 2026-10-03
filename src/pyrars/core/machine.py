"""The machine: the state a program runs in.

Everything a run consists of sits here together - the memory, the two register
files, the control registers - and nothing else holds any of it. What the machine
does with an instruction is `core/executor.py`; when and how often it does it is
the simulator of stage 22.
"""

from collections.abc import Callable

from pyrars.core.csr import ControlRegisters
from pyrars.core.memory import Bus, Fetched, Memory
from pyrars.core.options import Options
from pyrars.core.regs import FloatRegisters, Registers
from pyrars.core.traps import Pending
from pyrars.isa.program import AssembledProgram


class Machine:
    """One machine, set up for one run (see `Options`)."""

    def __init__(self, options: Options = Options(), clock: Callable[[], int] | None = None,
                 bus: Bus | None = None) -> None:
        self.options = options
        self.xlen = options.xlen
        self.mask = (1 << options.xlen) - 1
        self.memory = Memory(options, bus)
        self.x = Registers(options)
        self.f = FloatRegisters()
        self.csr = ControlRegisters(options, clock)
        self.pending = Pending()  # the events waiting to be taken (core/traps.py)

    def load(self, program: AssembledProgram) -> None:
        """Put a program in memory and set the program counter where it starts."""
        self.memory.load(program)
        self.x.pc = program.entry

    def fetch(self) -> Fetched | None:
        """The instruction the program counter points at, or None where the text
        holds nothing (the program ran off its end)."""
        return self.memory.fetch(self.x.pc)
