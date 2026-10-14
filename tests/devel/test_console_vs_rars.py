"""T-DBG, stage 37: a scripted session of the console debugger against RARS.

RARS has no console debugger at all, so what can be compared is not the session
but where it LEAVES the machine: a session told to go N instructions forward and k
back must stand in the state RARS stands in at N-k. That is the idea of T-HIST
(stage 21) read through the front-end instead of through the engine, and it tests
the whole way down - the command language, the session, the journal, the loop.

Everything the session itself says - the prompts, the tables, the commands - is
tested in `tests/unit/test_console.py`, because there is nothing to compare it
with.

Every program here ends in an endless jump, so that a step limit always falls
inside it and the state at that step is well defined.
"""

import io

import pytest

from pyrars.asm.assembler import Options as AsmOptions
from pyrars.asm.assembler import assemble
from pyrars.cli import main
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

DATA = DEFAULT.data_base
WORDS = 8  # words of the data segment that are compared
NAMES = tuple(f"x{number}" for number in range(1, 32))
END = "end:    j end\n"

PROGRAMS = {
    # name: (source, instructions forward, steps taken back)
    "arithmetic": ("""\
.text
main:   li t0, 0x12345678
        li t1, -3
        add t2, t0, t1
        sub t3, t0, t1
        xor t4, t0, t1
        mul t5, t0, t1
        div t6, t0, t1
        slt s0, t1, t0
        srai s1, t0, 7
""" + END, 12, 4),
    "memory and a loop": ("""\
.data
v:      .word 0x89abcdef, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        li t1, 4
        li t2, 0
loop:   lw t3, 0(t0)
        add t2, t2, t3
        addi t0, t0, 4
        addi t1, t1, -1
        bne t1, x0, loop
        la t0, v
        sw t2, 4(t0)
""" + END, 20, 7),
    "a call and its return": ("""\
.data
v:      .word 0, 0, 0, 0, 0, 0, 0, 0
.text
main:   li a0, 21
        jal ra, double
        la t0, v
        sw a0, 0(t0)
        j end
double: add a0, a0, a0
        ret
""" + END, 9, 3),
}


def session(source: str, tmp_path, forward: int, back: int):
    """Our machine as a scripted session of the console leaves it, read out of the
    transcript the session itself printed."""
    path = tmp_path / "p.s"
    path.write_text(source)
    out, errors = io.StringIO(), io.StringIO()
    code = main(["run", "--debug-mode", str(path),
                 "-e", f"step {forward}", "-e", f"back {back}",
                 "-e", "regs", "-e", f"mem {DATA:#x}..{DATA + 4 * WORDS - 1:#x}",
                 "-e", "quit"],
                out=out, errors=errors, reader=io.StringIO())
    assert code == 0, out.getvalue()
    assert errors.getvalue() == "", errors.getvalue()
    registers, words = _registers(out.getvalue()), _words(out.getvalue())
    # The transcript is read by its shape, so say at once if the shape has moved:
    # a parser that quietly finds nothing would make every comparison below true.
    assert len(registers) == 31, out.getvalue()
    assert len(words) == WORDS, out.getvalue()
    return registers, words


def _registers(transcript: str) -> dict[int, int]:
    """The registers of the `regs` table, by their numbers."""
    found = {}
    for line in transcript.splitlines():
        pieces = [piece.strip() for piece in line.split("|")]
        if len(pieces) == 3 and pieces[1].startswith("x") and pieces[1][1:].isdigit():
            found[int(pieces[1][1:])] = int(pieces[2], 16) & 0xFFFFFFFF
    return {number: value for number, value in found.items() if number}


def _words(transcript: str) -> list[int]:
    """The words of the `mem` table, in the order they were printed."""
    found = []
    for line in transcript.splitlines():
        pieces = [piece.strip() for piece in line.split("|")]
        if len(pieces) > 1 and pieces[0].startswith(f"0x{DATA:08x}"[:6]):
            if all(piece.startswith("0x") for piece in pieces[1:]):
                found += [int(piece, 16) for piece in pieces[1:]]
    return found


def theirs(rars, source: str, tmp_path, steps: int):
    """The state RARS stands in when it has carried out `steps` instructions."""
    path = tmp_path / "p.s"
    path.write_text(source)
    options = (f"{DATA:#x}-{DATA + 4 * WORDS - 4:#x}",) + NAMES
    done = rars.run([path], options=options, max_steps=steps)
    assert done.messages == [], done.stdout
    assert f"maximum step limit {steps} reached" in done.stdout, done.stdout
    registers, words = {}, []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("x"):
            registers[int(parts[0][1:])] = int(parts[1], 16)
        elif parts and parts[0].startswith("Mem["):
            words += [int(value, 16) for value in parts[1:]]
    return registers, words


@pytest.mark.parametrize("name", tuple(PROGRAMS))
def test_a_session_that_went_back_stands_where_rars_stands(name, tmp_path, rars):
    source, forward, back = PROGRAMS[name]
    program = assemble([str(_written(source, tmp_path))], AsmOptions())
    assert program.diagnostics == (), program.diagnostics

    ours = session(source, tmp_path, forward, back)
    expected = theirs(rars, source, tmp_path, forward - back)
    assert ours[0] == expected[0]
    assert ours[1] == expected[1]


@pytest.mark.parametrize("name", tuple(PROGRAMS))
def test_a_session_that_only_went_forward_stands_where_rars_stands(name, tmp_path,
                                                                   rars):
    """The other half: the steps back are what the first test is about, so the same
    session without them must agree as well, or nothing is proved."""
    source, forward, _ = PROGRAMS[name]
    ours = session(source, tmp_path, forward, 0)
    expected = theirs(rars, source, tmp_path, forward)
    assert ours[0] == expected[0]
    assert ours[1] == expected[1]


def _written(source: str, tmp_path):
    path = tmp_path / "p.s"
    path.write_text(source)
    return path
