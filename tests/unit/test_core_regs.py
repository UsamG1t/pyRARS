"""The register files of the machine.

Expected values: the initial `sp` and `gp` of each memory configuration
(isa/memory.py, verified against RARS), the hardwired zero of x0 and the NaN
boxing of the D extension (ISA manual v20260120, chapter D).
"""

import pytest

from pyrars.core.options import Options
from pyrars.core.regs import FloatRegisters, Registers
from pyrars.isa.memory import COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO, DEFAULT
from pyrars.isa.registers import X_NAMES
from pyrars.softfloat.formats import BINARY32

SP = X_NAMES.index("sp")
GP = X_NAMES.index("gp")


@pytest.mark.parametrize("config", [DEFAULT, COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO])
def test_the_registers_start_where_the_configuration_says(config):
    x = Registers(Options(config=config))
    assert x.read(SP) == config.stack_pointer
    assert x.read(GP) == config.global_pointer
    assert [x.read(number) for number in range(32)
            if number not in (SP, GP)] == [0] * 30
    assert x.pc == config.text_base


def test_the_program_counter_starts_where_it_is_told():
    x = Registers(Options(), pc=DEFAULT.text_base + 0x40)
    assert x.pc == DEFAULT.text_base + 0x40


def test_x0_keeps_its_zero():
    x = Registers()
    x.write(0, 0x11223344)
    assert x.read(0) == 0 and x.signed(0) == 0


def test_a_value_is_kept_in_as_many_bits_as_the_machine_is_wide():
    narrow = Registers(Options(xlen=32))
    narrow.write(5, 0x1_11223344)
    assert narrow.read(5) == 0x11223344

    wide = Registers(Options(xlen=64))
    wide.write(5, 0x1_11223344)
    assert wide.read(5) == 0x111223344
    wide.write(6, -1)
    assert wide.read(6) == 0xFFFFFFFFFFFFFFFF


@pytest.mark.parametrize("xlen, written, unsigned, signed", [
    (32, -1, 0xFFFFFFFF, -1),
    (32, 0x7FFFFFFF, 0x7FFFFFFF, 0x7FFFFFFF),
    (32, 0x80000000, 0x80000000, -(1 << 31)),
    (64, -2, 0xFFFFFFFFFFFFFFFE, -2),
    (64, 1 << 63, 1 << 63, -(1 << 63)),
])
def test_a_register_read_as_a_signed_number(xlen, written, unsigned, signed):
    x = Registers(Options(xlen=xlen))
    x.write(7, written)
    assert x.read(7) == unsigned and x.signed(7) == signed


# ------------------------------------------------------- floating point file


def test_the_floating_point_registers_start_at_zero():
    f = FloatRegisters()
    assert [f.raw(number) for number in range(32)] == [0] * 32


def test_a_single_is_kept_boxed_and_read_back():
    f = FloatRegisters()
    f.set_single(3, 0x3F800000)
    assert f.raw(3) == 0xFFFFFFFF3F800000
    assert f.single(3) == 0x3F800000
    assert f.low_word(3) == 0x3F800000


def test_a_register_that_is_no_boxed_single_reads_as_the_canonical_nan():
    """Verified in RARS: `fadd.s` of such a register gives the canonical NaN,
    while `fmv.x.w` of it gives the low word as it lies."""
    f = FloatRegisters()
    f.set_double(4, 0x1122334455667788)
    assert f.single(4) == BINARY32.canonical_nan
    assert f.low_word(4) == 0x55667788
    assert f.double(4) == 0x1122334455667788


def test_a_double_uses_the_whole_register():
    f = FloatRegisters()
    f.set_double(5, 0x3FF0000000000000)
    assert f.double(5) == 0x3FF0000000000000 and f.raw(5) == 0x3FF0000000000000
    f.set_raw(6, -1)
    assert f.raw(6) == 0xFFFFFFFFFFFFFFFF
    assert f.single(6) == 0xFFFFFFFF  # all ones is a boxed NaN, not the canonical one


def test_a_single_written_over_a_double_boxes_it_again():
    f = FloatRegisters()
    f.set_double(7, 0x1122334455667788)
    f.set_single(7, 0x40000000)
    assert f.raw(7) == 0xFFFFFFFF40000000 and f.single(7) == 0x40000000
