"""The control and status registers.

Expected values are the verified behaviour of RARS (R-CSR): the masks of
`ustatus` and `fcsr`, the windows `fflags` and `frm` into `fcsr`, the counters
that hold 64 bits and refuse every write, and the messages of the two refusals.
"""

import pytest

from pyrars.core.csr import BY_NAME, REGISTERS, ControlRegisters
from pyrars.core.options import Options
from pyrars.core.traps import ILLEGAL_INSTRUCTION, Trap
from pyrars.isa.registers import CSRS

USTATUS = CSRS["ustatus"]
FCSR, FFLAGS, FRM = CSRS["fcsr"], CSRS["fflags"], CSRS["frm"]
CYCLE, TIME, INSTRET = CSRS["cycle"], CSRS["time"], CSRS["instret"]
CYCLEH, TIMEH, INSTRETH = CSRS["cycleh"], CSRS["timeh"], CSRS["instreth"]


def registers(xlen=32, clock=lambda: 0) -> ControlRegisters:
    return ControlRegisters(Options(xlen=xlen), clock)


def test_the_table_holds_the_seventeen_registers_of_rars():
    assert len(REGISTERS) == 17
    assert {register.name for register in REGISTERS} == set(CSRS)
    assert all(register.number == CSRS[register.name] for register in REGISTERS)


@pytest.mark.parametrize("name", ["uie", "uip", "utvec", "uscratch", "uepc", "ucause", "utval"])
def test_a_plain_register_takes_every_bit(name):
    number = CSRS[name]
    narrow = registers()
    narrow.write(number, 0x1_FFFFFFFF)
    assert narrow.read(number) == 0xFFFFFFFF

    wide = registers(xlen=64)
    wide.write(number, 0x1122334455667788)
    assert wide.read(number) == 0x1122334455667788


def test_ustatus_keeps_only_its_two_bits():
    c = registers()
    c.write(USTATUS, 0xFFFFFFFF)
    assert c.read(USTATUS) == 0x11
    c.write(USTATUS, 0x01)
    assert c.read(USTATUS) == 0x01


def test_fcsr_keeps_only_its_eight_bits():
    c = registers()
    c.write(FCSR, 0xFFFFFFFF)
    assert c.read(FCSR) == 0xFF
    assert (c.read(FFLAGS), c.read(FRM)) == (0x1F, 0x7)


def test_the_flags_are_a_window_into_fcsr():
    c = registers()
    c.write(FFLAGS, 0xFF)  # only five bits of it belong to the window
    assert c.read(FCSR) == 0x1F and c.read(FFLAGS) == 0x1F
    c.write(FFLAGS, 0x20)  # a bit above the window changes nothing
    assert c.read(FCSR) == 0x00


def test_the_rounding_mode_is_a_window_into_fcsr():
    c = registers()
    c.write(FRM, 7)
    assert c.read(FCSR) == 0xE0 and c.read(FRM) == 7 and c.rounding_mode() == 7
    c.write(FFLAGS, 0x03)  # writing the flags leaves the mode alone
    assert c.read(FCSR) == 0xE3 and c.rounding_mode() == 7


def test_the_flags_of_an_operation_are_added_to_fcsr():
    c = registers()
    c.write(FRM, 2)
    c.raise_flags(0x01)
    c.raise_flags(0x10)
    assert c.read(FFLAGS) == 0x11 and c.rounding_mode() == 2


@pytest.mark.parametrize("number, name", [
    (CYCLE, "cycle"), (TIME, "time"), (INSTRET, "instret"),
    (CYCLEH, "cycleh"), (TIMEH, "timeh"), (INSTRETH, "instreth")])
def test_a_counter_refuses_every_write(number, name):
    """The message names the register, where RARS says only "CSR" (DEV-54)."""
    c = registers()
    with pytest.raises(Trap) as raised:
        c.write(number, 1)
    assert raised.value.cause == ILLEGAL_INSTRUCTION
    assert raised.value.message == f"Cannot write to the read-only control register {name}"
    assert raised.value.value == number


def test_a_register_that_does_not_exist():
    c = registers()
    for number in (0x123, 0x300, 0xFFF):
        with pytest.raises(Trap) as raised:
            c.read(number)
        assert raised.value.message == f"No such control register 0x{number:03x}"
        with pytest.raises(Trap):
            c.write(number, 0)


def test_the_counters_grow_by_one_for_every_instruction():
    c = registers()
    for _ in range(5):
        c.retire()
    assert c.read(CYCLE) == 5 and c.read(INSTRET) == 5


def test_a_counter_holds_64_bits_and_its_half_is_read_apart():
    c = registers()
    c.poke("instret", 0x1122334455667788)
    assert c.read(INSTRET) == 0x55667788  # a machine of 32 bits sees the low half
    assert c.read(INSTRETH) == 0x11223344

    wide = registers(xlen=64)
    wide.poke("instret", 0x1122334455667788)
    assert wide.read(INSTRET) == 0x1122334455667788
    assert wide.read(INSTRETH) == 0x11223344


def test_the_time_comes_from_the_clock_of_the_machine():
    c = registers(clock=lambda: 0x1A0BEEFCAFE)
    assert c.read(TIME) == 0xBEEFCAFE and c.read(TIMEH) == 0x1A0
    assert registers(xlen=64, clock=lambda: 0x1A0BEEFCAFE).read(TIME) == 0x1A0BEEFCAFE

    ticks = iter([1, 2, 3])
    moving = registers(clock=lambda: next(ticks))
    assert [moving.read(TIME) for _ in range(3)] == [1, 2, 3]


def test_the_machine_writes_what_a_program_may_not():
    c = registers()
    c.poke("ucause", 5)
    c.poke("uepc", 0x00400010)
    c.poke("cycle", 7)
    assert (c.read(CSRS["ucause"]), c.read(CSRS["uepc"]), c.read(CYCLE)) == (5, 0x00400010, 7)
    # a window can be written that way as well
    c.poke("cycleh", 0x11223344)
    assert c.read(CYCLEH) == 0x11223344 and c.read(CYCLE) == 7


def test_every_register_starts_at_zero():
    c = registers(clock=lambda: 0)
    assert all(c.read(register.number) == 0 for register in REGISTERS)
    assert BY_NAME["fcsr"].writable == 0xFF
