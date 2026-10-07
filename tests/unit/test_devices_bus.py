"""The frame of the devices: the bus, the connection and the registry.

Expected values come from the decisions of 2026-10-07: a device answers its own
range and plain memory answers everywhere else in the area of the devices (which is
what RARS does with no tool connected), a device's registers live in the memory
cells of its range, a device reaches the machine only through its connection, and
only the devices that ask hear of every instruction carried out.
"""

import random

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DEVICES, DeviceBus, Model, make, names, register
from pyrars.devices.base import Connection, Interrupts, Part
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import CONFIGS, DEFAULT

MMIO = DEFAULT.mmio_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


class Cells(Model):
    """A device of four bytes whose register lives in memory, and which counts how
    often it was read and written."""

    name = "cells"
    offset = 0x0
    size = 4

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.writes = 0

    def read(self, address: int, size: int) -> int:
        self.reads += 1
        return self.connection.memory.peek(address, size)

    def write(self, address: int, size: int, value: int) -> None:
        self.writes += 1
        self.connection.memory.poke(address, size, value + 1)  # so a test sees it


class Ticker(Model):
    """A device that wants to hear of every instruction."""

    name = "ticker"
    counts = True

    def __init__(self) -> None:
        super().__init__()
        self.heard = 0

    def on_retire(self, count: int) -> None:
        self.heard += count

    def reset(self) -> None:
        self.heard = 0


class Quiet(Model):
    """A device that does not want to hear."""

    name = "quiet"

    def __init__(self) -> None:
        super().__init__()
        self.heard = 0

    def on_retire(self, count: int) -> None:  # never called by the bus
        self.heard += count


class Shouter(Model):
    """A device that asks for attention as soon as it is told of an instruction."""

    name = "shouter"
    counts = True

    def __init__(self, value: int = 0x40) -> None:
        super().__init__()
        self.value = value
        self.answers: list[bool] = []

    def on_retire(self, count: int) -> None:
        self.answers.append(self.connection.interrupts.external(self.value))


def machine(*devices: Part, xlen: int = 32, config=DEFAULT, seed: int | None = None,
            **values: int) -> tuple[Machine, DeviceBus]:
    bus = DeviceBus(devices, seed=seed)
    m = Machine(Options(xlen=xlen, config=config), bus=bus)
    bus.connect(m)
    for number, value in values.items():
        m.x.write(int(number[1:]), value)
    return m, bus


# ------------------------------------------------------------------ the addresses


def test_a_device_answers_its_own_range():
    m, bus = machine(Cells())
    m.memory.write(MMIO, 4, 7)
    assert m.memory.read(MMIO, 4) == 8  # the device added one on the way in
    assert (bus.devices[0].reads, bus.devices[0].writes) == (1, 1)


def test_the_registers_of_a_device_live_in_memory():
    """So a dump, a memory view or the debugger sees the true values without
    asking the devices."""
    m, bus = machine(Cells())
    m.memory.write(MMIO, 4, 0x1234)
    assert m.memory.peek(MMIO, 4) == 0x1235


def test_where_no_device_stands_the_area_is_plain_memory():
    """Which is what RARS does when no tool is connected."""
    m, bus = machine(Cells())
    m.memory.write(MMIO + 0x40, 4, 0x1234)
    assert m.memory.read(MMIO + 0x40, 4) == 0x1234
    assert bus.devices[0].writes == 0


def test_the_address_just_past_a_device_is_not_its_own():
    m, bus = machine(Cells())  # four bytes at the base of the area
    m.memory.write(MMIO + 4, 4, 0x1234)
    assert m.memory.read(MMIO + 4, 4) == 0x1234  # plain memory, not one more
    assert (bus.devices[0].reads, bus.devices[0].writes) == (0, 0)


def test_a_bus_without_devices_is_plain_memory():
    m, bus = machine()
    m.memory.write(MMIO, 4, 5)
    assert (m.memory.read(MMIO, 4), m.memory.peek(MMIO, 4)) == (5, 5)


def test_a_device_sits_where_the_configuration_puts_the_area():
    """The offset is counted from the base of the area, so the same device works in
    every memory configuration."""
    config = CONFIGS["CompactDataAtZero"]
    m, bus = machine(Cells(), config=config)
    m.memory.write(config.mmio_base, 4, 1)
    assert bus.devices[0].writes == 1


def test_two_devices_cannot_answer_the_same_address():
    class Other(Cells):
        name = "other"
        offset = 0x2

    bus = DeviceBus([Cells()])
    with pytest.raises(ValueError, match="answer the same addresses"):
        bus.add(Other())


def test_two_devices_side_by_side_are_allowed():
    class Other(Cells):
        name = "other"
        offset = 0x4

    bus = DeviceBus([Cells(), Other()])
    assert len(bus.devices) == 2


def test_a_range_outside_the_area_of_the_devices_is_refused():
    class Far(Cells):
        name = "far"
        offset = 0x10000

    m = Machine(Options())
    bus = DeviceBus([Far()])
    with pytest.raises(ValueError, match="past the area of the devices"):
        bus.connect(m)


def test_a_range_of_no_size_is_refused():
    class Empty(Cells):
        name = "empty"
        size = 0

    with pytest.raises(ValueError, match="a range of 0 bytes"):
        DeviceBus([Empty()])


# ----------------------------------------------------------------- the connection


def test_a_device_is_given_what_it_may_reach():
    device = Cells()
    m, bus = machine(device, seed=7)
    connection = device.connection
    assert isinstance(connection, Connection)
    assert connection.memory is m.memory and connection.csr is m.csr
    assert connection.config is DEFAULT and connection.clock is m.csr.clock
    assert isinstance(connection.interrupts, Interrupts)
    assert connection.random.random() == random.Random(7).random()


def test_connecting_a_device_resets_it():
    """A device attached to a machine starts as a machine just started does."""
    ticker = Ticker()
    ticker.heard = 5
    bus = DeviceBus([ticker])
    assert ticker.heard == 5  # nothing happened yet: there is no machine
    bus.connect(Machine(Options()))
    assert ticker.heard == 0


def test_a_device_added_after_the_bus_was_connected_is_connected_too():
    m, bus = machine()
    device = bus.add(Cells())
    assert device.connection is not None
    m.memory.write(MMIO, 4, 1)
    assert device.writes == 1


def test_a_device_asks_for_attention_through_its_slot():
    device = Shouter()
    m, bus = machine(device)
    bus.on_retire(1)
    bus.on_retire(1)
    assert m.pending.external == 0x40
    assert device.answers == [True, False]  # a full slot drops the second, as in RARS


def test_resetting_the_bus_resets_every_device():
    ticker = Ticker()
    m, bus = machine(ticker)
    bus.on_retire(3)
    assert ticker.heard == 3
    bus.reset()
    assert ticker.heard == 0


# -------------------------------------------------------------- the instructions


def test_only_the_devices_that_ask_hear_of_an_instruction():
    ticker, quiet = Ticker(), Quiet()
    m, bus = machine(ticker, quiet)
    bus.on_retire(2)
    assert (ticker.heard, quiet.heard) == (2, 0)


def test_the_simulator_tells_the_bus_of_every_instruction_carried_out():
    ticker = Ticker()
    m, bus = machine(ticker)
    m.memory.poke(TEXT, 4, NOP)
    m.memory.poke(TEXT + 4, 4, NOP)
    simulator = Simulator(m)
    simulator.step()
    simulator.step()
    assert ticker.heard == simulator.count == 2


def test_an_instruction_that_traps_is_not_told_of():
    """A faulting instruction never reaches `instret`, and the devices are told of
    exactly the instructions that do."""
    ticker = Ticker()
    m, bus = machine(ticker)
    m.memory.poke(TEXT, 4, word("lw", rd=5, rs1=0, imm=1))  # misaligned
    simulator = Simulator(m)
    simulator.step()
    assert (ticker.heard, simulator.count) == (0, 0)


def test_a_machine_without_a_bus_tells_nobody():
    m = Machine(Options())
    assert m.memory.bus is None
    simulator = Simulator(m)
    assert simulator._tick is None


def test_a_bus_that_does_not_want_to_hear_is_not_called():
    """The `Bus` protocol of the memory knows only read and write; a bus of another
    kind is left alone."""
    class Plain:
        def read(self, address, size):
            return 0

        def write(self, address, size, value):
            pass

    m = Machine(Options(), bus=Plain())
    assert Simulator(m)._tick is None


# ------------------------------------------------------------------ the registry


def test_a_device_is_built_by_name():
    register("cells-for-the-test", Cells)
    try:
        assert "cells-for-the-test" in names()
        assert isinstance(make("cells-for-the-test"), Cells)
    finally:
        del DEVICES["cells-for-the-test"]


def test_a_name_nobody_has():
    with pytest.raises(ValueError, match="no device of that name"):
        make("nothing")


def test_a_name_cannot_be_taken_twice():
    register("twice", Cells)
    try:
        with pytest.raises(ValueError, match="known already"):
            register("twice", Cells)
    finally:
        del DEVICES["twice"]
