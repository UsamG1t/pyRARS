"""T-SYS, stage 20: the services of a program against RARS.

A program that prints gets no register dump from the command line of RARS
(verified), so these tests compare what a program WRITES, and its exit code. The
input a program reads is given to both the same way.

What differs on purpose, each stated on both sides:
 - DEV-47: a service works at the width of the machine, so in RV64 our numbers are
   printed whole where RARS shows the low 32 bits;
 - DEV-48: a file service that fails gives the negative of its error number where
   RARS gives -1 (the tests compare the sign, since both mean "it failed");
 - DEV-49: a dialog becomes the console, where RARS opens a window and dies
   without one;
 - DEV-50: the random numbers are ours, not those of the Java generator.
"""

import io as streams
import subprocess

import pytest

import driver
from pyrars.asm.assembler import Options as AsmOptions
from pyrars.asm.assembler import assemble
from pyrars.core.options import Options
from pyrars.core.systemio import ConsoleIO

pytestmark = pytest.mark.devel

EXIT = "        li a7, 93\n        li a0, 0\n        ecall\n"


def ours(source: str, tmp_path, xlen: int = 32, given: str = "") -> tuple[str, int]:
    """What our machine writes, and the code it exits with."""
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions(xlen=xlen))
    assert program.diagnostics == (), program.diagnostics
    out = streams.StringIO()
    console = ConsoleIO(out=out, errors=out, reader=streams.StringIO(given))
    outcome = driver.run(program, Options(xlen=xlen), io=console)
    assert outcome.reason == "exit", outcome.reason
    return out.getvalue(), outcome.code


def theirs(rars, tmp_path, xlen: int = 32, given: str = "") -> tuple[str, int]:
    done = rars.run([tmp_path / "p.s"], options=("rv64",) if xlen == 64 else (), stdin=given)
    return done.stdout, done.exit_code


PROGRAMS = {
    "the printing services": """\
.data
msg:    .asciz "text "
f:      .float -2.5
d:      .double 0.1
.text
main:   la a0, msg
        li a7, 4
        ecall
        li a0, -42
        li a7, 1
        ecall
        li a0, 32
        li a7, 11
        ecall
        li a0, -1
        li a7, 34
        ecall
        li a0, 32
        li a7, 11
        ecall
        li a0, 5
        li a7, 35
        ecall
        li a0, 32
        li a7, 11
        ecall
        li a0, -1
        li a7, 36
        ecall
        li a0, 10
        li a7, 11
        ecall
        la t0, f
        flw fa0, 0(t0)
        li a7, 2
        ecall
        li a0, 32
        li a7, 11
        ecall
        la t0, d
        fld fa0, 0(t0)
        li a7, 3
        ecall
        li a0, 10
        li a7, 11
        ecall
""",
    "the heap and the character services": """\
.text
main:   li a0, 16
        li a7, 9
        ecall
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a0, 24
        li a7, 9
        ecall
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a0, 0x7a
        li a7, 11
        ecall
        li a0, 10
        li a7, 11
        ecall
""",
}

READING = {
    "numbers from the input": ("""\
.text
main:   li a7, 5
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a7, 6
        ecall
        li a7, 2
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a7, 7
        ecall
        li a7, 3
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a7, 12
        ecall
        li a7, 11
        ecall
        li a0, 10
        li a7, 11
        ecall
""", "42\n-2.5\n0.1\nQ\n"),
    "a line from the input": ("""\
.data
buf:    .space 32
.text
main:   la a0, buf
        li a1, 8
        li a7, 8
        ecall
        la a0, buf
        li a7, 4
        ecall
        la a0, buf
        li a1, 8
        li a7, 8
        ecall
        la a0, buf
        li a7, 4
        ecall
        li a0, 10
        li a7, 11
        ecall
""", "ab\nabcdefghij\n"),
}


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_a_program_that_prints(rars, tmp_path, name):
    source = PROGRAMS[name] + EXIT
    assert ours(source, tmp_path) == theirs(rars, tmp_path)


@pytest.mark.parametrize("name", list(READING))
def test_a_program_that_reads(rars, tmp_path, name):
    source, given = READING[name]
    assert ours(source + EXIT, tmp_path, given=given) == theirs(rars, tmp_path, given=given)


def test_the_code_a_program_exits_with(rars, tmp_path):
    source = ".text\nmain:   li a0, 7\n        li a7, 93\n        ecall\n"
    assert ours(source, tmp_path)[1] == 7
    assert theirs(rars, tmp_path)[1] == 7

    source = ".data\nm: .asciz \"bye\\n\"\n.text\nmain:   la a0, m\n        li a7, 4\n        ecall\n" \
             "        li a0, 0\n        li a7, 10\n        ecall\n"
    assert ours(source, tmp_path) == theirs(rars, tmp_path)


@pytest.mark.parametrize("source, text", [
    (".text\nmain:   li a7, 5\n        ecall\n", "invalid integer input (syscall 5)"),
    (".text\nmain:   li a7, 777\n        ecall\n",
     "invalid or unimplemented syscall service: 777"),
])
def test_a_service_that_cannot_do_what_it_was_asked(rars, tmp_path, source, text):
    """The message of RARS, word for word, and both machines stop there."""
    path = tmp_path / "p.s"
    path.write_text(source + EXIT)
    program = assemble([str(path)], AsmOptions())
    outcome = driver.run(program, Options(), io=ConsoleIO(
        out=streams.StringIO(), reader=streams.StringIO("abc\n" if "5" in source else "")))
    assert outcome.reason == text

    done = rars.run([path], stdin="abc\n")
    assert any(text in line for line in done.stdout.splitlines()), done.stdout


def test_the_working_directory_is_the_same_for_both(rars, tmp_path):
    source = """\
.data
buf:    .space 256
.text
main:   la a0, buf
        li a1, 256
        li a7, 17
        ecall
        la a0, buf
        li a7, 4
        ecall
        li a0, 10
        li a7, 11
        ecall
""" + EXIT
    assert ours(source, tmp_path) == theirs(rars, tmp_path)


def test_a_file_written_and_read_back(rars, tmp_path, monkeypatch):
    """Both machines work on real files; each run gets its own directory."""
    source = """\
.data
name:   .asciz "probe.txt"
text:   .asciz "written by a program"
buf:    .space 32
.text
main:   la a0, name
        li a1, 1
        li a7, 1024
        ecall
        mv s1, a0
        mv a0, s1
        la a1, text
        li a2, 20
        li a7, 64
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
        mv a0, s1
        li a7, 57
        ecall
        la a0, name
        li a1, 0
        li a7, 1024
        ecall
        mv s1, a0
        mv a0, s1
        la a1, buf
        li a2, 20
        li a7, 63
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
        la a0, buf
        li a7, 4
        ecall
        li a0, 10
        li a7, 11
        ecall
        mv a0, s1
        li a1, 0
        li a2, 0
        li a7, 62
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
""" + EXIT
    monkeypatch.chdir(tmp_path)
    mine = ours(source, tmp_path)
    (tmp_path / "probe.txt").unlink()
    assert mine == theirs(rars, tmp_path)


def test_a_file_service_that_fails(rars, tmp_path):  # DEV-48
    """Both answer with a negative number, and only its size differs: ours is the
    error number of the standard, theirs is -1."""
    source = """\
.data
name:   .asciz "no_such_file"
.text
main:   la a0, name
        li a1, 0
        li a7, 1024
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a0, 99
        li a1, 0
        li a2, 4
        li a7, 63
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
""" + EXIT
    mine = [int(line) for line in ours(source, tmp_path)[0].split()]
    their = [int(line) for line in theirs(rars, tmp_path)[0].split()]
    assert all(value < 0 for value in mine) and all(value < 0 for value in their)
    assert mine == [-2, -9] and their == [-1, -1]  # ENOENT and EBADF against -1


def test_the_width_of_a_service_on_a_64_bit_machine(rars, tmp_path):  # DEV-47
    """Ours reads the whole register, RARS only its low half."""
    source = """\
.text
main:   li a0, 0x1ffffffff
        li a7, 36
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a0, 0x1ffffffff
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
        li a7, 30
        ecall
        beqz a1, same
        li a0, 0x3f
        li a7, 11
        ecall
same:   li a0, 10
        li a7, 11
        ecall
""" + EXIT
    assert ours(source, tmp_path, xlen=64)[0] == "8589934591\n0x00000001ffffffff\n\n"
    # RARS: the low half, eight digits, and the halves of the time in a0 and a1
    assert theirs(rars, tmp_path, xlen=64)[0] == "4294967295\n0xffffffff\n?\n"


def test_a_dialog_without_a_window_system(rars, tmp_path):  # DEV-49
    """Ours prints the message and reads the answer; RARS dies without a window."""
    source = """\
.data
ask:    .asciz "a number? "
.text
main:   la a0, ask
        li a7, 51
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
        mv a0, a1
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
""" + EXIT
    assert ours(source, tmp_path, given="17\n") == ("a number? 17\n0\n", 0)

    done = rars.run([tmp_path / "p.s"], stdin="17\n")
    assert "HeadlessException" in done.stderr


def test_the_random_numbers_are_ours(rars, tmp_path):  # DEV-50
    """A seed makes ours repeat, which is what a program needs; the numbers
    themselves are not those of the Java generator."""
    source = """\
.text
main:   li a0, 0
        li a1, 12345
        li a7, 40
        ecall
        li a0, 0
        li a1, 100
        li a7, 42
        ecall
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
""" + EXIT
    mine = ours(source, tmp_path)[0]
    assert mine == ours(source, tmp_path)[0]  # the same seed, the same number
    assert 0 <= int(mine) < 100
    their = theirs(rars, tmp_path)[0]
    assert 0 <= int(their) < 100 and their != mine


def test_a_program_that_sleeps_costs_a_test_nothing(rars, tmp_path):
    """The sleeping lives in the world outside the machine, so a test gives one
    that only writes the request down (user decision 2026-10-03)."""
    source = ".text\nmain:   li a0, 5000\n        li a7, 32\n        ecall\n" + EXIT
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions())

    class Recording(ConsoleIO):
        def __init__(self) -> None:
            super().__init__(out=streams.StringIO(), reader=streams.StringIO(""))
            self.slept: list[int] = []

        def sleep(self, milliseconds: int) -> None:
            self.slept.append(milliseconds)

    world = Recording()
    assert driver.run(program, Options(), io=world).reason == "exit"
    assert world.slept == [5000]

    # RARS really sleeps, so it needs more time than it is given here
    with pytest.raises(subprocess.TimeoutExpired):
        rars.run([path], timeout=2)


ARGUMENTS = """\
.text
main:   mv s1, a0
        mv s2, a1
        li s3, 0
loop:   beq s3, s1, done
        slli t0, s3, 2
        add t0, t0, s2
        lw a0, 0(t0)
        li a7, 4
        ecall
        li a0, 10
        li a7, 11
        ecall
        addi s3, s3, 1
        j loop
done:   mv a0, s1
        li a7, 1
        ecall
        li a0, 10
        li a7, 11
        ecall
"""


def test_a_program_reads_its_arguments(rars, tmp_path):
    """The texts and the table lie where RARS puts them, so the same program
    finds them in both machines."""
    path = tmp_path / "p.s"
    path.write_text(ARGUMENTS + EXIT)
    program = assemble([str(path)], AsmOptions())
    assert program.diagnostics == ()
    out = streams.StringIO()
    outcome = driver.run(program, Options(), io=ConsoleIO(out=out, reader=streams.StringIO("")),
                         arguments=["hello", "world"])
    assert outcome.reason == "exit"

    done = rars.run([path], arguments=("hello", "world"))
    assert out.getvalue() == done.stdout == "hello\nworld\n2\n"
