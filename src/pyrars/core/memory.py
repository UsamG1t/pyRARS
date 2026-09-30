"""Memory of the machine: a sparse store of bytes and the rules of access.

The store is a dictionary of pages of 4 KiB, so a program that touches three
places costs three pages. Every access takes the same path whatever its width,
and the store itself knows nothing about what the bytes mean.

The address space is 32 bits wide in both widths of the machine: the address
2**32 + x is the address x. That is verified behaviour of RARS (2026-09-30:
writing to 0x110010000 and reading 0x10010000 give the same cell), and it is
what makes `la` work in the compact configurations of a 64-bit machine, where
the computation of an address runs past 2**32.

Which addresses a program may touch follows the memory configuration:
  - the data area, from the base of the data segment to its limit: read, write;
  - the text segment: instructions. A program reads or writes its own text only
    when `self_modifying` is set, and a write there makes the instruction be
    read anew;
  - the addresses of the devices: the bus if one is attached, plain memory
    otherwise, as in RARS;
  - anything else: "address out of range".
Every access must be aligned to its own width. Where RARS differs - it reaches
only four windows of 4 MiB, checks a load of eight bytes against four and a
store of eight bytes not at all, and words its alignment messages in four
different ways - see DEV-43, DEV-44 and DEV-45.

Sources: verified behaviour of RARS in `rars-behavior.md` (R-MEM-CFG, R-MEM-SMC,
R-FP has none of this); cause codes from the ISA manual, see `traps.py`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from pyrars.core import traps
from pyrars.core.options import Options
from pyrars.isa.codec import Decoded, decode
from pyrars.isa.program import AssembledProgram

PAGE_BITS = 12
PAGE_SIZE = 1 << PAGE_BITS
ADDRESS_MASK = (1 << 32) - 1

# The name of an access width, for the messages about alignment.
WIDTHS = {1: "byte", 2: "halfword", 4: "word", 8: "doubleword"}


class Access(Enum):
    """What a program did with the bytes; subscriptions are made per kind."""

    READ = auto()
    WRITE = auto()


class Area(Enum):
    """The part of the memory configuration an address belongs to."""

    TEXT = auto()
    DATA = auto()
    DEVICES = auto()
    NONE = auto()


@dataclass(frozen=True, slots=True)
class MemAccess:
    """One access, as the subscribers of the memory see it."""

    kind: Access
    address: int
    size: int
    value: int


@dataclass(frozen=True, slots=True)
class Fetched:
    """The instruction word at an address. `instr` is None when the word encodes
    no instruction of this width; the simulator then raises an illegal
    instruction."""

    address: int
    word: int
    instr: Decoded | None


class Fault(Exception):
    """An access the machine refuses. The simulator turns it into a trap, so
    nothing of this reaches the user of the machine (INV-E)."""

    def __init__(self, cause: int, address: int, message: str) -> None:
        super().__init__(message)
        self.cause = cause
        self.address = address
        self.message = message


class Bus(Protocol):
    """What `pyrars.devices` attaches to the addresses of the devices."""

    def read(self, address: int, size: int) -> int: ...

    def write(self, address: int, size: int, value: int) -> None: ...


@dataclass(frozen=True, slots=True)
class _Watch:
    kind: Access
    low: int
    high: int
    callback: Callable[[MemAccess], None]


class Memory:
    """The memory of one machine."""

    def __init__(self, options: Options = Options(), bus: Bus | None = None) -> None:
        self.options = options
        self.config = options.config
        self.bus = bus
        self._pages: dict[int, bytearray] = {}
        self._filled: set[int] = set()  # addresses of the text segment that hold a word
        self._fetched: dict[int, Fetched] = {}  # what fetch already read and decoded
        self._watchers: list[_Watch] = []

    # ------------------------------------------------------------- the program

    def load(self, program: AssembledProgram) -> None:
        """Put the text and the data of an assembled program in place.

        Loading is not an access of the program: it writes the text segment,
        which a program may not, and it raises no fault. A program assembled for
        another width or another configuration is refused, because its addresses
        are built into its machine code.
        """
        if program.xlen != self.options.xlen or program.mem_config != self.config.name:
            raise ValueError(
                f"the program is assembled for RV{program.xlen} and the configuration "
                f"{program.mem_config}, the machine is RV{self.options.xlen} and "
                f"{self.config.name}")
        for entry in program.text:
            self._put(entry.address, entry.word.to_bytes(4, "little"))
            self._filled.add(entry.address)
        if program.data:
            self._put(program.data_base, program.data)
        self._fetched.clear()

    # -------------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        """`size` bytes as an unsigned number; the caller extends the sign."""
        address &= ADDRESS_MASK
        area = self._allowed(address, size, Access.READ)
        if area is Area.DEVICES and self.bus is not None:
            value = self.bus.read(address, size)
        else:
            value = int.from_bytes(self._get(address, size), "little")
        if self._watchers:
            self._notify(MemAccess(Access.READ, address, size, value))
        return value

    def write(self, address: int, size: int, value: int) -> None:
        address &= ADDRESS_MASK
        area = self._allowed(address, size, Access.WRITE)
        value &= (1 << (8 * size)) - 1
        if area is Area.DEVICES and self.bus is not None:
            self.bus.write(address, size, value)
        else:
            self._put(address, value.to_bytes(size, "little"))
            if area is Area.TEXT:
                self._text_changed(address, size)
        if self._watchers:
            self._notify(MemAccess(Access.WRITE, address, size, value))

    def read_bytes(self, address: int, count: int) -> bytes:
        """A run of bytes, for the syscalls that read strings and buffers."""
        address &= ADDRESS_MASK
        if count:
            self._allowed(address, 1, Access.READ)
            self._allowed((address + count - 1) & ADDRESS_MASK, 1, Access.READ)
        return self._get(address, count)

    def write_bytes(self, address: int, data: bytes) -> None:
        address &= ADDRESS_MASK
        if data:
            self._allowed(address, 1, Access.WRITE)
            self._allowed((address + len(data) - 1) & ADDRESS_MASK, 1, Access.WRITE)
        self._put(address, data)

    def fetch(self, address: int) -> Fetched | None:
        """The instruction at an address, or None when nothing was ever put
        there, which means the program ran off the end of its text."""
        address &= ADDRESS_MASK
        if address % 4:
            raise Fault(traps.INSTRUCTION_ADDRESS_MISALIGNED, address,
                        f"Instruction address not aligned to word boundary 0x{address:08x}")
        area = self._area(address)
        if area is Area.TEXT:
            if address not in self._filled:
                return None
            cached = self._fetched.get(address)
            if cached is not None:
                return cached
        elif not (self.options.self_modifying and area is Area.DATA):
            raise Fault(traps.INSTRUCTION_ACCESS_FAULT, address,
                        "Instruction load access error")
        word = int.from_bytes(self._get(address, 4), "little")
        fetched = Fetched(address, word, decode(word, self.options.xlen))
        if area is Area.TEXT:
            self._fetched[address] = fetched
        return fetched

    # ------------------------------------------------------ what the tools do

    def peek(self, address: int, size: int) -> int:
        """The bytes at an address, whatever they are: no rules and no notice.
        For the views of the user interface, for the debugger and for tests."""
        return int.from_bytes(self._get(address & ADDRESS_MASK, size), "little")

    def poke(self, address: int, size: int, value: int) -> None:
        """Put bytes anywhere, by the same right as the loader."""
        address &= ADDRESS_MASK
        self._put(address, (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))
        if self._area(address) is Area.TEXT:
            self._text_changed(address, size)

    def subscribe(self, kind: Access, callback: Callable[[MemAccess], None],
                  low: int = 0, high: int = ADDRESS_MASK) -> Callable[[], None]:
        """Watch accesses of one kind in [low, high]; the result ends the watch.

        With no subscriber an access allocates nothing (INV-Z).
        """
        watch = _Watch(kind, low, high, callback)
        self._watchers.append(watch)

        def unsubscribe() -> None:
            if watch in self._watchers:
                self._watchers.remove(watch)

        return unsubscribe

    # ----------------------------------------------------------------- the rules

    def _area(self, address: int) -> Area:
        config = self.config
        # `text_limit` is the address of the last WORD of the text segment, while
        # the other limits are addresses of bytes.
        if config.text_base <= address <= config.text_limit + 3:
            return Area.TEXT
        if config.data_segment_base <= address <= config.data_segment_limit:
            return Area.DATA
        if config.mmio_base <= address <= config.mmap_limit:
            return Area.DEVICES
        return Area.NONE

    def _allowed(self, address: int, size: int, kind: Access) -> Area:
        """The area of an access a program may make; raises Fault otherwise."""
        reading = kind is Access.READ
        if size > 1 and address % size:
            raise Fault(traps.LOAD_ADDRESS_MISALIGNED if reading
                        else traps.STORE_ADDRESS_MISALIGNED, address,
                        f"{'Load' if reading else 'Store'} address not aligned to "
                        f"{WIDTHS[size]} boundary 0x{address:08x}")
        area = self._area(address)
        if area is Area.TEXT and not self.options.self_modifying:
            verb = "read directly from" if reading else "write directly to"
            raise Fault(traps.LOAD_ACCESS_FAULT if reading else traps.STORE_ACCESS_FAULT,
                        address, f"Cannot {verb} text segment!0x{address:08x}")
        if area is Area.NONE:
            raise Fault(traps.LOAD_ACCESS_FAULT if reading else traps.STORE_ACCESS_FAULT,
                        address, f"address out of range 0x{address:08x}")
        return area

    def _text_changed(self, address: int, size: int) -> None:
        """A write reached the text segment: the words it touched hold something
        now, and what was read of them before no longer counts."""
        first = address - address % 4
        for word in range(first, address + size, 4):
            self._filled.add(word)
            self._fetched.pop(word, None)

    def _notify(self, access: MemAccess) -> None:
        for watch in self._watchers:
            if watch.kind is access.kind and watch.low <= access.address <= watch.high:
                watch.callback(access)

    # ----------------------------------------------------------------- the store

    def _get(self, address: int, count: int) -> bytes:
        index, offset = divmod(address, PAGE_SIZE)
        if offset + count <= PAGE_SIZE:  # the usual case: one page
            page = self._pages.get(index)
            return bytes(count) if page is None else bytes(page[offset:offset + count])
        return b"".join(self._get((address + i) & ADDRESS_MASK, 1) for i in range(count))

    def _put(self, address: int, data: bytes) -> None:
        while data:
            index, offset = divmod(address & ADDRESS_MASK, PAGE_SIZE)
            page = self._pages.get(index)
            if page is None:
                page = self._pages[index] = bytearray(PAGE_SIZE)
            piece = min(len(data), PAGE_SIZE - offset)
            page[offset:offset + piece] = data[:piece]
            address += piece
            data = data[piece:]
