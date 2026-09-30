"""Memory of the machine: the store, the areas of a configuration, the rules.

Expected addresses are read from the memory configurations (isa/memory.py, the
table of RARS); the causes of the faults are the numbers of the ucause register
(ISA manual v20260120); the rules of access are the decisions of 2026-09-30
recorded as DEV-43, DEV-44 and DEV-45.
"""

import pytest

from pyrars.core import traps
from pyrars.core.memory import ADDRESS_MASK, Access, Area, MemAccess, Memory, PAGE_SIZE
from pyrars.core.traps import Trap
from pyrars.core.options import Options
from pyrars.isa.memory import COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO, DEFAULT
from pyrars.isa.program import AssembledProgram, TextEntry

DATA = DEFAULT.data_base
TEXT = DEFAULT.text_base


def memory(**options) -> Memory:
    return Memory(Options(**options))


# --------------------------------------------------------------------- the store


@pytest.mark.parametrize("size, value", [
    (1, 0x44), (2, 0x3344), (4, 0x11223344), (8, 0x1122334455667788),
])
def test_a_value_of_every_width_comes_back(size, value):
    m = memory()
    m.write(DATA, size, value)
    assert m.read(DATA, size) == value


def test_the_bytes_of_a_word_lie_in_the_order_of_the_machine():
    m = memory()
    m.write(DATA, 4, 0x11223344)
    assert [m.read(DATA + i, 1) for i in range(4)] == [0x44, 0x33, 0x22, 0x11]
    assert m.read(DATA, 2) == 0x3344 and m.read(DATA + 2, 2) == 0x1122


def test_a_value_wider_than_the_access_is_cut():
    m = memory()
    m.write(DATA, 1, 0x1FF)
    assert m.read(DATA, 1) == 0xFF


def test_memory_that_was_never_written_reads_as_zero():
    m = memory()
    assert m.read(DATA + 0x40, 4) == 0
    assert m.read_bytes(DATA + 0x40, 16) == bytes(16)


def test_a_run_of_bytes_crosses_the_pages_of_the_store():
    m = memory()
    start = DATA + PAGE_SIZE - 5
    m.write_bytes(start, bytes(range(10)))
    assert m.read_bytes(start, 10) == bytes(range(10))
    assert m.read(start + 5, 4) == int.from_bytes(bytes(range(5, 9)), "little")


def test_the_address_space_is_32_bits_wide():
    """Verified against RARS: the address 2**32 + x is the address x."""
    m = memory()
    m.write((1 << 32) + DATA, 4, 0x11223344)
    assert m.read(DATA, 4) == 0x11223344
    assert m.read((1 << 32) + DATA, 4) == 0x11223344  # and back again
    assert m.peek((1 << 32) + DATA, 4) == 0x11223344
    m.poke((1 << 32) + TEXT, 4, 0x00100513)
    assert m.fetch((1 << 32) + TEXT).address == TEXT


# -------------------------------------------------------------------- the areas


@pytest.mark.parametrize("config", [DEFAULT, COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO])
def test_the_areas_of_a_configuration_follow_its_table(config):
    m = Memory(Options(config=config))
    assert m._area(config.text_base) is Area.TEXT
    assert m._area(config.text_limit + 3) is Area.TEXT
    assert m._area(config.data_segment_base) is Area.DATA
    assert m._area(config.data_segment_limit) is Area.DATA
    assert m._area(config.mmio_base) is Area.DEVICES
    assert m._area(config.mmap_limit) is Area.DEVICES
    assert m._area(config.kernel_base) is Area.NONE


@pytest.mark.parametrize("address", [
    DEFAULT.text_base - 4,  # below the text segment
    DEFAULT.kernel_base,  # the kernel keeps its own memory
    DEFAULT.mmio_base - 4,  # between the kernel base and the devices
])
def test_an_address_of_no_area_is_out_of_range(address):
    m = memory()
    for size in (1, 4):
        with pytest.raises(Trap) as raised:
            m.read(address, size)
        assert raised.value.cause == traps.LOAD_ACCESS_FAULT
        assert raised.value.message == f"address out of range 0x{address:08x}"
    with pytest.raises(Trap) as raised:
        m.write(address, 4, 0)
    assert raised.value.cause == traps.STORE_ACCESS_FAULT


@pytest.mark.parametrize("address", [
    DEFAULT.data_segment_base,  # the extern area
    DEFAULT.data_base,
    DEFAULT.heap_base,
    0x50000000,  # far above the heap: ours to use (DEV-43)
    DEFAULT.stack_pointer,
    DEFAULT.data_segment_limit - 3,
    DEFAULT.mmio_base,  # the devices are plain memory while no bus is attached
    DEFAULT.mmap_limit - 3,
])
def test_the_addresses_a_program_may_use(address):
    m = memory()
    m.write(address, 4, 0x55667788)
    assert m.read(address, 4) == 0x55667788


# ----------------------------------------------------------------- alignment


@pytest.mark.parametrize("size, name", [(2, "halfword"), (4, "word"), (8, "doubleword")])
def test_an_access_must_be_aligned_to_its_own_width(size, name):
    """DEV-44: RARS checks a load of eight bytes against four and a store of
    eight bytes not at all. DEV-45: its four messages read differently."""
    m = memory()
    for offset in range(1, size):
        with pytest.raises(Trap) as raised:
            m.read(DATA + offset, size)
        assert raised.value.cause == traps.LOAD_ADDRESS_MISALIGNED
        assert raised.value.message == (
            f"Load address not aligned to {name} boundary 0x{DATA + offset:08x}")

        with pytest.raises(Trap) as raised:
            m.write(DATA + offset, size, 0)
        assert raised.value.cause == traps.STORE_ADDRESS_MISALIGNED
        assert raised.value.message == (
            f"Store address not aligned to {name} boundary 0x{DATA + offset:08x}")


def test_a_byte_needs_no_alignment():
    m = memory()
    for offset in range(8):
        m.write(DATA + offset, 1, offset)
    assert [m.read(DATA + offset, 1) for offset in range(8)] == list(range(8))


# -------------------------------------------------------------- the text segment


def test_a_program_cannot_touch_its_own_text():
    m = memory()
    with pytest.raises(Trap) as raised:
        m.read(TEXT, 4)
    assert raised.value.cause == traps.LOAD_ACCESS_FAULT
    assert raised.value.message == f"Cannot read directly from text segment!0x{TEXT:08x}"
    with pytest.raises(Trap) as raised:
        m.write(TEXT, 4, 0)
    assert raised.value.cause == traps.STORE_ACCESS_FAULT
    assert raised.value.message == f"Cannot write directly to text segment!0x{TEXT:08x}"


def test_with_self_modifying_code_the_text_is_ordinary_memory():
    m = memory(self_modifying=True)
    m.write(TEXT, 4, 0x00100513)  # addi a0, x0, 1
    assert m.read(TEXT, 4) == 0x00100513
    assert m.fetch(TEXT).instr.instr.mnemonic == "addi"


def test_a_write_into_the_text_makes_the_instruction_be_read_anew():
    m = memory(self_modifying=True)
    m.write(TEXT, 4, 0x00000013)  # nop
    assert m.fetch(TEXT).instr.instr.mnemonic == "addi"  # nop is addi x0, x0, 0
    m.write(TEXT, 4, 0x00008067)  # jalr x0, 0(x1)
    assert m.fetch(TEXT).instr.instr.mnemonic == "jalr"
    m.write(TEXT + 3, 1, 0x00)  # a byte of the same word counts as well
    assert m.fetch(TEXT).word == 0x00008067 & 0x00FFFFFF


def test_the_alignment_rule_is_checked_before_the_text_rule():
    """Verified in RARS: a misaligned access to the text gives the alignment
    message, not the one about the text segment."""
    m = memory()
    with pytest.raises(Trap) as raised:
        m.read(TEXT + 2, 4)
    assert raised.value.cause == traps.LOAD_ADDRESS_MISALIGNED


# ------------------------------------------------------------------ fetching


def test_a_place_of_the_text_that_holds_nothing_has_no_instruction():
    m = memory()
    assert m.fetch(TEXT) is None


def test_an_instruction_word_is_fetched_and_decoded():
    m = memory()
    m.load(program([(TEXT, 0x00100513)]))  # addi a0, x0, 1
    fetched = m.fetch(TEXT)
    assert (fetched.address, fetched.word) == (TEXT, 0x00100513)
    assert fetched.instr.instr.mnemonic == "addi" and fetched.instr.operands["rd"] == 10


def test_a_word_that_is_no_instruction_is_fetched_without_one():
    m = memory()
    m.load(program([(TEXT, 0x11223344)]))
    fetched = m.fetch(TEXT)
    assert fetched.word == 0x11223344 and fetched.instr is None


def test_fetching_asks_the_decoder_once():
    m = memory()
    m.load(program([(TEXT, 0x00100513)]))
    assert m.fetch(TEXT) is m.fetch(TEXT)


def test_a_fetch_must_be_aligned():
    m = memory()
    m.load(program([(TEXT, 0x00100513)]))
    with pytest.raises(Trap) as raised:
        m.fetch(TEXT + 2)
    assert raised.value.cause == traps.INSTRUCTION_ADDRESS_MISALIGNED
    assert raised.value.message == (
        f"Instruction address not aligned to word boundary 0x{TEXT + 2:08x}")


def test_a_fetch_outside_the_text_is_refused():
    m = memory()
    m.write(DATA, 4, 0x00100513)
    with pytest.raises(Trap) as raised:
        m.fetch(DATA)
    assert raised.value.cause == traps.INSTRUCTION_ACCESS_FAULT
    assert raised.value.message == "Instruction load access error"


def test_with_self_modifying_code_a_fetch_outside_the_text_is_allowed():
    m = memory(self_modifying=True)
    m.write(DATA, 4, 0x00100513)
    assert m.fetch(DATA).instr.instr.mnemonic == "addi"
    # but only where memory exists at all
    with pytest.raises(Trap):
        m.fetch(DEFAULT.kernel_base)


# ------------------------------------------------------------------- loading


def program(words, data=b"", data_base=DATA, xlen=32, config="Default") -> AssembledProgram:
    return AssembledProgram(
        xlen=xlen, mem_config=config,
        text=tuple(TextEntry(address, word, "", None, "") for address, word in words),
        data_base=data_base, data=data, data_layout=(), symbols={}, globals=frozenset(),
        entry=TEXT, diagnostics=())


def test_loading_puts_the_text_and_the_data_in_place():
    m = memory()
    m.load(program([(TEXT, 0x00100513), (TEXT + 4, 0x00008067)], data=b"hi\0"))
    assert m.peek(TEXT, 4) == 0x00100513 and m.peek(TEXT + 4, 4) == 0x00008067
    assert m.read_bytes(DATA, 3) == b"hi\0"
    assert m.fetch(TEXT + 4).instr.instr.mnemonic == "jalr"


@pytest.mark.parametrize("program_xlen, program_config", [
    (64, "Default"), (32, "CompactDataAtZero")])
def test_a_program_of_another_contract_is_refused(program_xlen, program_config):
    """The addresses are built into the machine code, so the machine must be
    set up the same way the assembler was (user decision 2026-09-30)."""
    m = memory()
    with pytest.raises(ValueError, match="assembled for"):
        m.load(program([(TEXT, 0x00100513)], xlen=program_xlen, config=program_config))


# -------------------------------------------------------------- subscriptions


def test_a_subscriber_sees_the_accesses_it_asked_for():
    m = memory()
    seen = []
    m.subscribe(Access.WRITE, seen.append)
    m.write(DATA, 4, 0x11223344)
    m.read(DATA, 4)  # not a write: not reported
    assert seen == [MemAccess(Access.WRITE, DATA, 4, 0x11223344)]

    reads = []
    m.subscribe(Access.READ, reads.append)
    assert m.read(DATA + 1, 1) == 0x33
    assert reads == [MemAccess(Access.READ, DATA + 1, 1, 0x33)]


def test_a_subscription_may_watch_a_range_only():
    m = memory()
    seen = []
    m.subscribe(Access.WRITE, seen.append, DATA, DATA + 7)
    m.write(DATA + 4, 4, 1)
    m.write(DATA + 8, 4, 2)  # outside the range
    assert [access.address for access in seen] == [DATA + 4]


def test_a_subscription_can_be_ended():
    m = memory()
    seen = []
    stop = m.subscribe(Access.WRITE, seen.append)
    m.write(DATA, 4, 1)
    stop()
    m.write(DATA, 4, 2)
    assert len(seen) == 1
    stop()  # ending it twice is no error


def test_the_tools_read_and_write_without_rules_and_without_notice():
    m = memory()
    seen = []
    m.subscribe(Access.READ, seen.append)
    m.subscribe(Access.WRITE, seen.append)
    m.poke(TEXT, 4, 0x00100513)  # the text segment, which a program may not touch
    assert m.peek(TEXT, 4) == 0x00100513
    assert m.peek(DEFAULT.kernel_base, 4) == 0  # no area, no fault
    assert seen == []
    assert m.fetch(TEXT).instr.instr.mnemonic == "addi"  # poke filled the word


# ---------------------------------------------------------------- the devices


class FakeBus:
    def __init__(self) -> None:
        self.log = []

    def read(self, address: int, size: int) -> int:
        self.log.append(("read", address, size))
        return 0xABCD

    def write(self, address: int, size: int, value: int) -> None:
        self.log.append(("write", address, size, value))


def test_the_addresses_of_the_devices_go_to_the_bus_when_one_is_attached():
    bus = FakeBus()
    m = Memory(Options(), bus)
    m.write(DEFAULT.mmio_base, 4, 7)
    assert m.read(DEFAULT.mmio_base, 4) == 0xABCD
    assert bus.log == [("write", DEFAULT.mmio_base, 4, 7), ("read", DEFAULT.mmio_base, 4)]
    # the rest of the memory is untouched by the bus
    m.write(DATA, 4, 1)
    assert m.read(DATA, 4) == 1 and len(bus.log) == 2


def test_without_a_bus_the_devices_are_plain_memory():
    """Verified in RARS: a program without tools reads and writes there freely."""
    m = memory()
    m.write(DEFAULT.mmio_base + 4, 4, 7)
    assert m.read(DEFAULT.mmio_base + 4, 4) == 7
