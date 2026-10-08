"""The digital lab: two seven-segment displays, a keyboard of sixteen keys and a
counter that asks for attention again and again.

The protocol is the one of RARS (R-DEV-DLAB, read from the byte code of
`tools/DigitalLabSim` and verified again 2026-10-08). Its registers are single
bytes, which a program reaches with `sb` and `lb`:

    MMIO+0x10  the right display: bit 0 is the segment a ... bit 6 g, bit 7 the dot
    MMIO+0x11  the left display, the same bits
    MMIO+0x12  which row of the keyboard to look at (bits 0..3), and the bits 4..7,
               any of which asks to be told when a key is pressed
    MMIO+0x13  anything but zero starts the counter; zero stops it
    MMIO+0x14  the key that is pressed, written by the device: the bit of its row
               in the low half and the bit of its column in the high half, or zero

A key stays pressed until it is pressed again - a keyboard of RARS is a row of
buttons that stay down. Pressing one asks for the external interrupt 0x200 where
the program said it wanted to be told. The code of the key appears in `0x14` when
the program next says which row to look at, and only when that row is EXACTLY the
row of the key: a program that asks for every row at once (0xf) is told nothing,
which is what RARS does.

The counter counts notices: every instruction carried out, and every read or write
of the four registers 0x10..0x13 - the register of the key is not among them. The
thirty-first notice asks for the timer interrupt 0x100 and the count starts over,
so the period is 31. In RARS the notices are the fetches of the instructions and
the accesses of the same four addresses, and `on_retire` is what replaces the
fetches (decision of 2026-10-07).
"""

from collections.abc import Callable

from pyrars.devices.base import Model

RIGHT_DISPLAY = 0x10
LEFT_DISPLAY = 0x11
KEYBOARD_ROW = 0x12
COUNTER = 0x13
KEYBOARD_KEY = 0x14

# What the counter of notices watches: its own four registers, and nothing else.
WATCHED = (RIGHT_DISPLAY, LEFT_DISPLAY, KEYBOARD_ROW, COUNTER)

KEY_INTERRUPT = 0x200  # external: a key was pressed
COUNTER_INTERRUPT = 0x100  # timer: the counter came round again

KEYS = 16
PERIOD = 31  # notices between two interrupts of the counter

# The code of every key: the bit of its row, and the bit of its column shifted up.
KEY_CODES = tuple((1 << (key // 4)) | (1 << (4 + key % 4)) for key in range(KEYS))

# The segments of a display, from the bit 0 up.
SEGMENTS = ("a", "b", "c", "d", "e", "f", "g", "dot")


class DigitalLab(Model):
    """The digital lab of one machine."""

    name = "lab"
    counts = True  # the counter counts instructions as well
    offset = RIGHT_DISPLAY
    size = 5  # 0x10 .. 0x14

    def __init__(self) -> None:
        super().__init__()
        self.left = 0  # the segments each display holds
        self.right = 0
        self.pressed: int | None = None  # the key that is down, 0..15
        self.key_interrupts = False  # whether a press asks for attention
        self.counter_on = False
        self.counter = 0  # notices still to go
        self.watchers: list[Callable[[], None]] = []

    def reset(self) -> None:
        self.left = self.right = 0
        self.pressed = None
        self.key_interrupts = False
        self.counter_on = False
        self.counter = 0
        if self.connection is not None:
            for register_ in (*WATCHED, KEYBOARD_KEY):
                self._poke(register_, 0)
        self._changed()

    # ------------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        value = self.connection.memory.peek(address, size)
        self._noticed(address)
        return value

    def write(self, address: int, size: int, value: int) -> None:
        self.connection.memory.poke(address, size, value)
        which = self._which(address)
        if which == RIGHT_DISPLAY:
            self.right = value & 0xFF
            self._changed()
        elif which == LEFT_DISPLAY:
            self.left = value & 0xFF
            self._changed()
        elif which == KEYBOARD_ROW:
            self._select(value)
        elif which == COUNTER:
            self.counter_on = bool(value & 0xFF)
            self.counter = PERIOD - 1 if self.counter_on else 0
            self._changed()
        self._noticed(address)

    def on_retire(self, count: int) -> None:
        """Every instruction carried out is a notice for the counter."""
        for _ in range(count):
            self._tick()

    # ------------------------------------------------------- the front-end side

    def press(self, key: int) -> None:
        """A key was pressed. A key that is already down goes up instead, whichever
        key is named: the keyboard of RARS is a row of buttons that stay down and
        the next press releases."""
        if not 0 <= key < KEYS:
            raise ValueError(f"{key}: the keyboard has the keys 0 to {KEYS - 1}")
        if self.pressed is not None:
            self.release()
            return
        self.pressed = key
        if self.key_interrupts:
            self.connection.interrupts.external(KEY_INTERRUPT)
        self._changed()

    def release(self) -> None:
        """The key that was down goes up, and the register says nothing is pressed."""
        self.pressed = None
        self._poke(KEYBOARD_KEY, 0)
        self._changed()

    def lit(self, value: int) -> tuple[str, ...]:
        """Which segments a display holds, for whoever draws it."""
        return tuple(name for index, name in enumerate(SEGMENTS) if value >> index & 1)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    # ---------------------------------------------------------------- the parts

    def _select(self, row: int) -> None:
        """The program says which row of the keyboard to look at."""
        code = 0
        if self.pressed is not None and 1 << (self.pressed // 4) == row & 0xF:
            code = KEY_CODES[self.pressed]
        self._poke(KEYBOARD_KEY, code)
        self.key_interrupts = bool(row & 0xF0)
        self._changed()

    def _noticed(self, address: int) -> None:
        """An access of the registers the counter watches is a notice as well."""
        if self._which(address) in WATCHED:
            self._tick()

    def _tick(self) -> None:
        if not self.counter_on:
            return
        if self.counter > 0:
            self.counter -= 1
            return
        self.counter = PERIOD - 1
        self.connection.interrupts.timer(COUNTER_INTERRUPT)

    def _which(self, address: int) -> int:
        """Which register an address is, counted from the base of the area."""
        return address - self.connection.config.mmio_base

    def _address(self, register_: int) -> int:
        return self.connection.config.mmio_base + register_

    def _poke(self, register_: int, value: int) -> None:
        self.connection.memory.poke(self._address(register_), 1, value)

    def _changed(self) -> None:
        for watcher in self.watchers:
            watcher()
