"""The timer: a clock a program can read, and a time at which it wants to be told.

The protocol is the one of RARS (R-DEV-TIMER, read from the byte code of
`tools/TimerTool` and verified again 2026-10-08):

    MMIO+0x18  time     milliseconds since the timer started, 64 bits: low word
                        first, high word at +0x1c
    MMIO+0x20  timecmp  the time at which the program wants to be told, 64 bits

When the time reaches `timecmp` the timer asks for the timer interrupt 0x10, but
only while the program allows it: the bit 0x10 of `uie` and the bit 0x1 of
`ustatus` must both be set, exactly as RARS checks them. It asks once per write of
`timecmp`: writing it again arms the timer anew.

RARS keeps a thread of its own that ticks every millisecond. This one has no
thread: the time is worked out when it is read, from the clock the machine was
given, and the comparison is made after every instruction carried out. So the
cells of `time` hold what the last read put there; a read through the bus always
refreshes them first, which is what a program sees (decision of 2026-10-07).

Besides the wall clock the timer has a mode of its own, where the time is counted
in instructions: a given number of milliseconds per instruction carried out. A test
and a run compared with another run then give the same thing (INV-D).

The two artifacts of Java in RARS's writing of `timecmp` are not reproduced
(DEV-57): each half replaces its own half.
"""

from collections.abc import Callable

from pyrars.devices.base import Model
from pyrars.isa.registers import CSRS

TIME = 0x18
TIMECMP = 0x20
WIDTH = 8  # bytes of each of the two

INTERRUPT = 0x10  # what a handler reads in `utval`
TIMER_ENABLE = 0x10  # the bit of `uie` that lets the timer be heard
GLOBAL_ENABLE = 0x1  # the bit of `ustatus` that lets anything be heard

MODES = ("wall", "virtual")
LIMIT = (1 << 64) - 1


class Timer(Model):
    """The timer of one machine."""

    name = "timer"
    counts = True  # the comparison is made after every instruction
    offset = TIME
    size = TIMECMP + WIDTH - TIME  # 0x18 .. 0x27

    def __init__(self, mode: str = "wall", step: int = 1) -> None:
        super().__init__()
        if mode not in MODES:
            raise ValueError(f'"{mode}": the timer runs on the {" or ".join(MODES)} clock')
        if step < 1:
            raise ValueError("an instruction takes at least one millisecond")
        self.mode = mode
        self.step = step  # milliseconds an instruction costs in the virtual mode
        self.running = True  # RARS waits for its Play button; a device needs none
        self.saved = 0  # milliseconds counted before the last stop
        self.started = 0  # what the clock said when it last ran on
        self.counted = 0  # instructions carried out since then (the virtual mode)
        self.timecmp = 0
        self.armed = False  # whether an interrupt is still to be asked for
        self.watchers: list[Callable[[], None]] = []

    def reset(self) -> None:
        self.saved = 0
        self.counted = 0
        self.timecmp = 0
        self.armed = False
        if self.connection is not None:
            self.started = self._now()
            for register_ in (TIME, TIME + 4, TIMECMP, TIMECMP + 4):
                self._write(register_, 0)  # the time is nothing yet
        self._changed()

    # ------------------------------------------------------------- the clock

    def time(self) -> int:
        """The milliseconds the timer has counted."""
        if not self.running:
            return self.saved
        if self.mode == "virtual":
            return (self.saved + self.counted * self.step) & LIMIT
        return (self.saved + self._now() - self.started) & LIMIT

    def _now(self) -> int:
        """What the clock says - and nothing at all in the virtual mode, where the
        time is counted in instructions and a run must repeat (INV-D)."""
        return 0 if self.mode == "virtual" else self.connection.clock()

    def state(self) -> dict[str, object]:
        return {
            "clock": self.mode + ("" if self.mode == "wall" else f" ({self.step} ms an instruction)"),
            "running": self.running,
            "time": self.time(),
            "asked for": self.timecmp,
            "armed": self.armed,
        }

    def play(self) -> None:
        """Let the time run on, from where it stopped."""
        if self.running:
            return
        self.running = True
        self.started = self._now()
        self.counted = 0
        self._changed()

    def pause(self) -> None:
        """Keep the time where it stands."""
        if not self.running:
            return
        self.saved = self.time()
        self.running = False
        self._changed()

    # ------------------------------------------------------- what a program does

    def read(self, address: int, size: int) -> int:
        which = self._which(address)
        if TIME <= which < TIME + WIDTH:
            self._write_time()  # so a program never reads a time that has stood still
        return self.connection.memory.peek(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        self.connection.memory.poke(address, size, value)
        which = self._which(address)
        if not TIMECMP <= which < TIMECMP + WIDTH:
            return  # the time itself: the next read works it out again anyway
        if which == TIMECMP and size >= WIDTH:  # the whole of it at once
            self.timecmp = value & LIMIT
        elif which == TIMECMP:  # the low half replaces the low half (DEV-57)
            self.timecmp = (self.timecmp & ~0xFFFFFFFF) | (value & 0xFFFFFFFF)
        else:
            self.timecmp = (self.timecmp & 0xFFFFFFFF) | ((value & 0xFFFFFFFF) << 32)
        self.armed = True  # every write arms the timer anew, as in RARS
        self._changed()

    def on_retire(self, count: int) -> None:
        """An instruction has been carried out: the virtual clock moves on, and the
        time is compared with what the program asked for."""
        self.counted += count
        self._compare()

    # ---------------------------------------------------------------- the parts

    def _compare(self) -> None:
        if not self.armed or not self.running or self.time() < self.timecmp:
            return
        csr = self.connection.csr
        allowed = (csr.read(CSRS["uie"]) & TIMER_ENABLE
                   and csr.read(CSRS["ustatus"]) & GLOBAL_ENABLE)
        if not allowed:  # RARS waits for the program to allow it, and so do we
            return
        self.connection.interrupts.timer(INTERRUPT)
        self.armed = False

    def _write_time(self) -> None:
        now = self.time()
        self._write(TIME, now & 0xFFFFFFFF)
        self._write(TIME + 4, now >> 32)

    def _which(self, address: int) -> int:
        return address - self.connection.config.mmio_base

    def _write(self, register_: int, value: int) -> None:
        self.connection.memory.poke(self.connection.config.mmio_base + register_, 4, value)

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self.watchers.append(callback)

        def unsubscribe() -> None:
            if callback in self.watchers:
                self.watchers.remove(callback)

        return unsubscribe

    def _changed(self) -> None:
        for watcher in self.watchers:
            watcher()
