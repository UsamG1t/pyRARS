"""The block device.

No device of RARS does this, so the expected values are the ones the architecture
spec fixes (M5, 2026-10-08): the six registers at MMIO+0x40..0x57, one block
carried over whole every `delay` instructions, the external interrupt 0x800 when
the work ends, the bit of the error for a block past the end of the disk or a
buffer the program may not touch, and a geometry the device only answers.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator
from pyrars.devices import DeviceBus, make
from pyrars.devices.disk import (ASKS, BLOCK, BLOCKS, BUFFER, BUSY, BlockDevice, CONTROL,
                                 COUNT, ERROR, INTERRUPT, SIZE, WRITING)
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

MMIO = DEFAULT.mmio_base
DATA = DEFAULT.data_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def disk(blocks: int = 4, block_size: int = 8, delay: int = 2, depth: int = 0,
         filled: bool = True) -> tuple[Machine, BlockDevice]:
    device = BlockDevice(blocks=blocks, block_size=block_size, delay=delay)
    if filled:
        device.load(bytes(range(blocks * block_size)))
    bus = DeviceBus([device])
    machine = Machine(Options(history_depth=depth), bus=bus)
    bus.connect(machine)
    return machine, device


def put(machine: Machine, which: int, value: int) -> None:
    machine.memory.write(MMIO + which, 4, value)


def get(machine: Machine, which: int) -> int:
    return machine.memory.read(MMIO + which, 4)


def order(machine: Machine, block: int, buffer: int, count: int,
          writing: bool = False, interrupt: bool = False) -> None:
    """What a program writes to set the disk working."""
    put(machine, BLOCK, block)
    put(machine, BUFFER, buffer)
    put(machine, COUNT, count)
    put(machine, CONTROL, BUSY | (WRITING if writing else 0)
        | (INTERRUPT if interrupt else 0))


# ----------------------------------------------------------------- the geometry


def test_the_disk_says_how_large_it_is():
    machine, device = disk(blocks=4, block_size=8)
    assert (get(machine, BLOCKS), get(machine, SIZE)) == (4, 8)


def test_the_geometry_is_the_disk_s_to_tell():
    machine, device = disk()
    put(machine, BLOCKS, 99)
    put(machine, SIZE, 99)
    assert (get(machine, BLOCKS), get(machine, SIZE)) == (4, 8)


def test_a_disk_of_nothing():
    with pytest.raises(ValueError, match="at least one block"):
        BlockDevice(blocks=0)
    with pytest.raises(ValueError, match="at least one block"):
        BlockDevice(delay=0)


def test_an_image_of_the_wrong_size():
    with pytest.raises(ValueError, match="an image of 5 bytes"):
        BlockDevice(blocks=2, block_size=4, image=bytearray(5))
    device = BlockDevice(blocks=2, block_size=4)
    with pytest.raises(ValueError, match="an image of 3 bytes"):
        device.load(b"abc")


# ------------------------------------------------------------------ the reading


def test_a_block_is_read_into_memory_when_its_time_is_up():
    machine, device = disk(delay=3)
    order(machine, 1, DATA, 1)
    assert get(machine, CONTROL) & BUSY
    device.on_retire(2)
    assert machine.memory.read_bytes(DATA, 8) == bytes(8)
    device.on_retire(1)
    assert machine.memory.read_bytes(DATA, 8) == bytes(range(8, 16))
    assert not get(machine, CONTROL) & BUSY


def test_every_block_costs_the_same():
    machine, device = disk(delay=2)
    order(machine, 0, DATA, 3)
    device.on_retire(2)
    assert device.left == 2
    device.on_retire(4)
    assert device.left == 0
    assert machine.memory.read_bytes(DATA, 24) == bytes(range(24))


def test_nothing_to_carry_over_is_no_work():
    machine, device = disk()
    order(machine, 0, DATA, 0)
    assert not get(machine, CONTROL) & BUSY
    assert machine.memory.read_bytes(DATA, 8) == bytes(8)


# ------------------------------------------------------------------ the writing


def test_a_block_is_written_from_memory_to_the_disk():
    machine, device = disk(delay=1, filled=False)
    machine.memory.write_bytes(DATA, bytes(range(100, 108)))
    order(machine, 2, DATA, 1, writing=True)
    device.on_retire(1)
    assert device.image[16:24] == bytearray(range(100, 108))
    assert device.image[:16] == bytearray(16)  # and nothing else was touched


def test_what_was_written_can_be_read_back():
    machine, device = disk(delay=1, filled=False)
    machine.memory.write_bytes(DATA, b"saved!!!")
    order(machine, 3, DATA, 1, writing=True)
    device.on_retire(1)
    order(machine, 3, DATA + 0x40, 1)
    device.on_retire(1)
    assert machine.memory.read_bytes(DATA + 0x40, 8) == b"saved!!!"


# ------------------------------------------------------------ asking to be told


def test_the_disk_tells_the_program_when_it_is_done():
    machine, device = disk(delay=1)
    order(machine, 0, DATA, 2, interrupt=True)
    device.on_retire(1)
    assert machine.pending.external is None
    device.on_retire(1)
    assert machine.pending.external == ASKS
    assert get(machine, CONTROL) == INTERRUPT


def test_the_disk_is_silent_where_the_program_did_not_ask():
    machine, device = disk(delay=1)
    order(machine, 0, DATA, 1)
    device.on_retire(1)
    assert machine.pending.external is None


# ------------------------------------------------------------------- the errors


def test_a_block_past_the_end_of_the_disk_is_refused():
    machine, device = disk(blocks=4)
    order(machine, 4, DATA, 1, interrupt=True)
    assert get(machine, CONTROL) == INTERRUPT | ERROR
    assert machine.pending.external == ASKS
    assert machine.memory.read_bytes(DATA, 8) == bytes(8)


def test_a_run_of_blocks_that_runs_past_the_end_is_refused():
    machine, device = disk(blocks=4)
    order(machine, 3, DATA, 2)
    assert get(machine, CONTROL) & ERROR
    assert not get(machine, CONTROL) & BUSY


def test_a_buffer_the_program_may_not_touch():
    machine, device = disk(delay=1)
    order(machine, 0, TEXT, 1)  # the text segment is closed to a program
    device.on_retire(1)
    assert get(machine, CONTROL) & ERROR
    assert not get(machine, CONTROL) & BUSY


def test_a_new_order_clears_the_error():
    machine, device = disk(delay=1)
    order(machine, 9, DATA, 1)
    assert get(machine, CONTROL) & ERROR
    order(machine, 0, DATA, 1)
    assert not get(machine, CONTROL) & ERROR


def test_the_bit_that_starts_it_is_no_use_while_it_works():
    machine, device = disk(delay=4)
    order(machine, 0, DATA, 2)
    device.on_retire(1)
    put(machine, COUNT, 99)
    put(machine, CONTROL, BUSY)
    assert device.left == 2


# ------------------------------------------------------------- with the machine


def test_the_work_is_counted_by_the_machine_itself():
    machine, device = disk(delay=2)
    machine.x.write(5, MMIO)
    machine.x.write(6, 1)  # the block
    machine.x.write(7, DATA)
    machine.x.write(8, 1)  # one block
    machine.x.write(9, BUSY)
    program = (word("sw", rs1=5, rs2=6, imm=BLOCK),
               word("sw", rs1=5, rs2=7, imm=BUFFER),
               word("sw", rs1=5, rs2=8, imm=COUNT),
               word("sw", rs1=5, rs2=9, imm=CONTROL),
               NOP, NOP)
    for index, value in enumerate(program):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    simulator = Simulator(machine)
    for _ in range(4):
        simulator.step()
    assert machine.memory.read_bytes(DATA, 8) == bytes(8)  # not yet
    simulator.step()
    assert machine.memory.read_bytes(DATA, 8) == bytes(range(8, 16))


def test_what_was_read_into_memory_goes_back_with_a_step_back():
    """The bytes are written as a program writes them, so the journal holds them;
    what the disk has carried over is its own and does not go back."""
    machine, device = disk(delay=1, depth=10)
    machine.memory.poke(TEXT, 4, NOP)
    order(machine, 1, DATA, 1)
    simulator = Simulator(machine)
    simulator.step()
    assert machine.memory.peek(DATA, 4) == 0x0B0A0908
    assert simulator.back_step() is True
    assert machine.memory.peek(DATA, 4) == 0
    assert device.block == 2  # the disk stands where it stood


# ------------------------------------------------------------- what is around


def test_the_registers_live_in_memory():
    machine, device = disk()
    order(machine, 2, DATA, 1)
    assert machine.memory.peek(MMIO + BLOCK, 4) == 2
    assert machine.memory.peek(MMIO + BLOCKS, 4) == 4


def test_the_image_is_handed_over_and_taken_back():
    machine, device = disk(blocks=2, block_size=4, filled=False)
    device.load(b"abcdefgh")
    assert device.saved() == b"abcdefgh"
    machine.memory.write_bytes(DATA, b"WXYZ")
    order(machine, 0, DATA, 1, writing=True)
    device.on_retire(2)
    assert device.saved() == b"WXYZefgh"


def test_a_reset_forgets_the_order_and_keeps_the_disk():
    machine, device = disk()
    order(machine, 1, DATA, 2)
    device.reset()
    assert (device.busy, device.left) == (False, 0)
    assert get(machine, CONTROL) == 0
    assert (get(machine, BLOCKS), get(machine, SIZE)) == (4, 8)
    assert device.saved() == bytes(range(32))  # what is on the disk stays there


def test_a_watcher_is_told_of_a_change():
    machine, device = disk(delay=1)
    changes = []
    stop = device.subscribe(lambda: changes.append(device.left))
    order(machine, 0, DATA, 2)
    device.on_retire(2)
    assert changes[-1] == 0
    stop()
    told = len(changes)
    device.on_retire(1)
    assert len(changes) == told


def test_the_device_is_known_by_name():
    assert isinstance(make("disk"), BlockDevice)
    assert make("disk", blocks=2, block_size=4).image == bytearray(8)
