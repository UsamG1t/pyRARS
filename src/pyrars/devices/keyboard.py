"""The keyboard and the display: four registers of MMIO, a key typed, a character
shown after a delay.

The protocol is the one of RARS (R-DEV-KBD, read from the byte code of
`tools/KeyboardAndDisplaySimulator` and verified again 2026-10-07):

    MMIO+0x0  RcvCtrl   bit 0 ready: a key is waiting; bit 1: ask for an interrupt
    MMIO+0x4  RcvData   the key, in its low 8 bits
    MMIO+0x8  TxCtrl    bit 0 ready: the display will take a character
    MMIO+0xc  TxData    the character to show, in its low 8 bits

A key typed sets the ready bit of `RcvCtrl` and puts the key in `RcvData`; reading
`RcvData` clears that ready bit, so the program sees each key once. Only the last
key typed is kept: the one before is lost if the program did not read it, exactly
as in RARS - a front-end that feeds a text watches the ready bit and types the next
key when the program has taken the one before.

Writing `TxData` while the display is ready clears the ready bit and starts a
delay, counted in instructions carried out (which is what replaces the text-fetch
observation of RARS). The instruction that wrote the character does not count, as
it does not in RARS, where its fetch has already passed; so a delay of three means
three instructions after it. When the delay is over the character appears, the
ready bit comes back, and an interrupt is asked for if the control register wants
one. The
length of the delay is fixed, drawn evenly, or drawn from a normal distribution -
the three techniques of RARS, over our own seedable stream (DEV-50), so a test of a
drawn delay repeats.

Two characters mean something of their own, as in RARS:
  - 12 (form feed) clears the display;
  - 7 (bell) switches the display to the mode in which a character goes where it is
    told: the X of the place is the bits 20..31 of the word, the Y its bits 8..19,
    both cut to the size of the display.

The display of RARS is as large as its window; a model has no window, so the size
is an option, 80 by 25 by default (DEV-56).
"""

from collections.abc import Callable

from pyrars.devices.base import Connection, Model

# The registers, counted from the base of the device area.
RECEIVER_CONTROL = 0x0
RECEIVER_DATA = 0x4
TRANSMITTER_CONTROL = 0x8
TRANSMITTER_DATA = 0xC

READY = 0x1  # bit 0 of a control register
INTERRUPT = 0x2  # bit 1: the program asks to be told

# What a handler reads in `utval` (RARS: 0x40 for a key, 0x80 for the display).
KEY_INTERRUPT = 0x40
DISPLAY_INTERRUPT = 0x80

CLEAR_SCREEN = 12  # form feed
SET_PLACE = 7  # bell

# The lengths of the delay RARS offers on its slider; the fifth is its default.
DELAYS = (1, 2, 3, 4, 5, 10, 20, 30, 40, 50, 100, 150, 200, 300, 400, 500, 600, 700,
          800, 900, 1000, 1500, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000,
          20000, 40000, 60000, 80000, 100000, 200000, 400000, 600000, 800000, 1000000)
DEFAULT_DELAY = DELAYS[4]

TECHNIQUES = ("fixed", "uniform", "normal")

ROWS = 25
COLUMNS = 80


class KeyboardDisplay(Model):
    """The keyboard and the display of one machine."""

    name = "keyboard"
    counts = True  # the delay of the display is counted in instructions
    offset = RECEIVER_CONTROL
    size = 0x10

    def __init__(self, delay: int = DEFAULT_DELAY, technique: str = "fixed",
                 rows: int = ROWS, columns: int = COLUMNS,
                 show_after_delay: bool = True) -> None:
        super().__init__()
        if technique not in TECHNIQUES:
            raise ValueError(f'"{technique}": the delay is {" or ".join(TECHNIQUES)}')
        if delay < 1 or rows < 1 or columns < 1:
            raise ValueError("a delay, a number of rows and of columns are all at least 1")
        self.delay = delay
        self.technique = technique
        self.rows = rows
        self.columns = columns
        self.show_after_delay = show_after_delay  # RARS shows at the end of the delay

        self.text = ""  # what the display holds while it scrolls
        self.grid: list[list[str]] = []  # and while a character goes where it is told
        self.place = (0, 0)  # where the next character goes: column, row
        self.told_where = False  # the mode the bell switches on
        self.counting = False  # a delay is running
        self.counted = 0
        self.limit = 0
        self.waiting = 0  # the word whose character is to be shown
        self.watchers: list[Callable[[], None]] = []

    # ------------------------------------------------------------- the machine

    def reset(self) -> None:
        self.text = ""
        self.grid = []
        self.place = (0, 0)
        self.told_where = False
        self.counting = False
        self.counted = self.limit = self.waiting = 0
        if self.connection is not None:
            self._poke(RECEIVER_CONTROL, 0)
            self._poke(RECEIVER_DATA, 0)
            # The display takes a character as soon as it is there, as in RARS,
            # where the ready bit is set when the tool is connected.
            self._poke(TRANSMITTER_CONTROL, READY)
            self._poke(TRANSMITTER_DATA, 0)
        self._changed()

    def read(self, address: int, size: int) -> int:
        value = self.connection.memory.peek(address, size)
        if address == self._address(RECEIVER_DATA):
            # The program has taken the key: the next one may come.
            self._control(RECEIVER_CONTROL, self._register(RECEIVER_CONTROL) & ~READY)
        return value

    def write(self, address: int, size: int, value: int) -> None:
        self.connection.memory.poke(address, size, value)
        if address != self._address(TRANSMITTER_DATA):
            return  # a control register: the program sets its own bits
        if not self._register(TRANSMITTER_CONTROL) & READY:
            return  # the display is busy; the character is lost, as in RARS
        self._control(TRANSMITTER_CONTROL,
                      self._register(TRANSMITTER_CONTROL) & ~READY)
        self.waiting = self.connection.memory.peek(self._address(TRANSMITTER_DATA), 4)
        if not self.show_after_delay:
            self._show(self.waiting)
        self.counting = True
        # The instruction that wrote the character does not count: in RARS the
        # fetch of that instruction has already passed when the write arrives, so
        # the delay is counted from the instruction after it.
        self.counted = -1
        self.limit = self._delay()

    def on_retire(self, count: int) -> None:
        """Instructions have been carried out: the delay of the display runs on."""
        if not self.counting:
            return
        self.counted += count
        if self.counted < self.limit:
            return
        if self.show_after_delay:
            self._show(self.waiting)
        self.counting = False
        control = self._register(TRANSMITTER_CONTROL) | READY
        self._control(TRANSMITTER_CONTROL, control)
        if control != READY:  # the program asked to be told (RARS: `control != 1`)
            self.connection.interrupts.external(DISPLAY_INTERRUPT)

    # ------------------------------------------------------- the front-end side

    def type_key(self, key: str | int) -> None:
        """A key was typed. Only the last one is kept, as in RARS: a front-end that
        feeds a text waits for the program to read the one before."""
        code = ord(key) if isinstance(key, str) else key
        self._poke(RECEIVER_DATA, code & 0xFF)
        control = self._register(RECEIVER_CONTROL) | READY
        self._control(RECEIVER_CONTROL, control)
        if control != READY:
            self.connection.interrupts.external(KEY_INTERRUPT)
        self._changed()

    @property
    def waiting_for_a_key(self) -> bool:
        """Whether the program has read the key typed before."""
        return not self._register(RECEIVER_CONTROL) & READY

    def shown(self) -> str:
        """What the display holds, as lines of text."""
        if self.told_where:
            return "\n".join("".join(row) for row in self.grid)
        return self.text

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Watch the display; the answer ends the watch. With no watcher a change
        costs nothing (INV-Z)."""
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    # ------------------------------------------------------------ the display

    def _show(self, word: int) -> None:
        """One character of a word written to `TxData`."""
        code = word & 0xFF
        if code == CLEAR_SCREEN:
            self._clear()
        elif code == SET_PLACE:
            if not self.told_where:
                self.told_where = True
                self._clear()
            column = (word & 0xFFF00000) >> 20
            row = (word & 0x000FFF00) >> 8
            self.place = (min(max(column, 0), self.columns - 1),
                          min(max(row, 0), self.rows - 1))
        elif self.told_where:
            column, row = self.place
            self.grid[row][column] = chr(code)
            # The place moves on, and stands still at the last one of the display:
            # characters then overwrite it, as they do in RARS.
            if column + 1 < self.columns:
                self.place = (column + 1, row)
            elif row + 1 < self.rows:
                self.place = (0, row + 1)
        else:
            self.text += chr(code)
        self._changed()

    def _clear(self) -> None:
        self.text = ""
        self.grid = [[" "] * self.columns for _ in range(self.rows)]
        self.place = (0, 0)

    # -------------------------------------------------------------- the parts

    def _delay(self) -> int:
        """How many instructions the display takes for one character."""
        if self.technique == "fixed":
            return self.delay
        if self.technique == "uniform":
            return self.connection.random.randrange(self.delay) + 1
        return int(abs(self.connection.random.gauss(0, 1) * self.delay) + 1)

    def _address(self, register: int) -> int:
        return self.connection.config.mmio_base + register

    def _register(self, register: int) -> int:
        return self.connection.memory.peek(self._address(register), 4)

    def _poke(self, register: int, value: int) -> None:
        self.connection.memory.poke(self._address(register), 4, value)

    def _control(self, register: int, value: int) -> None:
        """A control register changes; the bits the program set stay as they are."""
        self._poke(register, value)
        self._changed()

    def _changed(self) -> None:
        for watcher in self.watchers:
            watcher()
