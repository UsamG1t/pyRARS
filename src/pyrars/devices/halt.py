"""The halt register: a program says it is done by writing to an address.

    MMIO+0x28  write a code, and the machine stops with it

This is how the test stands of real machines are talked to - a program that cannot
use the services of an environment, or does not want to, needs some way of saying
"I am finished, and this is how it went". A write here ends the run exactly as the
services 10 and 93 do, with the code that was written.

No device of RARS does this; it is ours (DEV-59), and it costs nothing, because the
simulator already stops when something says the program is done.
"""

from pyrars.core.syscalls import Exited
from pyrars.devices.base import Model

HALT = 0x28


class Halt(Model):
    """The halt register of one machine."""

    name = "halt"
    counts = False
    offset = HALT
    size = 4

    def state(self) -> dict[str, object]:
        return {"last written": self.connection.memory.peek(self._address(), 4)
                if self.connection is not None else 0}

    def _address(self) -> int:
        return self.connection.config.mmio_base + HALT

    def read(self, address: int, size: int) -> int:
        """What was written last, which says nothing of its own."""
        return self.connection.memory.peek(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        self.connection.memory.poke(address, size, value)
        raise Exited(value)
