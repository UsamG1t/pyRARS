"""The journal of a step and the step back.

Expected values are derived from what a step changes, which the earlier stages
pinned: a register, a control register, memory, the counters, the top of the heap,
a stream of random numbers, the waiting slots. The journal of RARS is the model
(R-BACKSTEP: the old value of every place, the counters among them), and the
decisions of 2026-10-04 add our own state and the world outside under a debugger.
"""

import io

import pytest

from pyrars.core import traps
from pyrars.core.executor import execute
from pyrars.core.history import History, Kind
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.systemio import ConsoleIO
from pyrars.core.traps import Trap
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT
from pyrars.isa.registers import CSRS

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
HEAP = DEFAULT.heap_base
NOP = 0x00000013  # addi x0, x0, 0
ECALL = encode(find("ecall", 32), {})
A0, A1, A7 = 10, 11, 17


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def machine(*words: int, xlen: int = 32, debug: bool = False, depth: int = 2000,
            io_=None, **values: int) -> Machine:
    """A machine with a journal, holding the words as its program. A journal has to
    be asked for: `Options.history_depth` is zero by default, because a plain run
    has nobody to look at it (user decision 2026-10-05)."""
    m = Machine(Options(xlen=xlen, history_depth=depth, debug=debug), io=io_)
    for index, value in enumerate(words):
        m.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in values.items():
        m.x.write(int(number[1:]), value)
    return m


def step(m: Machine) -> None:
    """One turn of the loop of R-SIM-LOOP, as the simulator of stage 22 will do
    it: the journal opens a step, the waiting events are looked at, the
    instruction is carried out and counted."""
    if m.history is not None:
        m.history.begin(m)
    traps.take(m)
    fetched = m.fetch()
    if fetched is not None:
        try:
            execute(m, fetched)
        except Trap as trap:
            traps.register(m, trap, fetched.address)
            return
    m.csr.retire()


def state(m: Machine, low: int = DATA, count: int = 8) -> tuple:
    """Everything of a machine a test compares."""
    return (m.x.pc, tuple(m.x.values), tuple(m.f.values), dict(m.csr.values), m.heap,
            tuple(m.memory.peek(low + 4 * index, 4) for index in range(count)),
            (m.pending.external, m.pending.timer, m.pending.trap))


# --------------------------------------------------------------- the registers


def test_integer_register_comes_back():
    m = machine(word("addi", rd=5, rs1=0, imm=42), x5=7)
    step(m)
    assert m.x.read(5) == 42
    assert m.history.back(m) is True
    assert m.x.read(5) == 7


def test_the_program_counter_comes_back():
    m = machine(word("jal", rd=1, imm=0x40))
    step(m)
    assert m.x.pc == TEXT + 0x40
    m.history.back(m)
    assert m.x.pc == TEXT


def test_x0_needs_no_record():
    m = machine(word("addi", rd=0, rs1=0, imm=42))
    step(m)
    assert m.history.steps[-1].entries == []
    m.history.back(m)
    assert m.x.read(0) == 0


def test_a_floating_point_register_comes_back():
    m = machine(word("fmv.w.x", rd=3, rs1=5), x5=0x3F800000)
    m.f.set_double(3, 0x1234567890ABCDEF)
    step(m)
    assert m.f.raw(3) == 0xFFFFFFFF3F800000  # boxed
    m.history.back(m)
    assert m.f.raw(3) == 0x1234567890ABCDEF


def test_a_control_register_comes_back():
    m = machine(word("csrrwi", rd=0, csr=CSRS["uscratch"], uimm=9))
    m.csr.write(CSRS["uscratch"], 0x55)
    step(m)
    assert m.csr.read(CSRS["uscratch"]) == 9
    m.history.back(m)
    assert m.csr.read(CSRS["uscratch"]) == 0x55


def test_a_window_into_a_control_register_comes_back():
    m = machine(word("csrrwi", rd=0, csr=CSRS["frm"], uimm=3))
    m.csr.write(CSRS["fcsr"], 0x1F)  # the flags below the rounding mode
    step(m)
    assert m.csr.read(CSRS["fcsr"]) == 0x7F
    m.history.back(m)
    assert m.csr.read(CSRS["fcsr"]) == 0x1F


def test_the_flags_of_an_operation_come_back():
    m = machine(word("fdiv.s", rd=1, rs1=2, rs2=3, rm=7))  # dyn, frm = 0
    m.f.set_single(2, 0x3F800000)  # 1.0 / 0.0 raises division by zero
    m.f.set_single(3, 0)
    step(m)
    assert m.csr.read(CSRS["fflags"]) == 0x08
    m.history.back(m)
    assert m.csr.read(CSRS["fflags"]) == 0


def test_the_counters_come_back():
    m = machine(NOP, NOP)
    step(m)
    step(m)
    assert m.csr.read(CSRS["instret"]) == 2
    m.history.back(m)
    assert (m.csr.read(CSRS["cycle"]), m.csr.read(CSRS["instret"])) == (1, 1)
    m.history.back(m)
    assert (m.csr.read(CSRS["cycle"]), m.csr.read(CSRS["instret"])) == (0, 0)


# ------------------------------------------------------------------ the memory


def test_a_word_of_memory_comes_back():
    m = machine(word("sw", rs1=5, rs2=6, imm=0), x5=DATA, x6=0xAABBCCDD)
    m.memory.poke(DATA, 4, 0x11223344)
    step(m)
    assert m.memory.peek(DATA, 4) == 0xAABBCCDD
    m.history.back(m)
    assert m.memory.peek(DATA, 4) == 0x11223344


def test_a_byte_of_memory_comes_back_without_touching_its_neighbours():
    m = machine(word("sb", rs1=5, rs2=6, imm=1), x5=DATA, x6=0xFF)
    m.memory.poke(DATA, 4, 0x11223344)
    step(m)
    assert m.memory.peek(DATA, 4) == 0x1122FF44
    m.history.back(m)
    assert m.memory.peek(DATA, 4) == 0x11223344


def test_two_stores_of_one_step_come_back_in_reverse():
    """A pseudo-instruction is several steps, but a service may write twice in
    one; the journal must undo the later write first."""
    m = machine()
    m.history.begin(m)
    m.memory.write(DATA, 4, 1)
    m.memory.write(DATA, 4, 2)
    assert m.memory.peek(DATA, 4) == 2
    m.history.back(m)
    assert m.memory.peek(DATA, 4) == 0


def test_a_run_of_bytes_comes_back():
    m = machine()
    m.memory.write_bytes(DATA, b"abcdefgh")
    m.history.begin(m)
    m.memory.write_bytes(DATA + 2, b"XYZ")
    assert m.memory.read_bytes(DATA, 8) == b"abXYZfgh"
    m.history.back(m)
    assert m.memory.read_bytes(DATA, 8) == b"abcdefgh"


def test_a_write_into_the_text_leaves_the_text_as_empty_as_it_was():
    """A program that writes its own text makes a word of it hold an instruction.
    Taking the write back makes the word hold nothing again, so the machine stops
    there instead of reading an illegal instruction out of zeroes."""
    place = TEXT + 0x40
    m = Machine(Options(self_modifying=True, history_depth=2000))
    m.memory.poke(TEXT, 4, word("sw", rs1=5, rs2=6, imm=0))
    m.x.write(5, place)
    m.x.write(6, NOP)
    assert m.memory.fetch(place) is None
    step(m)
    assert m.memory.fetch(place).word == NOP
    m.history.back(m)
    assert m.memory.fetch(place) is None


def test_a_rewritten_instruction_is_read_anew_after_a_step_back():
    place = TEXT + 0x40
    m = Machine(Options(self_modifying=True, history_depth=2000))
    m.memory.poke(TEXT, 4, word("sw", rs1=5, rs2=6, imm=0))
    m.memory.poke(place, 4, NOP)
    m.x.write(5, place)
    m.x.write(6, word("addi", rd=7, rs1=0, imm=1))
    assert m.memory.fetch(place).word == NOP  # read once, so it is cached
    step(m)
    assert m.memory.fetch(place).instr.instr.mnemonic == "addi"
    m.history.back(m)
    assert m.memory.fetch(place).word == NOP


def test_a_write_to_a_device_is_the_device_s_own_to_undo():
    """What a device did with a write is not in the journal: it is not memory."""
    class Bus:
        def __init__(self):
            self.written = []

        def read(self, address, size):
            return 0

        def write(self, address, size, value):
            self.written.append((address, value))

    bus = Bus()
    m = Machine(Options(history_depth=2000), bus=bus)
    m.history.begin(m)
    m.memory.write(DEFAULT.mmio_base, 4, 7)
    assert m.history.steps[-1].entries == []
    m.history.back(m)
    assert bus.written == [(DEFAULT.mmio_base, 7)]


# ------------------------------------------------------- the rest of the machine


def test_the_top_of_the_heap_comes_back():
    m = machine(ECALL, ECALL, **{"x17": 9, "x10": 16})
    step(m)
    assert (m.x.read(A0), m.heap) == (HEAP, HEAP + 16)
    m.history.back(m)
    assert m.heap == HEAP
    step(m)
    assert m.x.read(A0) == HEAP  # the same piece is handed out again


def test_a_stream_of_random_numbers_comes_back():
    m = machine(ECALL, ECALL, **{"x17": 41, "x10": 0})
    step(m)
    first = m.x.read(A0)
    m.history.back(m)
    step(m)
    assert m.x.read(A0) == first


def test_a_stream_is_made_before_it_is_written_down():
    """A stream made by the step itself stays after a step back, with the state
    it started from: making it anew would draw from another seed."""
    m = machine(ECALL, ECALL, **{"x17": 41, "x10": 3})
    step(m)
    first = m.x.read(A0)
    m.history.back(m)
    assert 3 in m.generators
    step(m)
    assert m.x.read(A0) == first


def test_a_seeded_stream_comes_back():
    m = machine(ECALL, ECALL, ECALL, **{"x17": 41, "x10": 0})
    step(m)  # one number from an unseeded stream
    before = m.generators[0].getstate()
    m.x.write(A7, 40)
    m.x.write(A0, 0)  # the number of the stream; the number drawn landed in a0
    m.x.write(A1, 12345)
    step(m)  # the stream is replaced by a seeded one
    assert m.generators[0].getstate() != before
    m.history.back(m)
    assert m.generators[0].getstate() == before


def test_the_waiting_slots_come_back():
    m = machine(word("sw", rs1=5, rs2=6, imm=1), x5=DATA)  # misaligned: a trap
    step(m)
    assert m.pending.trap is not None
    m.history.back(m)
    assert m.pending.trap is None


def test_an_interrupt_taken_in_a_step_comes_back():
    handler = TEXT + 0x100
    m = machine(NOP)
    m.memory.poke(handler, 4, NOP)
    m.csr.write(CSRS["utvec"], handler)
    m.csr.write(CSRS["ustatus"], 0x01)
    m.csr.write(CSRS["uie"], traps.EXTERNAL)
    m.pending.add_external(7)
    before = state(m)
    step(m)
    assert m.x.pc == handler + 4 and m.pending.external is None
    m.history.back(m)
    assert state(m) == before


# ------------------------------------------------------------------ the journal


def test_nothing_to_take_back():
    m = machine(NOP)
    assert m.history.back(m) is False


def test_the_oldest_step_is_dropped():
    m = machine(*[word("addi", rd=5, rs1=5, imm=1)] * 4, depth=2)
    for _ in range(4):
        step(m)
    assert m.x.read(5) == 4
    assert len(m.history) == 2
    while m.history.back(m):
        pass
    assert m.x.read(5) == 2  # the two oldest steps are out of reach


def test_a_machine_without_a_depth_keeps_no_journal():
    m = Machine(Options(history_depth=0))
    assert m.history is None
    assert m.x.journal is None and m.memory.journal is None and m.csr.journal is None


def test_a_write_outside_a_step_is_not_written_down():
    """Loading a program and poking from a tool are no steps of a machine."""
    m = machine()
    m.memory.poke(DATA, 4, 5)
    m.x.write(5, 9)
    assert len(m.history) == 0
    assert m.history.back(m) is False


def test_putting_values_back_records_nothing():
    """A step back closes its step first, so what it writes has nowhere to go."""
    m = machine(word("addi", rd=5, rs1=0, imm=42))
    step(m)
    m.history.back(m)
    assert len(m.history) == 0 and m.history.open is None


def test_a_write_of_a_tool_is_not_taken_back():
    """What a debugger puts in memory while a program stands still is no step of
    the machine: a step back leaves it alone."""
    m = machine(NOP)
    m.history.begin(m)
    m.memory.poke(DATA, 4, 0x1234)
    m.history.back(m)
    assert m.memory.peek(DATA, 4) == 0x1234


def test_a_whole_program_run_and_taken_back():
    m = machine(
        word("lui", rd=6, imm=0xABCDE),
        word("sw", rs1=5, rs2=6, imm=0),
        word("lw", rd=7, rs1=5, imm=0),
        word("addi", rd=7, rs1=7, imm=1),
        NOP,
        NOP,
    )
    m.x.write(5, DATA)
    before = state(m)
    for _ in range(6):
        step(m)
    assert m.x.read(7) == 0xABCDE001 and m.memory.peek(DATA, 4) == 0xABCDE000
    assert state(m) != before
    for _ in range(6):
        assert m.history.back(m) is True
    assert state(m) == before
    assert m.history.back(m) is False


def test_steps_come_back_one_at_a_time():
    m = machine(*[word("addi", rd=5, rs1=5, imm=1)] * 3)
    places = []
    for _ in range(3):
        step(m)
        places.append(m.x.read(5))
    assert places == [1, 2, 3]
    for expected in [2, 1, 0]:
        m.history.back(m)
        assert m.x.read(5) == expected


def test_the_journal_can_be_cleared():
    m = machine(NOP)
    step(m)
    m.history.clear()
    assert len(m.history) == 0 and m.history.open is None


def test_an_entry_says_what_it_is_about():
    m = machine(word("addi", rd=5, rs1=0, imm=1), x5=3)
    step(m)
    assert m.history.steps[-1].entries == [m.history.steps[-1].entries[0]]
    entry = m.history.steps[-1].entries[0]
    assert (entry.kind, entry.where, entry.value) == (Kind.X, 5, 3)


# -------------------------------------------------------------- the world outside


def reader_and_io(text: str) -> tuple[io.StringIO, ConsoleIO]:
    out = io.StringIO()
    return out, ConsoleIO(out=out, reader=io.StringIO(text))


def test_under_a_debugger_the_world_comes_back():
    """A read line is handed out again and printed text is taken back, so running
    the same step forward again gives the same thing (user decision 2026-10-04)."""
    out, world = reader_and_io("17\n42\n")
    m = machine(ECALL, ECALL, debug=True, io_=world, **{"x17": 5})
    step(m)
    assert m.x.read(A0) == 17
    m.x.write(A7, 1)  # PrintInt
    step(m)
    assert out.getvalue() == "17"
    m.history.back(m)
    assert out.getvalue() == ""
    m.history.back(m)
    m.x.write(A7, 5)
    step(m)
    assert m.x.read(A0) == 17  # the same line, not the next one


def test_without_a_debugger_the_world_reads_on():
    out, world = reader_and_io("17\n42\n")
    m = machine(ECALL, ECALL, io_=world, **{"x17": 5})
    step(m)
    assert m.x.read(A0) == 17
    m.history.back(m)
    step(m)
    assert m.x.read(A0) == 42  # the world kept its place
    assert m.history.steps[-1].world is not None  # but the record is there


def test_the_record_of_the_world_is_kept_either_way():
    for debug in (False, True):
        out, world = reader_and_io("5\n")
        m = machine(ECALL, debug=debug, io_=world, **{"x17": 5})
        step(m)
        assert m.history.steps[-1].world == (0, 0, 0, {})


def test_a_file_goes_back_to_where_it_was(tmp_path):
    path = tmp_path / "in.txt"
    path.write_text("abcdef")
    world = ConsoleIO(out=io.StringIO(), reader=io.StringIO(""))
    fd = world.open(str(path), 0)
    mark = world.mark()
    assert world.read(fd, 3) == b"abc"
    world.rewind(mark)
    assert world.read(fd, 3) == b"abc"


def test_a_terminal_keeps_what_has_left():
    """A stream that cannot be cut keeps its text; the rest of the mark still
    works."""
    class Terminal(io.StringIO):
        def seekable(self):
            return False

    out = Terminal()
    world = ConsoleIO(out=out, reader=io.StringIO("x\n"))
    mark = world.mark()
    world.write(1, b"gone?")
    world.read_line()
    world.rewind(mark)
    assert out.getvalue() == "gone?"
    assert world.read_line() == "x\n"


def test_a_journal_of_its_own():
    """The journal is a plain object: a test may drive it without a machine."""
    history = History(depth=3)
    assert len(history) == 0 and history.rewind_world is False
