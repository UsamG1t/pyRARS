"""The block device: storage a program talks to a block at a time.

    MMIO+0x40  block    which block of the disk to work on
    MMIO+0x44  buffer   where in memory the bytes come from or go to
    MMIO+0x48  count    how many blocks to carry over
    MMIO+0x4c  control  bit 0 start, and 1 while it is still working
                        bit 1 ask for an interrupt when the work ends
                        bit 2 the last work was refused
                        bit 3 the way: 0 from the disk into memory, 1 the other way
    MMIO+0x50  blocks   how many blocks the disk holds (it only answers)
    MMIO+0x54  size     how many bytes a block holds (it only answers)

A program writes the three numbers and the start bit, then either waits for the
start bit to go out or asks to be told with an interrupt (0x800, an external
event). One block is carried over every `delay` instructions, whole, because a
block is what a disk works with; so a program that reads two blocks waits twice as
long, and a program that reads nothing waits not at all.

No device of RARS does this; it is ours (DEV-60). It is here for what nothing else
in the simulator teaches: a driver in the proper sense - the geometry asked of the
device, buffers, the choice between waiting on a flag and waiting on an interrupt,
and data that outlives the run.

The disk itself is an image of bytes handed to the device; the device never touches
a file. The command line reads a file into it before a run and writes it back after
(decision of 2026-10-08), and a test hands it an image of its own.
"""

from collections.abc import Callable

from pyrars.core.traps import Trap
from pyrars.devices.base import Model

BLOCK = 0x40
BUFFER = 0x44
COUNT = 0x48
CONTROL = 0x4C
BLOCKS = 0x50
SIZE = 0x54

BUSY = 0x1  # written: start; read: still working
INTERRUPT = 0x2  # ask to be told when the work ends
ERROR = 0x4  # the block or the buffer was refused
WRITING = 0x8  # the way: from memory to the disk

ASKS = 0x800  # what a handler reads in `utval`

DEFAULT_SIZE = 512  # bytes a block holds, as a disk of this world usually does
DEFAULT_BLOCKS = 16
DEFAULT_DELAY = 10  # instructions a block costs: storage is slow


class BlockDevice(Model):
    """The block device of one machine."""

    name = "disk"
    counts = True  # the work goes on while instructions are carried out
    offset = BLOCK
    size = SIZE + 4 - BLOCK  # 0x40 .. 0x57

    def __init__(self, blocks: int = DEFAULT_BLOCKS, block_size: int = DEFAULT_SIZE,
                 delay: int = DEFAULT_DELAY, image: bytearray | None = None) -> None:
        super().__init__()
        if blocks < 1 or block_size < 1 or delay < 1:
            raise ValueError("a disk holds at least one block of one byte, and a block "
                             "costs at least one instruction")
        self.blocks = blocks
        self.block_size = block_size
        self.delay = delay
        self.image = bytearray(blocks * block_size) if image is None else image
        if len(self.image) != blocks * block_size:
            raise ValueError(f"an image of {len(self.image)} bytes for a disk of "
                             f"{blocks} blocks of {block_size}")
        self.busy = False
        self.error = False
        self.writing = False
        self.block = 0  # the block it is working on
        self.buffer = 0  # where in memory it has got to
        self.left = 0  # blocks still to carry over
        self.counted = 0  # instructions towards the block it is working on
        self.watchers: list[Callable[[], None]] = []

    def reset(self) -> None:
        self.busy = False
        self.error = False
        self.writing = False
        self.block = self.buffer = self.left = self.counted = 0
        if self.connection is not None:
            for register_ in (BLOCK, BUFFER, COUNT, CONTROL):
                self._poke(register_, 0)
            self._poke(BLOCKS, self.blocks)  # the geometry, for a program to ask
            self._poke(SIZE, self.block_size)
        self._changed()

    # ------------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        if self._which(address) == CONTROL:
            self._poke(CONTROL, self._control())
        return self.connection.memory.peek(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        which = self._which(address)
        if which in (BLOCKS, SIZE):
            # The geometry is the device's to tell: a write to it is dropped, and
            # the cell keeps what is true.
            self._poke(BLOCKS, self.blocks)
            self._poke(SIZE, self.block_size)
            return
        self.connection.memory.poke(address, size, value)
        if which != CONTROL:
            return  # the three numbers are read when the work starts
        if value & BUSY and not self.busy:
            self._start(value)
        self._poke(CONTROL, self._control())
        self._changed()

    def on_retire(self, count: int) -> None:
        """Instructions have been carried out: the work goes on."""
        if not self.busy:
            return
        self.counted += count
        while self.busy and self.counted >= self.delay:
            self.counted -= self.delay
            self._carry_one()
        self._changed()

    # ------------------------------------------------------- the front-end side

    def state(self) -> dict[str, object]:
        return {
            "blocks": self.blocks,
            "block": f"{self.block_size} bytes",
            "delay": f"{self.delay} instruction{'s' if self.delay != 1 else ''}"
                     " a block",
            "working": self.busy,
            "way": "to the disk" if self.writing else "from the disk",
            "at block": self.block,
            "buffer": f"0x{self.buffer:08x}",
            "blocks left": self.left,
            "refused": self.error,
        }

    def looks(self) -> dict[str, object]:
        """Which block it is working on, and how many are left: a disk at work is
        a row of blocks with one of them lit."""
        return {"blocks": self.blocks, "at": self.block, "left": self.left,
                "working": self.busy, "writing": self.writing,
                "refused": self.error}

    def load(self, data: bytes) -> None:
        """Put an image on the disk: what a command line does before a run."""
        if len(data) != len(self.image):
            raise ValueError(f"an image of {len(data)} bytes for a disk of "
                             f"{len(self.image)}")
        self.image[:] = data
        self._changed()

    def saved(self) -> bytes:
        """The image as it stands: what a command line writes back after a run."""
        return bytes(self.image)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    # ---------------------------------------------------------------- the parts

    def _start(self, control: int) -> None:
        self.block = self._register(BLOCK)
        self.buffer = self._register(BUFFER)
        self.left = self._register(COUNT)
        self.writing = bool(control & WRITING)
        self.counted = 0
        self.error = False
        if self.block + self.left > self.blocks:  # past the end of the disk
            self.error = True
            self._ended()
            return
        self.busy = self.left > 0
        if not self.busy:  # nothing to carry over is no work at all
            self._ended()

    def _carry_one(self) -> None:
        """One block, whole, between the disk and the memory."""
        start = self.block * self.block_size
        memory = self.connection.memory
        try:
            if self.writing:
                self.image[start:start + self.block_size] = memory.read_bytes(
                    self.buffer, self.block_size)
            else:
                memory.write_bytes(self.buffer,
                                   bytes(self.image[start:start + self.block_size]))
        except Trap:  # a buffer the program may not touch
            self.error = True
            self._ended()
            return
        self.block += 1
        self.buffer += self.block_size
        self.left -= 1
        if self.left == 0:
            self._ended()

    def _ended(self) -> None:
        """The work is over, one way or the other."""
        self.busy = False
        if self._register(CONTROL) & INTERRUPT:
            self.connection.interrupts.external(ASKS)

    def _control(self) -> int:
        """What the control register reads as."""
        kept = self._register(CONTROL) & (INTERRUPT | WRITING)
        return kept | (BUSY if self.busy else 0) | (ERROR if self.error else 0)

    def _which(self, address: int) -> int:
        return address - self.connection.config.mmio_base

    def _register(self, register_: int) -> int:
        return self.connection.memory.peek(
            self.connection.config.mmio_base + register_, 4)

    def _poke(self, register_: int, value: int) -> None:
        self.connection.memory.poke(
            self.connection.config.mmio_base + register_, 4, value)

    def _changed(self) -> None:
        for watcher in self.watchers:
            watcher()
