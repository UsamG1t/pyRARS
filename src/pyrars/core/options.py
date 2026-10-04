"""What is fixed for one run of a program.

These are the parameters of a run, not constants of the implementation: they are
chosen when a program is loaded and stay until the machine is built anew. The
program cannot change them, unlike registers, memory and the control and status
registers.

The width and the memory configuration are also a contract with the assembler,
because the addresses of a program are built into its machine code: `la a0, msg`
becomes `auipc a0, 0x0fc10` only while the text lies at 0x00400000 and the data
at 0x10010000. `Memory.load` therefore refuses a program that was assembled for
another width or another configuration instead of giving wrong results.

Where the program starts is NOT here: the assembler already decided it and
`AssembledProgram.entry` carries it.

`history_depth` says how many steps can be taken back; zero means that nothing
is written down at all, which is what the command line runs with. `debug` says
that the program runs under a debugger, and then a step back also takes the
world outside back: what was read is handed out again, the files stand where
they stood. The world writes its record down either way; the flag only decides
whether a step back reads it (user decision 2026-10-04, `core/history.py`).
"""

from dataclasses import dataclass

from pyrars.isa.memory import DEFAULT, MemoryConfig


@dataclass(frozen=True, slots=True)
class Options:
    xlen: int = 32  # width of the registers, 32 or 64
    config: MemoryConfig = DEFAULT  # where the segments live
    self_modifying: bool = False  # may a program read and write its own text?
    history_depth: int = 2000  # steps that can be taken back; 0 keeps no journal
    debug: bool = False  # under a debugger: a step back takes the world back too
