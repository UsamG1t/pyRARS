"""What a device is, and what of the machine it may reach.

A device is a MODEL: state and events, and nothing of a window. The panels that
show it belong to `pyrars.ui`, and a test drives the same model with no graphics at
all.

There are two ways of being attached:
  - a `Device` answers the reads and writes of its own range of addresses. Its
    registers LIVE in the memory cells of that range, as they do in RARS, and the
    device only adds the behaviour: a read that clears a ready bit, a write that
    starts a delay. So a memory view, a dump or the debugger sees the true values
    without asking the devices, and no state is kept twice.
  - a `Watcher` answers nothing and only looks at a range of memory through
    `Memory.subscribe` - which is what the bitmap display of RARS does, for it is
    no MMIO device at all.

A device reaches the machine only through the `Connection` it is given: the
interrupt slots, the memory, the control registers, the clock, a random stream of
its own and the memory configuration. It may change memory and raise interrupts;
it may not touch a register of the program or carry anything out.

Sources: R-DEV-* in `rars-behavior.md`; the decisions of 2026-10-07 in the M5
entry of the architecture spec.
"""

import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pyrars.core.memory import Memory
from pyrars.core.traps import Pending
from pyrars.isa.memory import MemoryConfig


class Interrupts:
    """The way a device asks for attention: one slot for an external event, one
    for a timer event. A slot that is already full drops the new event, as in RARS,
    and the answer says so."""

    def __init__(self, pending: Pending) -> None:
        self.pending = pending

    def external(self, value: int) -> bool:
        return self.pending.add_external(value)

    def timer(self, value: int) -> bool:
        return self.pending.add_timer(value)


@dataclass(frozen=True, slots=True)
class Connection:
    """Everything a device may reach of the machine it is attached to."""

    interrupts: Interrupts
    memory: Memory
    csr: object  # `core/csr.py` ControlRegisters: a device may READ what a handler sees
    clock: Callable[[], int]  # milliseconds, the same clock the machine reads
    random: random.Random  # seedable, so a test of a device repeats (INV-D)
    config: MemoryConfig


@runtime_checkable
class Part(Protocol):
    """What every device has, whether it answers on the bus or only watches."""

    name: str  # how the command line and the interface call it
    counts: bool  # whether it wants to hear of every instruction carried out

    def connect(self, connection: Connection) -> None: ...

    def on_retire(self, count: int) -> None: ...

    def reset(self) -> None: ...


@runtime_checkable
class Device(Part, Protocol):
    """A device that answers the reads and writes of its range.

    `offset` is counted from the base of the device area of the configuration, so
    the same device sits in the right place in every memory configuration.
    """

    offset: int
    size: int  # bytes of the range

    def read(self, address: int, size: int) -> int: ...

    def write(self, address: int, size: int, value: int) -> None: ...


class Model:
    """What the built-in devices start from: a name, no interest in instructions,
    and a connection once it is attached."""

    name = "model"
    counts = False

    def __init__(self) -> None:
        self.connection: Connection | None = None

    def connect(self, connection: Connection) -> None:
        self.connection = connection
        self.reset()

    def on_retire(self, count: int) -> None:
        """Instructions have been carried out. Only a device whose `counts` is set
        is told, because this runs on every instruction."""

    def reset(self) -> None:
        """Back to the state of a machine just started."""

    def state(self) -> dict[str, object]:
        """What the device holds, for whoever shows it: a name to a value, in the
        order a reader wants them. A device of someone else answers for itself, so
        nothing that shows devices has to know any of them."""
        return {}

    def looks(self) -> dict[str, object]:
        """What a front end needs to DRAW the device, in numbers.

        `state` is what to READ about a device - words a person reads in a row of a
        table - and for most devices that is the whole of it. A device that is a
        PICTURE, though, cannot be read: a bitmap display is its units, a
        seven-segment display is its segments, a disk is which block it is working
        on. Those are the numbers, and no device knows anything about how they are
        drawn; one that has nothing to draw says nothing here, and whoever shows
        devices shows its table and no more.
        """
        return {}
