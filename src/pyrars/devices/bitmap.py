"""The bitmap display: a piece of memory seen as a picture.

One word of memory is one unit of the picture, row by row, and the colour of a unit
is the low 24 bits of that word: red, green, blue. The display watches the words of
its range and keeps a copy of them, so that whoever draws it - a window, or a test -
reads the picture from the device and hears which unit changed.

This is no device of MMIO: it answers no address and a program talks to it by
writing into memory, exactly as in RARS (R-DEV-BITMAP, read from the byte code of
`tools/BitmapDisplay` and verified again 2026-10-08, where the tool watches the
range and takes the WORD of memory the written address belongs to, not the value
written).

The place of the picture is the base of the data segment, the global pointer, the
start of the data of a program (the default), the top of the heap or the area of
the devices - the five choices of RARS, named here, because their addresses differ
from one memory configuration to another, and it has to be the address of a word, as
it has to be in RARS. The size is given in units of the picture and in pixels of a
unit, as RARS gives it. A picture larger than what is left of the memory is simply
never filled past its last word.
"""

from collections.abc import Callable

from pyrars.core.memory import ADDRESS_MASK, Access, MemAccess
from pyrars.devices.base import Connection, Model

# The places of RARS, by the name of the place in the memory configuration.
PLACES = {
    "data": "data_segment_base",
    "global": "global_pointer",
    "static": "data_base",  # the data of a program: what RARS starts with
    "heap": "heap_base",
    "devices": "mmio_base",
}

# What RARS offers, and starts with: a picture of 512 by 256 pixels of one word each.
WIDTHS = (64, 128, 256, 512, 1024)
UNITS = (1, 2, 4, 8, 16, 32)
WIDTH = 512
HEIGHT = 256


class BitmapDisplay(Model):
    """The bitmap display of one machine."""

    name = "bitmap"
    counts = False  # it hears of writes, not of instructions

    def __init__(self, place: str | int = "static", width: int = WIDTH,
                 height: int = HEIGHT, unit_width: int = 1, unit_height: int = 1) -> None:
        super().__init__()
        if isinstance(place, str) and place not in PLACES:
            raise ValueError(f'"{place}": the picture lies at one of '
                             f'{", ".join(sorted(PLACES))}, or at an address')
        for value in (width, height, unit_width, unit_height):
            if value < 1:
                raise ValueError("a size of the picture is at least one pixel")
        self.place = place
        self.width = width
        self.height = height
        self.unit_width = unit_width
        self.unit_height = unit_height
        self.columns = width // unit_width
        self.rows = height // unit_height
        self.base = 0
        self.frame = [0] * (self.columns * self.rows)
        self.watchers: list[Callable[[int | None], None]] = []
        self._unwatch: Callable[[], None] | None = None

    # ------------------------------------------------------------- the machine

    def connect(self, connection: Connection) -> None:
        if self._unwatch is not None:
            self._unwatch()
        self.base = (getattr(connection.config, PLACES[self.place])
                     if isinstance(self.place, str) else self.place) & ADDRESS_MASK
        if self.base % 4:
            raise ValueError(f"0x{self.base:08x}: the picture starts at a word")
        high = self.base + 4 * len(self.frame) - 1
        self._unwatch = connection.memory.subscribe(Access.WRITE, self._wrote,
                                                    self.base, high)
        super().connect(connection)

    def reset(self) -> None:
        """The picture is what the memory holds now."""
        if self.connection is not None:
            memory = self.connection.memory
            self.frame = [memory.peek(self.base + 4 * index, 4)
                          for index in range(self.columns * self.rows)]
        else:
            self.frame = [0] * (self.columns * self.rows)
        self._changed(None)

    def _wrote(self, access: MemAccess) -> None:
        """A word of the picture was written. The word of memory is what counts, not
        the value of the access: a program may have written a single byte of it.

        The range watched holds exactly the words of the picture and starts at one,
        so the word written is always a unit of it.
        """
        address = access.address & ~3
        index = (address - self.base) // 4
        self.frame[index] = self.connection.memory.peek(address, 4)
        self._changed(index)

    # --------------------------------------------------------- what a viewer does

    def looks(self) -> dict[str, object]:
        """The picture itself: every unit as the colour it holds.

        A copy, taken while the thread of the run holds it - whoever draws it has
        its own thread, and a list that was being written to as it was read would
        tear.
        """
        return {"units": tuple(self.frame), "columns": self.columns,
                "rows": self.rows, "unit_width": self.unit_width,
                "unit_height": self.unit_height}

    def state(self) -> dict[str, object]:
        painted = sum(1 for word in self.frame if word)
        return {
            "picture": f"0x{self.base:08x}, {self.columns} by {self.rows} units",
            "unit": f"{self.unit_width} by {self.unit_height} pixels",
            "painted": f"{painted} of {len(self.frame)}",
        }

    def unit(self, column: int, row: int) -> int:
        """The word of one unit of the picture."""
        return self.frame[row * self.columns + column]

    def units(self) -> list[list[int]]:
        """The picture, row by row."""
        return [self.frame[row * self.columns:(row + 1) * self.columns]
                for row in range(self.rows)]

    def colour(self, word: int) -> tuple[int, int, int]:
        """The colour of a word: red, green and blue, as RARS reads them (the
        highest byte is no part of it)."""
        return (word >> 16) & 0xFF, (word >> 8) & 0xFF, word & 0xFF

    def subscribe(self, callback: Callable[[int | None], None]) -> Callable[[], None]:
        """Watch the picture. The watcher is told which unit changed, or None when
        the whole picture did."""
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    def _changed(self, index: int | None) -> None:
        for watcher in self.watchers:
            watcher(index)
