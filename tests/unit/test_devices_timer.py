"""The timer: the time a program reads, and the time it wants to be told of.

Expected values are the verified protocol of RARS (R-DEV-TIMER, read from the byte
code of `tools/TimerTool` 2026-10-08): the two 64-bit registers at MMIO+0x18 and
+0x20, the timer interrupt 0x10, the two bits that must be set for it to be heard
(0x10 of `uie` and 0x1 of `ustatus`), and one interrupt per write of `timecmp`.
The halves of `timecmp` each replace their own half, where RARS has two artifacts
of its language (DEV-57), and the clock is the one the machine was given, so a run
repeats (INV-D).
"""

import pytest

from pyrars.core import traps
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DeviceBus, make
from pyrars.devices.timer import (GLOBAL_ENABLE, INTERRUPT, TIME, TIMECMP, TIMER_ENABLE,
                                  Timer)
from pyrars.isa.memory import DEFAULT
from pyrars.isa.registers import CSRS

MMIO = DEFAULT.mmio_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def never() -> int:
    raise AssertionError("the virtual mode must not ask the clock")


def timer(times=(0,), allow: bool = True, **options) -> tuple[Machine, Timer]:
    """A machine whose clock says what the test wants, with the timer attached."""
    ticks = iter(times)
    last = [0]

    def clock() -> int:
        last[0] = next(ticks, last[0])
        return last[0]

    device = Timer(**options)
    bus = DeviceBus([device])
    machine = Machine(Options(), clock=never if options.get("mode") == "virtual" else clock,
                      bus=bus)
    bus.connect(machine)
    if allow:  # the program says it wants to be told
        machine.csr.write(CSRS["uie"], TIMER_ENABLE)
        machine.csr.write(CSRS["ustatus"], GLOBAL_ENABLE)
    return machine, device


def read(machine: Machine, which: int, size: int = 4) -> int:
    return machine.memory.read(MMIO + which, size)


def put(machine: Machine, which: int, value: int, size: int = 4) -> None:
    machine.memory.write(MMIO + which, size, value)


# ------------------------------------------------------------------- the clock


def test_the_time_comes_from_the_clock_of_the_machine():
    machine, device = timer(times=(100, 130, 175))  # the start, then two reads
    assert read(machine, TIME) == 30
    assert read(machine, TIME) == 75
    assert device.started == 100  # the clock was asked once when it started


def test_the_time_is_a_number_of_64_bits():
    machine, device = timer(times=(0, 0x1_0000_0005))
    assert read(machine, TIME) == 5
    assert read(machine, TIME + 4) == 1


def test_the_virtual_clock_counts_instructions():
    machine, device = timer(mode="virtual", step=3)
    device.on_retire(4)
    assert read(machine, TIME) == 12  # and the clock was never asked


def test_the_time_stands_still_while_the_timer_is_paused():
    machine, device = timer(times=(0, 50, 50, 90))
    device.pause()  # the clock said 50
    assert read(machine, TIME) == 50
    assert read(machine, TIME) == 50
    device.play()  # from where it stopped; the clock says 50 again
    assert read(machine, TIME) == 50 + (90 - 50)


def test_a_clock_nobody_knows():
    with pytest.raises(ValueError, match="wall or virtual"):
        Timer(mode="sundial")
    with pytest.raises(ValueError, match="at least one millisecond"):
        Timer(mode="virtual", step=0)


# ----------------------------------------------------------------- the comparison


def test_the_timer_asks_for_attention_when_the_time_is_there():
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP, 5)
    device.on_retire(4)
    assert machine.pending.timer is None
    device.on_retire(1)
    assert machine.pending.timer == INTERRUPT
    assert machine.pending.external is None


def test_the_timer_is_silent_until_the_program_allows_it():
    machine, device = timer(mode="virtual", allow=False)
    put(machine, TIMECMP, 1)
    device.on_retire(10)
    assert machine.pending.timer is None
    machine.csr.write(CSRS["uie"], TIMER_ENABLE)
    device.on_retire(1)
    assert machine.pending.timer is None  # `ustatus` still says no
    machine.csr.write(CSRS["ustatus"], GLOBAL_ENABLE)
    device.on_retire(1)
    assert machine.pending.timer == INTERRUPT


def test_the_timer_asks_once_for_every_time_it_is_given():
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP, 2)
    device.on_retire(5)
    assert machine.pending.timer == INTERRUPT
    machine.pending.timer = None  # the machine took it
    device.on_retire(5)
    assert machine.pending.timer is None  # nothing new was asked for
    put(machine, TIMECMP, 20)  # the program asks again
    device.on_retire(10)
    assert machine.pending.timer == INTERRUPT


def test_a_paused_timer_asks_for_nothing():
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP, 1)
    device.pause()
    device.on_retire(10)
    assert machine.pending.timer is None


# ------------------------------------------------------------------ the halves


def test_each_half_of_the_time_asked_for_replaces_its_own():
    """RARS puts the low half in with a sign extension of Java and ADDS the high
    half to what is there, because its mask promotes to -1 (DEV-57). Here the low
    half replaces the low half and the high one the high one."""
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP + 4, 2)
    put(machine, TIMECMP, 0x80000000)
    assert device.timecmp == 0x2_80000000
    put(machine, TIMECMP + 4, 3)  # again: it replaces, it does not add
    assert device.timecmp == 0x3_80000000
    put(machine, TIMECMP, 7)
    assert device.timecmp == 0x3_00000007


def test_the_whole_time_asked_for_can_be_written_at_once():
    """Which a 64-bit machine does with one `sd`."""
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP, 0x1_0000_0002, size=8)
    assert device.timecmp == 0x1_0000_0002


def test_writing_the_time_itself_changes_nothing():
    """The time is worked out, not kept: a program may write there and the next
    read says what the clock says. The time asked for is untouched by it."""
    machine, device = timer(mode="virtual", step=1)
    put(machine, TIME, 500)
    put(machine, TIME + 4, 500)
    assert (device.timecmp, device.armed) == (0, False)
    device.on_retire(3)
    assert read(machine, TIME) == 3


# ------------------------------------------------------------- what is around


def test_the_registers_live_in_memory():
    machine, device = timer(mode="virtual")
    device.on_retire(7)
    read(machine, TIME)  # a read brings the cells up to date
    assert machine.memory.peek(MMIO + TIME, 4) == 7
    put(machine, TIMECMP, 9)
    assert machine.memory.peek(MMIO + TIMECMP, 4) == 9


def test_a_reset_starts_the_time_over():
    machine, device = timer(mode="virtual")
    put(machine, TIMECMP, 3)
    device.on_retire(10)
    device.reset()
    assert (device.timecmp, device.armed) == (0, False)
    assert read(machine, TIME) == 0


def test_the_timer_is_counted_by_the_machine_itself():
    """The whole way round: the simulator counts, the timer asks, the machine takes
    the event and goes to the handler."""
    machine, device = timer(mode="virtual")
    handler = TEXT + 0x100
    machine.memory.poke(handler, 4, NOP)
    machine.csr.write(CSRS["utvec"], handler)
    for index in range(8):
        machine.memory.poke(TEXT + 4 * index, 4, NOP)
    put(machine, TIMECMP, 3)
    simulator = Simulator(machine)
    for _ in range(3):
        simulator.step()
    assert machine.pending.timer == INTERRUPT
    event = traps.take(machine)
    assert event.handled is True and machine.x.pc == handler
    assert machine.csr.read(CSRS["ucause"]) == traps.TIMER_INTERRUPT
    assert machine.csr.read(CSRS["utval"]) == INTERRUPT


def test_a_watcher_is_told_of_a_change():
    machine, device = timer(mode="virtual")
    changes = []
    stop = device.subscribe(lambda: changes.append(device.timecmp))
    put(machine, TIMECMP, 4)
    assert changes == [4]
    stop()
    put(machine, TIMECMP, 5)
    assert changes == [4]


def test_the_device_is_known_by_name():
    assert isinstance(make("timer"), Timer)
    assert make("timer", mode="virtual", step=2).step == 2
