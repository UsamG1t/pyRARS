"""The services a program asks for with `ecall`.

Expected values come from the documentation of RARS (its wiki table and the help
texts in its jar), from its verified behaviour where the documentation is silent,
and from the decisions of 2026-10-03: every service works at the width of the
machine, a failing file service gives back the negative of its error number, and a
dialog in a text session is the console.
"""

import errno

import pytest

from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.syscalls import Exited
from pyrars.core.systemio import Dialog
from pyrars.core.traps import ENVIRONMENT_CALL, Trap
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
A0, A1, A2, A7 = 10, 11, 12, 17
ECALL = encode(find("ecall", 32), {})


class FakeIO:
    """A world that writes into a list and answers from a script."""

    def __init__(self, reading: str = "", answers=(), files=None) -> None:
        self.written: list[tuple[int, bytes]] = []
        self.reading = reading
        self.answers = list(answers)
        self.asked: list[tuple[Dialog, str]] = []
        self.slept: list[int] = []
        self.files: dict[int, bytearray] = files or {}
        self.positions: dict[int, int] = dict.fromkeys(self.files, 0)
        self.opened: list[tuple[str, int]] = []

    # the streams
    def write(self, fd: int, data: bytes) -> int:
        self.written.append((fd, data))
        if fd in self.files:
            self.files[fd] += data
        return len(data)

    def read(self, fd: int, count: int) -> bytes:
        if fd in self.files:
            start = self.positions[fd]
            self.positions[fd] = start + count
            return bytes(self.files[fd][start:start + count])
        taken, self.reading = self.reading[:count], self.reading[count:]
        return taken.encode()

    def read_line(self) -> str:
        line, _, rest = self.reading.partition("\n")
        if not self.reading:
            return ""
        self.reading = rest
        return line + "\n"

    # the files
    def open(self, path: str, flags: int) -> int:
        self.opened.append((path, flags))
        if path == "missing":
            raise OSError(errno.ENOENT, "no such file")
        fd = 3 + len(self.files)
        self.files[fd] = bytearray()
        self.positions[fd] = 0
        return fd

    def close(self, fd: int) -> None:
        if fd not in self.files:
            raise OSError(errno.EBADF, "bad descriptor")
        del self.files[fd]

    def lseek(self, fd: int, offset: int, whence: int) -> int:
        if fd not in self.files:
            raise OSError(errno.EBADF, "bad descriptor")
        self.positions[fd] = offset if whence == 0 else self.positions[fd] + offset
        return self.positions[fd]

    # the rest of the world
    def sleep(self, milliseconds: int) -> None:
        self.slept.append(milliseconds)

    def cwd(self) -> str:
        return "/here"

    def dialog(self, kind: Dialog, message: str, payload: object) -> object:
        self.asked.append((kind, message))
        return self.answers.pop(0)

    @property
    def text(self) -> str:
        return "".join(data.decode() for _, data in self.written)


def machine(service: int, xlen: int = 32, io: FakeIO | None = None, **values) -> Machine:
    """A machine whose next instruction is the `ecall` of that service."""
    world = io if io is not None else FakeIO()
    m = Machine(Options(xlen=xlen), io=world)
    m.memory.poke(TEXT, 4, ECALL)
    m.x.write(A7, service)
    for name, value in values.items():
        m.x.write({"a0": A0, "a1": A1, "a2": A2}[name], value)
    return m


def call(m: Machine) -> None:
    execute(m, m.fetch())


def with_text(service: int, text: str, xlen: int = 32, **values) -> tuple[Machine, FakeIO]:
    """A machine with a string in memory at a0 (the usual shape of a service)."""
    io = FakeIO()
    m = machine(service, xlen=xlen, io=io, a0=DATA, **values)
    m.memory.write_bytes(DATA, text.encode() + b"\0")
    return m, io


# ------------------------------------------------------------- what is printed


@pytest.mark.parametrize("service, value, expected", [
    (1, -42, "-42"),
    (1, 0x7FFFFFFF, "2147483647"),
    (34, 0xFFFFFFFF, "0xffffffff"),
    (35, 5, "00000000000000000000000000000101"),
    (36, 0xFFFFFFFF, "4294967295"),
    (11, 0x41, "A"),
    (11, 0x14A, "J"),  # only the lowest byte counts
])
def test_a_number_is_printed(service, value, expected):
    io = FakeIO()
    m = machine(service, io=io, a0=value)
    call(m)
    assert io.text == expected


@pytest.mark.parametrize("service, value, expected", [
    (1, 0x1FFFFFFFF, "8589934591"),  # the whole register, not its low half
    (34, 0x1FFFFFFFF, "0x00000001ffffffff"),
    (35, 1 << 40, "0" * 23 + "1" + "0" * 40),
    (36, 0xFFFFFFFFFFFFFFFF, "18446744073709551615"),
])
def test_a_number_of_a_64_bit_machine_is_printed_whole(service, value, expected):
    """The width rule: a service works with values as wide as the machine
    (DEV-47; RARS reads only the low 32 bits)."""
    io = FakeIO()
    m = machine(service, xlen=64, io=io, a0=value)
    call(m)
    assert io.text == expected


def test_a_string_is_printed_up_to_its_zero_byte():
    m, io = with_text(4, "hello")
    call(m)
    assert io.text == "hello"


def test_the_two_kinds_of_real_number_are_printed():
    io = FakeIO()
    m = machine(2, io=io)
    m.f.set_single(10, 0xC0200000)  # -2.5
    call(m)
    assert io.text == "-2.5"

    io = FakeIO()
    m = machine(3, io=io)
    m.f.set_double(10, 0x3FF8000000000000)  # 1.5
    call(m)
    assert io.text == "1.5"


# --------------------------------------------------------------- what is read


def test_a_number_is_read():
    io = FakeIO(reading="42\n")
    m = machine(5, io=io)
    call(m)
    assert m.x.signed(A0) == 42


def test_a_wide_number_is_read_by_a_64_bit_machine():
    """DEV-47 again: RARS would cut this to 32 bits."""
    io = FakeIO(reading="9999999999\n")
    m = machine(5, xlen=64, io=io)
    call(m)
    assert m.x.signed(A0) == 9999999999


@pytest.mark.parametrize("service, text, message", [
    (5, "abc\n", "Invalid integer input (syscall 5)"),
    (6, "abc\n", "Invalid float input (syscall 6)"),
    (7, "abc\n", "Invalid double input (syscall 7)"),
])
def test_input_that_is_no_number(service, text, message):
    """The messages of RARS, word for word."""
    m = machine(service, io=FakeIO(reading=text))
    with pytest.raises(Trap) as raised:
        call(m)
    assert (raised.value.cause, raised.value.message) == (ENVIRONMENT_CALL, message)


def test_the_two_kinds_of_real_number_are_read():
    m = machine(6, io=FakeIO(reading="-2.5\n"))
    call(m)
    assert m.f.single(10) == 0xC0200000
    m = machine(7, io=FakeIO(reading="0.1\n"))
    call(m)
    assert m.f.double(10) == 0x3FB999999999999A  # read exactly, rounded once


def test_a_character_is_read_and_the_end_of_the_input_is_refused():
    m = machine(12, io=FakeIO(reading="Z"))
    call(m)
    assert m.x.read(A0) == 0x5A
    m = machine(12, io=FakeIO(reading=""))
    with pytest.raises(Trap) as raised:
        call(m)
    assert raised.value.message == "Invalid char input (syscall 12)"


@pytest.mark.parametrize("reading, room, expected", [
    ("ab\n", 6, b"ab\n\0"),  # a line that fits keeps its newline, as in RARS
    ("abcdefgh\n", 6, b"abcde\0"),  # a longer one is cut to room less one
    ("", 6, b"\0"),  # the end of the input leaves an empty string
])
def test_a_line_is_read_into_a_buffer(reading, room, expected):
    io = FakeIO(reading=reading)
    m = machine(8, io=io, a0=DATA, a1=room)
    m.memory.write_bytes(DATA, b"\xff" * 8)
    call(m)
    assert m.memory.read_bytes(DATA, len(expected)) == expected


# ------------------------------------------------------------ the machine itself


def test_the_heap_grows_piece_by_piece():
    io = FakeIO()
    m = machine(9, io=io, a0=16)
    call(m)
    assert m.x.read(A0) == DEFAULT.heap_base
    m.x.write(A7, 9)
    m.x.write(A0, 32)
    m.x.pc = TEXT
    call(m)
    assert m.x.read(A0) == DEFAULT.heap_base + 16 and m.heap == DEFAULT.heap_base + 48


@pytest.mark.parametrize("service, code, expected", [(10, 7, 0), (93, 7, 7), (93, -1, -1)])
def test_the_program_asks_to_stop(service, code, expected):
    m = machine(service, a0=code)
    with pytest.raises(Exited) as raised:
        call(m)
    assert raised.value.code == expected


def test_the_working_directory():
    io = FakeIO()
    m = machine(17, io=io, a0=DATA, a1=32)
    call(m)
    assert m.memory.read_bytes(DATA, 6) == b"/here\0"
    # and a buffer too small is refused with -1, as the documentation says
    m = machine(17, io=io, a0=DATA, a1=3)
    call(m)
    assert m.x.signed(A0) == -1


def test_the_time_of_a_32_bit_machine_comes_in_two_halves():
    io = FakeIO()
    m = Machine(Options(), clock=lambda: 0x1A0BEEFCAFE, io=io)
    m.memory.poke(TEXT, 4, ECALL)
    m.x.write(A7, 30)
    call(m)
    assert (m.x.read(A0), m.x.read(A1)) == (0xBEEFCAFE, 0x1A0)


def test_the_time_of_a_64_bit_machine_comes_whole():
    """DEV-47: the whole count in a0, and a1 zero - so a program that puts the
    pair together itself still reads the right number."""
    io = FakeIO()
    m = Machine(Options(xlen=64), clock=lambda: 0x1A0BEEFCAFE, io=io)
    m.memory.poke(TEXT, 4, ECALL)
    m.x.write(A7, 30)
    call(m)
    assert (m.x.read(A0), m.x.read(A1)) == (0x1A0BEEFCAFE, 0)


def test_sleeping_is_asked_of_the_world_and_not_done_here():
    io = FakeIO()
    m = machine(32, io=io, a0=500)
    call(m)
    assert io.slept == [500]


@pytest.mark.parametrize("service", [31, 33])
def test_the_services_of_midi_are_answered_and_play_nothing(service):
    io = FakeIO()
    m = machine(service, io=io, a0=60)
    call(m)
    assert io.written == []


def test_an_unknown_service():
    m = machine(777)
    with pytest.raises(Trap) as raised:
        call(m)
    assert raised.value.message == "Invalid or unimplemented syscall service 777"


# ---------------------------------------------------------- the random numbers


def test_a_seeded_stream_gives_the_same_numbers_again():
    """DEV-50: the numbers are our own, and a seed makes them repeat."""
    def draw() -> list[int]:
        io = FakeIO()
        m = machine(40, io=io, a0=0, a1=12345)
        call(m)
        values = []
        for service in (41, 42, 41):
            m.x.write(A7, service)
            m.x.write(A0, 0)
            m.x.write(A1, 100)
            m.x.pc = TEXT
            call(m)
            values.append(m.x.read(A0))
        return values

    first = draw()
    assert draw() == first
    assert 0 <= first[1] < 100  # the bound is not included


def test_the_random_reals_lie_between_zero_and_one():
    from pyrars.softfloat.compare import less, less_equal
    from pyrars.softfloat.formats import BINARY32, BINARY64
    io = FakeIO()
    m = machine(40, io=io, a0=0, a1=7)
    call(m)
    for service, fmt, read in ((43, BINARY32, lambda: m.f.single(10)),
                               (44, BINARY64, lambda: m.f.double(10))):
        for _ in range(20):
            m.x.write(A7, service)
            m.x.write(A0, 0)
            m.x.pc = TEXT
            call(m)
            value = read()
            one = 0x3F800000 if fmt is BINARY32 else 0x3FF0000000000000
            assert less_equal(0, value, fmt)[0] and less(value, one, fmt)[0]


# ---------------------------------------------------------------- the dialogs


def test_a_message_dialog_is_printed():
    m, io = with_text(55, "look here", a1=1)
    io.answers.append(None)
    call(m)
    assert io.asked == [(Dialog.MESSAGE, "look here")]


def test_a_message_dialog_with_a_number_or_a_string():
    m, io = with_text(56, "value: ", a1=-7)
    io.answers.append(None)
    call(m)
    assert io.asked[0][1] == "value: -7"

    m, io = with_text(58, "double: ")
    m.f.set_double(10, 0x3FF8000000000000)
    io.answers.append(None)
    call(m)
    assert io.asked[0][1] == "double: 1.5"

    m, io = with_text(60, "float: ")
    m.f.set_single(11, 0xC0200000)  # fa1, as the documentation says
    io.answers.append(None)
    call(m)
    assert io.asked[0][1] == "float: -2.5"


def test_a_confirmation_comes_back_in_a0():
    for answer in (0, 1, 2):
        m, io = with_text(50, "sure?")
        io.answers.append(answer)
        call(m)
        assert m.x.read(A0) == answer


@pytest.mark.parametrize("service, answer, status, check", [
    (51, ("42", 0), 0, lambda m: m.x.signed(A0) == 42),
    (51, ("abc", 0), -1, lambda m: m.x.read(A0) == 0),  # no number
    (51, ("", -2), -2, lambda m: m.x.read(A0) == 0),  # cancelled
    (51, ("", -3), -3, lambda m: m.x.read(A0) == 0),  # nothing entered
    (52, ("-2.5", 0), 0, lambda m: m.f.single(10) == 0xC0200000),
    (53, ("1.5", 0), 0, lambda m: m.f.double(10) == 0x3FF8000000000000),
])
def test_a_dialog_that_asks_for_a_number(service, answer, status, check):
    m, io = with_text(service, "number?")
    io.answers.append(answer)
    call(m)
    assert m.x.signed(A1) == status and check(m)


@pytest.mark.parametrize("answer, room, status, kept", [
    (("hello", 0), 32, 0, b"hello\0"),
    (("hello", 0), 4, -4, b"hel\0"),  # longer than the buffer
    (("", -2), 32, -2, b"\xff\xff"),  # cancelled: the buffer is left alone
])
def test_a_dialog_that_asks_for_a_string(answer, room, status, kept):
    io = FakeIO(answers=[answer])
    m = machine(54, io=io, a0=DATA, a1=DATA + 64, a2=room)
    m.memory.write_bytes(DATA, b"ask?\0")
    m.memory.write_bytes(DATA + 64, b"\xff" * 8)
    call(m)
    assert m.x.signed(A1) == status
    assert m.memory.read_bytes(DATA + 64, len(kept)) == kept


# ----------------------------------------------------------------- the files


def test_a_file_is_opened_written_read_and_closed():
    io = FakeIO()
    m = machine(1024, io=io, a0=DATA, a1=1)
    m.memory.write_bytes(DATA, b"file.txt\0")
    call(m)
    fd = m.x.read(A0)
    assert fd == 3 and io.opened == [("file.txt", 1)]

    m.x.write(A7, 64)  # Write
    m.x.write(A0, fd)
    m.x.write(A1, DATA + 16)
    m.x.write(A2, 4)
    m.memory.write_bytes(DATA + 16, b"data")
    m.x.pc = TEXT
    call(m)
    assert m.x.read(A0) == 4 and bytes(io.files[fd]) == b"data"

    m.x.write(A7, 62)  # LSeek to the beginning
    m.x.write(A0, fd)
    m.x.write(A1, 0)
    m.x.write(A2, 0)
    m.x.pc = TEXT
    call(m)
    assert m.x.read(A0) == 0

    m.x.write(A7, 63)  # Read it back
    m.x.write(A0, fd)
    m.x.write(A1, DATA + 32)
    m.x.write(A2, 4)
    m.x.pc = TEXT
    call(m)
    assert m.x.read(A0) == 4 and m.memory.read_bytes(DATA + 32, 4) == b"data"

    m.x.write(A7, 57)  # Close
    m.x.write(A0, fd)
    m.x.pc = TEXT
    call(m)
    assert m.x.read(A0) == 0 and fd not in io.files


@pytest.mark.parametrize("service, values, expected", [
    (1024, {"a0": DATA, "a1": 0}, -errno.ENOENT),  # a file that is not there
    (57, {"a0": 99}, -errno.EBADF),  # a descriptor nobody opened
    (62, {"a0": 99, "a1": 0, "a2": 0}, -errno.EBADF),
])
def test_a_file_service_that_fails_gives_the_number_of_the_error(service, values, expected):
    """DEV-48: the convention of the standard, where RARS answers -1."""
    io = FakeIO()
    m = machine(service, io=io, **values)
    m.memory.write_bytes(DATA, b"missing\0")
    call(m)
    assert m.x.signed(A0) == expected


# -------------------------------------------------- the arguments of a program


def program_for(xlen: int = 32):
    from pyrars.isa.program import AssembledProgram
    return AssembledProgram(xlen, "Default", (), DATA, b"", (), {}, frozenset(), TEXT, ())


def test_a_program_without_arguments_finds_the_stack_as_it_was():
    m = Machine(Options())
    m.load(program_for())
    assert m.x.read(2) == DEFAULT.stack_pointer  # sp
    assert (m.x.read(A0), m.x.read(A1)) == (0, 0)


def test_the_arguments_of_a_program_lie_where_rars_puts_them():
    """Verified against RARS: the texts end at the top of the stack, the table
    holds the count, the pointers and a zero, and its last word lies at the stack
    pointer the program would have started with."""
    m = Machine(Options())
    m.load(program_for(), ["hello", "world"])
    table = m.x.read(2)
    assert table == DEFAULT.stack_pointer - 12
    assert [m.memory.read(table + 4 * index, 4) for index in range(4)] == [
        2, DEFAULT.stack_base - 5, DEFAULT.stack_base - 11, 0]
    assert (m.x.read(A0), m.x.read(A1)) == (2, table + 4)
    assert m.memory.read_bytes(DEFAULT.stack_base - 5, 6) == b"hello\0"
    assert m.memory.read_bytes(DEFAULT.stack_base - 11, 6) == b"world\0"


def test_the_table_of_a_64_bit_machine_holds_wide_words():
    """DEV-47: the words of the table are as wide as the machine, as the process
    startup of the standard has them; RARS keeps four bytes in both widths."""
    m = Machine(Options(xlen=64))
    m.load(program_for(64), ["one", "two"])
    table = m.x.read(2)
    assert table % 8 == 0
    assert [m.memory.read(table + 8 * index, 8) for index in range(4)] == [
        2, DEFAULT.stack_base - 3, DEFAULT.stack_base - 7, 0]
    assert m.x.read(A1) == table + 8
