"""The controller of direct access to memory: copying while the program runs on.

    MMIO+0x30  from    the address the words are read from
    MMIO+0x34  to      the address they are written to
    MMIO+0x38  words   how many words to copy
    MMIO+0x3c  control bit 0 start, and 1 while it is still copying
                       bit 1 ask for an interrupt when the copying ends
                       bit 2 the last copying was refused an address

A program writes the three numbers, writes the start bit, and goes on with its own
work; the controller copies a few words for every instruction carried out - the
instruction that started it among them, for the hardware begins at once - and when
it is done the start bit reads as zero. A program either waits for that bit or asks
to be told with an interrupt (0x400, an external event).

This is no device of RARS: it is ours, and it is here because nothing else in the
simulator shows that hardware works at the same time as the processor - which is
where waiting on a flag, waiting on an interrupt and reading a buffer that is still
being filled all come from.

The copying goes word by word from the lower address up, so a copy of overlapping
ranges behaves like one made by a program with a loop that counts up. The words are
written as a program writes them, so what was copied goes back with a step back of
the journal; what the controller has counted does not (decision of 2026-10-08).

An address the program may not touch, or one that is not a word, is refused: the
copying stops, the bit of the error is set, and the interrupt - if it was asked for
- is given anyway, because the program has to hear that the copying ended.

The control register is worked out when it is read, as the time of the timer is: a
read through the bus always brings the cell up to date first, so a program never
sees a stale one, and nothing is written to memory on every instruction.
"""

from collections.abc import Callable

from pyrars.core.traps import Trap
from pyrars.devices.base import Model

FROM = 0x30
TO = 0x34
WORDS = 0x38
CONTROL = 0x3C

BUSY = 0x1  # written: start; read: still copying
INTERRUPT = 0x2  # ask to be told when the copying ends
ERROR = 0x4  # an address was refused

ASKS = 0x400  # what a handler reads in `utval`


class DirectAccess(Model):
    """The controller of direct access of one machine."""

    name = "dma"
    counts = True  # it copies a few words for every instruction
    offset = FROM
    size = CONTROL + 4 - FROM  # 0x30 .. 0x3f

    def __init__(self, speed: int = 1) -> None:
        super().__init__()
        if speed < 1:
            raise ValueError("the controller copies at least one word per instruction")
        self.speed = speed  # words it copies for every instruction carried out
        self.busy = False
        self.error = False
        self.source = 0  # where it has got to
        self.target = 0
        self.left = 0  # words still to copy
        self.copied = 0
        self.watchers: list[Callable[[], None]] = []

    def reset(self) -> None:
        self.busy = False
        self.error = False
        self.source = self.target = self.left = self.copied = 0
        if self.connection is not None:
            for register_ in (FROM, TO, WORDS, CONTROL):
                self._poke(register_, 0)
        self._changed()

    # ------------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        if self._which(address) == CONTROL:
            self._poke(CONTROL, self._control())
        return self.connection.memory.peek(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        self.connection.memory.poke(address, size, value)
        if self._which(address) != CONTROL:
            return  # the three numbers are read when the copying starts
        if value & BUSY and not self.busy:
            self._start()
        self._poke(CONTROL, self._control())
        self._changed()

    def on_retire(self, count: int) -> None:
        """Instructions have been carried out: that many turns of copying."""
        if not self.busy:
            return
        for _ in range(self.speed * count):
            if not self.busy:
                break
            self._copy_one()
        self._changed()

    # ---------------------------------------------------------------- the parts

    def _start(self) -> None:
        self.source = self._register(FROM)
        self.target = self._register(TO)
        self.left = self._register(WORDS)
        self.copied = 0
        self.error = False
        if self.source % 4 or self.target % 4:
            self.error = True
            self._ended()
            return
        self.busy = self.left > 0
        if not self.busy:  # nothing to copy is no work at all
            self._ended()

    def _copy_one(self) -> None:
        memory = self.connection.memory
        try:
            memory.write(self.target, 4, memory.read(self.source, 4))
        except Trap:  # an address the program may not touch
            self.error = True
            self.busy = False
            self._ended()
            return
        self.source += 4
        self.target += 4
        self.copied += 1
        self.left -= 1
        if self.left == 0:
            self.busy = False
            self._ended()

    def _ended(self) -> None:
        """The copying is over, one way or the other."""
        self.busy = False
        if self._register(CONTROL) & INTERRUPT:
            self.connection.interrupts.external(ASKS)

    def _control(self) -> int:
        """What the control register reads as."""
        asked = self._register(CONTROL) & INTERRUPT
        return asked | (BUSY if self.busy else 0) | (ERROR if self.error else 0)

    def _which(self, address: int) -> int:
        return address - self.connection.config.mmio_base

    def _register(self, register_: int) -> int:
        return self.connection.memory.peek(
            self.connection.config.mmio_base + register_, 4)

    def _poke(self, register_: int, value: int) -> None:
        self.connection.memory.poke(
            self.connection.config.mmio_base + register_, 4, value)

    def state(self) -> dict[str, object]:
        return {
            "speed": f"{self.speed} word{'s' if self.speed != 1 else ''}"
                     " an instruction",
            "copying": self.busy,
            "from": f"0x{self.source:08x}",
            "to": f"0x{self.target:08x}",
            "words left": self.left,
            "words copied": self.copied,
            "refused": self.error,
        }

    def looks(self) -> dict[str, object]:
        """How far the copying has got, which is the one thing a program waiting on
        it wants to see. `from` and `to` are where it has got TO, not where it was
        told to begin: those two registers walk as it copies."""
        return {"copied": self.copied, "left": self.left, "copying": self.busy,
                "from": self.source, "to": self.target, "refused": self.error}

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    def _changed(self) -> None:
        for watcher in self.watchers:
            watcher()
