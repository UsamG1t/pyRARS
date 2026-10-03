"""The machine: the state a program runs in.

Everything a run consists of sits here together - the memory, the two register
files, the control registers - and nothing else holds any of it. What the machine
does with an instruction is `core/executor.py`; when and how often it does it is
the simulator of stage 22.
"""

import random
from collections.abc import Callable, Sequence

from pyrars.core.csr import ControlRegisters
from pyrars.core.memory import Bus, Fetched, Memory
from pyrars.core.options import Options
from pyrars.core.regs import FloatRegisters, Registers
from pyrars.core.systemio import ConsoleIO, SystemIO
from pyrars.core.traps import Pending
from pyrars.isa.program import AssembledProgram
from pyrars.isa.registers import X_NAMES

SP = X_NAMES.index("sp")
A0, A1 = X_NAMES.index("a0"), X_NAMES.index("a1")


class Machine:
    """One machine, set up for one run (see `Options`)."""

    def __init__(self, options: Options = Options(), clock: Callable[[], int] | None = None,
                 bus: Bus | None = None, io: SystemIO | None = None) -> None:
        self.options = options
        self.xlen = options.xlen
        self.mask = (1 << options.xlen) - 1
        self.memory = Memory(options, bus)
        self.x = Registers(options)
        self.f = FloatRegisters()
        self.csr = ControlRegisters(options, clock)
        self.pending = Pending()  # the events waiting to be taken (core/traps.py)
        self.io = io if io is not None else ConsoleIO()  # the world outside
        self.heap = options.config.heap_base  # where the next `sbrk` hands out
        self.generators: dict[int, random.Random] = {}  # the streams of syscall 40

    def load(self, program: AssembledProgram, arguments: Sequence[str] = ()) -> None:
        """Put a program in memory, set the program counter where it starts, and
        hand it its arguments."""
        self.memory.load(program)
        self.x.pc = program.entry
        if arguments:
            self._hand_over(arguments)

    def _hand_over(self, arguments: Sequence[str]) -> None:
        """Where a program looks for its arguments: the texts at the top of the
        stack, then a table of the count, the pointers and a zero, whose last word
        lies at the stack pointer the program would have started with. a0 takes the
        count and a1 the table of pointers.

        The layout is the one of RARS (verified), with the words as wide as the
        machine instead of always four bytes, as the process startup of the
        standard has them (D20; part of DEV-47).
        """
        step = self.xlen // 8
        place = self.options.config.stack_base + 1
        pointers = []
        for text in arguments:
            data = text.encode() + b"\0"
            place -= len(data)
            self.memory.write_bytes(place, data)
            pointers.append(place)

        # The table lies as high as it can while each word of it is aligned: the
        # stack pointer of the configuration is a multiple of four, which is not
        # enough for the eight-byte words of a 64-bit machine.
        table = (self.options.config.stack_pointer - step * (len(pointers) + 1)) & ~(step - 1)
        for index, value in enumerate([len(pointers), *pointers, 0]):
            self.memory.write(table + step * index, step, value)
        self.x.write(SP, table)
        self.x.write(A0, len(pointers))
        self.x.write(A1, table + step)

    def fetch(self) -> Fetched | None:
        """The instruction the program counter points at, or None where the text
        holds nothing (the program ran off its end)."""
        return self.memory.fetch(self.x.pc)
