"""The halt register: a program says it is done by writing to an address.

Ours alone (DEV-59): no device of RARS has it, and it is how the test stands of
real machines are told that a program has finished and how it went.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, StopReason
from pyrars.core.syscalls import Exited
from pyrars.devices import DeviceBus, make
from pyrars.devices.halt import HALT, Halt
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

MMIO = DEFAULT.mmio_base
TEXT = DEFAULT.text_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def halt() -> tuple[Machine, Halt]:
    device = Halt()
    bus = DeviceBus([device])
    machine = Machine(Options(), bus=bus)
    bus.connect(machine)
    return machine, device


def test_a_write_says_the_program_is_done():
    machine, device = halt()
    with pytest.raises(Exited) as raised:
        machine.memory.write(MMIO + HALT, 4, 7)
    assert raised.value.code == 7


def test_the_run_ends_with_the_code_that_was_written():
    machine, device = halt()
    machine.x.write(5, MMIO + HALT)
    machine.x.write(6, 3)
    machine.memory.poke(TEXT, 4, word("sw", rs1=5, rs2=6, imm=0))
    machine.memory.poke(TEXT + 4, 4, NOP)
    simulator = Simulator(machine)
    stop = simulator.run()
    assert (stop.reason, stop.code) == (StopReason.NORMAL_TERMINATION, 3)
    assert simulator.count == 0  # as with the service that ends a program


def test_what_was_written_stays_to_be_read():
    machine, device = halt()
    with pytest.raises(Exited):
        machine.memory.write(MMIO + HALT, 4, 42)
    assert machine.memory.peek(MMIO + HALT, 4) == 42
    assert machine.memory.read(MMIO + HALT, 4) == 42  # a read says nothing of its own


def test_the_device_is_known_by_name():
    assert isinstance(make("halt"), Halt)
