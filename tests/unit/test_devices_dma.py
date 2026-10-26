"""The controller of direct access to memory.

No device of RARS does this, so the expected values are the ones the architecture
spec fixes (M5, 2026-10-08): the four registers at MMIO+0x30..0x3f, a few words
copied for every instruction carried out, the external interrupt 0x400 when the
copying ends, the bit of the error for an address the program may not touch or one
that is not a word, and a copy that goes word by word from the lower address up.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DeviceBus, make
from pyrars.devices.dma import (ASKS, BUSY, CONTROL, DirectAccess, ERROR, FROM, INTERRUPT,
                                TO, WORDS)
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

MMIO = DEFAULT.mmio_base
DATA = DEFAULT.data_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def dma(depth: int = 0, **options) -> tuple[Machine, DirectAccess]:
    device = DirectAccess(**options)
    bus = DeviceBus([device])
    machine = Machine(Options(history_depth=depth), bus=bus)
    bus.connect(machine)
    return machine, device


def put(machine: Machine, which: int, value: int) -> None:
    machine.memory.write(MMIO + which, 4, value)


def get(machine: Machine, which: int) -> int:
    return machine.memory.read(MMIO + which, 4)


def fill(machine: Machine, address: int, count: int) -> None:
    for index in range(count):
        machine.memory.write(address + 4 * index, 4, 0x100 + index)


def words_at(machine: Machine, address: int, count: int) -> list[int]:
    return [machine.memory.peek(address + 4 * index, 4) for index in range(count)]


def order(machine: Machine, source: int, target: int, count: int,
          interrupt: bool = False) -> None:
    """What a program writes to set a copying going."""
    put(machine, FROM, source)
    put(machine, TO, target)
    put(machine, WORDS, count)
    put(machine, CONTROL, BUSY | (INTERRUPT if interrupt else 0))


# -------------------------------------------------------------------- the copy


def test_what_the_controller_looks_like_is_how_far_it_has_got():
    machine, device = dma(speed=1)
    assert device.looks()["copying"] is False
    fill(machine, 0x10010000, 4)
    put(machine, FROM, 0x10010000)
    put(machine, TO, 0x10010100)
    put(machine, WORDS, 4)
    put(machine, CONTROL, BUSY)
    device.on_retire(1)
    looks = device.looks()
    assert looks["copying"] is True
    assert looks["copied"] + looks["left"] == 4
    # where it has GOT to: one word is copied by the instruction that started it,
    # because the hardware begins at once
    assert (looks["from"], looks["to"]) == (0x10010004, 0x10010104)


def test_a_few_words_are_copied_while_the_program_runs_on():
    machine, device = dma()
    fill(machine, DATA, 3)
    order(machine, DATA, DATA + 0x40, 3)
    assert get(machine, CONTROL) & BUSY
    device.on_retire(1)
    assert words_at(machine, DATA + 0x40, 3) == [0x100, 0, 0]
    device.on_retire(2)
    assert words_at(machine, DATA + 0x40, 3) == [0x100, 0x101, 0x102]
    assert not get(machine, CONTROL) & BUSY


def test_how_many_words_an_instruction_is_worth():
    machine, device = dma(speed=4)
    fill(machine, DATA, 8)
    order(machine, DATA, DATA + 0x40, 8)
    device.on_retire(1)
    assert words_at(machine, DATA + 0x40, 8)[:4] == [0x100, 0x101, 0x102, 0x103]
    assert words_at(machine, DATA + 0x40, 8)[4:] == [0, 0, 0, 0]
    device.on_retire(1)
    assert not get(machine, CONTROL) & BUSY


def test_a_copy_of_overlapping_words_goes_from_the_lower_address_up():
    """Which is what a program with a loop that counts up would do."""
    machine, device = dma(speed=8)
    fill(machine, DATA, 4)
    order(machine, DATA, DATA + 4, 4)
    device.on_retire(1)
    assert words_at(machine, DATA, 5) == [0x100, 0x100, 0x100, 0x100, 0x100]


def test_nothing_to_copy_is_no_work():
    machine, device = dma()
    order(machine, DATA, DATA + 0x40, 0)
    assert not get(machine, CONTROL) & BUSY
    assert device.copied == 0


def test_the_bit_that_starts_it_is_no_use_while_it_is_busy():
    machine, device = dma()
    fill(machine, DATA, 4)
    order(machine, DATA, DATA + 0x40, 4)
    device.on_retire(1)
    put(machine, WORDS, 99)  # the program changes its mind
    put(machine, CONTROL, BUSY)
    assert device.left == 3  # the copying that runs goes on as it was


def test_a_speed_of_nothing():
    with pytest.raises(ValueError, match="at least one word"):
        DirectAccess(speed=0)


# ------------------------------------------------------------ asking to be told


def test_the_controller_tells_the_program_when_it_is_done():
    machine, device = dma()
    fill(machine, DATA, 2)
    order(machine, DATA, DATA + 0x40, 2, interrupt=True)
    device.on_retire(1)
    assert machine.pending.external is None
    device.on_retire(1)
    assert machine.pending.external == ASKS
    assert get(machine, CONTROL) == INTERRUPT  # done, and still asked to be told


def test_the_controller_is_silent_where_the_program_did_not_ask():
    machine, device = dma()
    fill(machine, DATA, 1)
    order(machine, DATA, DATA + 0x40, 1)
    device.on_retire(1)
    assert machine.pending.external is None


# ------------------------------------------------------------------- the errors


def test_an_address_that_is_no_word_is_refused_at_once():
    machine, device = dma()
    order(machine, DATA + 2, DATA + 0x40, 4, interrupt=True)
    assert get(machine, CONTROL) == INTERRUPT | ERROR
    assert device.copied == 0
    assert machine.pending.external == ASKS  # the program hears that it ended


def test_an_address_the_program_may_not_touch_stops_the_copying():
    machine, device = dma(speed=8)
    fill(machine, DATA, 4)
    order(machine, DATA, TEXT, 4)  # the text segment is closed to a program
    device.on_retire(1)
    assert get(machine, CONTROL) & ERROR
    assert not get(machine, CONTROL) & BUSY
    assert device.copied == 0


def test_what_was_copied_before_the_error_stays():
    machine, device = dma(speed=8)
    fill(machine, DATA, 4)
    last = DEFAULT.data_segment_limit - 3  # the last word of the data segment
    machine.memory.write(last, 4, 0)
    order(machine, DATA, last, 2)
    device.on_retire(1)
    assert machine.memory.peek(last, 4) == 0x100  # the first word went in
    assert get(machine, CONTROL) & ERROR  # and the second had nowhere to go
    assert device.copied == 1


def test_a_new_order_clears_the_error():
    machine, device = dma()
    order(machine, DATA + 2, DATA + 0x40, 1)
    assert get(machine, CONTROL) & ERROR
    fill(machine, DATA, 1)
    order(machine, DATA, DATA + 0x40, 1)
    assert not get(machine, CONTROL) & ERROR


# ------------------------------------------------------------- with the machine


def test_the_copying_is_counted_by_the_machine_itself():
    machine, device = dma()
    fill(machine, DATA, 2)
    machine.x.write(5, MMIO)
    machine.x.write(6, DATA)
    machine.x.write(7, DATA + 0x40)
    machine.x.write(8, 2)
    machine.x.write(9, BUSY)
    program = (word("sw", rs1=5, rs2=6, imm=FROM),
               word("sw", rs1=5, rs2=7, imm=TO),
               word("sw", rs1=5, rs2=8, imm=WORDS),
               word("sw", rs1=5, rs2=9, imm=CONTROL),
               NOP, NOP, NOP)
    for index, value in enumerate(program):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    simulator = Simulator(machine)
    for _ in range(4):
        simulator.step()
    # The instruction that wrote the start bit is itself the first turn of copying:
    # the hardware begins at once (unlike the delay of the display, which follows
    # the counting of RARS).
    assert device.left == 1
    simulator.step()
    assert device.left == 0 and words_at(machine, DATA + 0x40, 2) == [0x100, 0x101]


def test_what_was_copied_goes_back_with_a_step_back():
    """The words are written as a program writes them, so the journal holds them;
    what the controller has counted is its own and does not go back (the decision
    of 2026-10-08)."""
    machine, device = dma(depth=10)
    fill(machine, DATA, 1)
    machine.memory.poke(TEXT, 4, NOP)
    order(machine, DATA, DATA + 0x40, 1)
    simulator = Simulator(machine)
    simulator.step()
    assert machine.memory.peek(DATA + 0x40, 4) == 0x100 and device.copied == 1
    assert simulator.back_step() is True
    assert machine.memory.peek(DATA + 0x40, 4) == 0  # the word went back
    assert device.copied == 1  # the controller did not


# ------------------------------------------------------------- what is around


def test_the_registers_live_in_memory():
    machine, device = dma()
    fill(machine, DATA, 1)
    order(machine, DATA, DATA + 0x40, 1)
    assert machine.memory.peek(MMIO + FROM, 4) == DATA
    assert machine.memory.peek(MMIO + WORDS, 4) == 1


def test_a_reset_forgets_the_order():
    machine, device = dma()
    fill(machine, DATA, 4)
    order(machine, DATA, DATA + 0x40, 4)
    device.reset()
    assert (device.busy, device.left, device.copied) == (False, 0, 0)
    assert get(machine, CONTROL) == 0


def test_a_watcher_is_told_of_a_change():
    machine, device = dma()
    changes = []
    stop = device.subscribe(lambda: changes.append(device.left))
    fill(machine, DATA, 2)
    order(machine, DATA, DATA + 0x40, 2)
    device.on_retire(2)
    assert changes[-1] == 0
    stop()
    told = len(changes)
    device.on_retire(1)
    assert len(changes) == told


def test_the_device_is_known_by_name():
    assert isinstance(make("dma"), DirectAccess)
    assert make("dma", speed=3).speed == 3
