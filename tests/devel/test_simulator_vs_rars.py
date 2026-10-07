"""T-SIM-END, stage 22: whole programs run by both command lines.

This is what closes M4: the programs of the corpus, which until now were only
assembled by both (T-CORPUS), are now RUN by both, and everything a run leaves
behind is compared - every register, a range of the data segment, what the program
wrote, how many instructions it carried out, the line that says why it ended, and
the code it exited with.

Both outputs are read by the same parser, because our command line prints these
values exactly as RARS prints them (`name<tab>value`, `Mem[0x…]<tab>…`); the report
lines are the ones of RARS as well. Where we differ, the test states both sides:
the whole of a register of a 64-bit machine (DEV-47), the one shape of a message
(DEV-54), and the two reasons RARS has no line for (DEV-55).

A program that writes anything gets no register dump from RARS and no termination
line either (verified again here), so such a program is compared by what it wrote
and the code it exited with.
"""

import io
import re
from pathlib import Path

import pytest

import oracle
from pyrars.cli import main
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

CORPUS = Path(__file__).with_name("corpus")
DATA = DEFAULT.data_base
WORDS = 8
NAMES = tuple(f"x{number}" for number in range(1, 32))
RANGE = f"{DATA:#x}-{DATA + 4 * (WORDS - 1):#x}"

# What a run left behind, as both command lines write it.
REGISTER = re.compile(r"^([a-z]\w*)\t(-?\w+)$")
MEMORY = re.compile(r"^Mem\[(0x[0-9a-f]+)]\t(.*)$")
COUNT = re.compile(r"^(?:instructions\t)?(\d+)\s*$")


def dump(text: str) -> tuple[dict[str, int], list[int], int | None]:
    """The registers, the words of memory and the instruction count of an output.

    A value that appears twice is taken from the later place, because RARS prints
    everything it was asked for at EVERY stop: a program with `ebreak` stops there,
    gets a whole dump, and carries on to be dumped again (verified with
    `corpus/system.s`, which holds an `ebreak`). Ours prints once, at the end of the
    run (DEV-55), so the last dump of RARS is the one to compare with.
    """
    registers, words, count = {}, {}, None
    for line in text.splitlines():
        found = MEMORY.match(line)
        if found:
            place = int(found.group(1), 16)
            for index, value in enumerate(found.group(2).split()):
                words[place + 4 * index] = int(value, 16)
            continue
        found = REGISTER.match(line)
        if found and found.group(1) != "instructions":
            registers[found.group(1)] = int(found.group(2), 16)
            continue
        found = COUNT.match(line)
        if found:
            count = int(found.group(1))
    return registers, [words[place] for place in sorted(words)], count


def ours(files, *options, given: str = "", arguments: tuple[str, ...] = ()):
    """(exit code, what the program and the values went to, the report) of our run."""
    out, errors = io.StringIO(), io.StringIO()
    argv = ["run", *options, *(str(f) for f in files)]
    if arguments:
        argv += ["--args", *arguments]
    code = main(argv, out=out, errors=errors, reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


SILENT = ["arithmetic", "control", "floating", "memory", "system"]

# A program that reads the wall clock leaves a value no two runs can share: in
# `system.s` the service-less `time` lands in t2 (x7) and a5 (x15).
CLOCK = {"system": ("x7", "x15")}

# Two of the programs end with `ret` while `ra` is zero, so they jump to the address
# zero: both machines stop on a fetch they cannot make, and neither runs off the
# bottom of its text.
JUMP_TO_ZERO = ("arithmetic", "memory")


def without_the_clock(values: dict[str, int], name: str) -> dict[str, int]:
    return {key: value for key, value in values.items() if key not in CLOCK.get(name, ())}


def same(ours_text: str, theirs_text: str, name: str = "") -> None:
    """Every value both command lines printed, read by the same parser."""
    our_registers, our_words, our_count = dump(ours_text)
    their_registers, their_words, their_count = dump(theirs_text)
    assert without_the_clock(our_registers, name) == without_the_clock(their_registers, name)
    assert (our_words, our_count) == (their_words, their_count)


@pytest.mark.parametrize("name", SILENT)
def test_a_program_of_the_corpus(name, rars, tmp_path):
    """`system.s` also shows what RARS does with `ebreak` from a command line: it
    stops there, prints everything it was asked for, and carries on - so its output
    holds two dumps and the instruction count 17 before 18. Ours carries on without
    stopping and prints once (DEV-55); the final values are the same."""
    path = CORPUS / f"{name}.s"
    their = rars.run([path], options=("ic", RANGE, *NAMES), max_steps=100_000)
    code, out, report = ours([path], "-c", "-r", ",".join(NAMES), "--memory", RANGE)

    same(out, their.stdout, name)
    assert code == their.exit_code
    if name in JUMP_TO_ZERO:
        # RARS names neither the address it could not fetch from nor a file it has
        # no line of: `Error in : Instruction load access error` (DEV-54).
        assert "Instruction load access error" in their.stdout
        assert report.splitlines()[1] == (
            "Error: Runtime exception at 0x00000000: "
            "Cannot fetch an instruction from 0x00000000")
    else:
        assert report.strip() in their.stdout


@pytest.mark.parametrize("name", SILENT)
def test_the_same_programs_stop_at_the_same_step(name, rars, tmp_path):
    """Half way through a program the machines hold the same values as well, which
    tells a divergence in the middle from one at the end."""
    path = CORPUS / f"{name}.s"
    their = rars.run([path], options=("ic", RANGE, *NAMES), max_steps=5)
    code, out, report = ours([path], "-c", "-r", ",".join(NAMES), "--memory", RANGE,
                             "--steps", "5")
    same(out, their.stdout, name)
    assert "maximum step limit 5 reached" in their.stdout
    assert report.strip() == "Program terminated when maximum step limit 5 reached."


def test_a_program_that_writes(rars, tmp_path):
    """RARS gives a writing program no dump and no termination line, so what it
    wrote and the code it exited with are what there is to compare."""
    path = CORPUS / "strings.s"
    their = rars.run([path], options=("ic", RANGE, *NAMES))
    code, out, _ = ours([path])
    assert out == their.stdout
    assert code == their.exit_code
    assert dump(their.stdout) == ({}, [], None)


def test_a_program_that_runs_off_its_text(rars, tmp_path):
    """A program whose last instruction is simply the last word of its text: both
    machines say the same about it."""
    path = tmp_path / "p.s"
    path.write_text(".text\nmain:   li t0, 5\n        addi t1, t0, 1\n")
    their = rars.run([path], options=("ic", *NAMES))
    code, out, report = ours([path], "-c", "-r", ",".join(NAMES))
    same(out, their.stdout)
    assert "Program terminated by dropping off the bottom." in their.stdout
    assert report.strip() == "Program terminated by dropping off the bottom."
    assert code == their.exit_code == 0


def test_a_trap_stops_both_in_the_same_place(rars, tmp_path):
    """The report of RARS, word for word, except the message itself, which has the
    one shape of every message of the machine (DEV-54)."""
    path = tmp_path / "p.s"
    path.write_text(".text\nmain:   li t0, 1\n        lw t1, 1(x0)\n")
    their = rars.run([path], options=("x5",))
    code, _, report = ours([path])

    assert (f"Error in {path} line 3: Runtime exception at 0x00400004: "
            "Load address not aligned to word boundary 0x00000001") in their.stdout
    assert report.splitlines()[1] == (
        f"Error in {path} line 3: Runtime exception at 0x00400004: "
        "Load address not aligned to word boundary 0x00000001")
    assert "Simulation terminated due to errors." in their.stdout
    assert "Simulation terminated due to errors." in report
    assert (code, their.exit_code) == (1, 1)


def test_both_read_the_same_input(rars, tmp_path):
    path = tmp_path / "p.s"
    path.write_text("""\
.text
main:   li a7, 5
        ecall
        mv t0, a0
        li a7, 5
        ecall
        add a0, a0, t0
        li a7, 1
        ecall
        li a7, 93
        li a0, 0
        ecall
""")
    their = rars.run([path], stdin="17\n25\n")
    code, out, _ = ours([path], given="17\n25\n")
    assert out == their.stdout == "42"
    assert code == their.exit_code == 0


def test_both_hand_a_program_its_arguments(rars, tmp_path):
    path = tmp_path / "p.s"
    path.write_text("""\
.text
main:   mv t0, a1
        li a7, 1
        ecall
        li a7, 11
        li a0, 32
        ecall
        lw a0, 0(t0)
        lb a0, 0(a0)
        li a7, 11
        ecall
        li a7, 93
        li a0, 0
        ecall
""")
    their = rars.run([path], arguments=("one", "two"))
    code, out, _ = ours([path], arguments=("one", "two"))
    assert out == their.stdout == "2 o"
    assert code == their.exit_code


def test_a_64_bit_program(rars, tmp_path):
    """RARS prints the low 32 bits of a register and we print the whole of it
    (DEV-47), so the comparison masks ours; the wide values are compared through
    memory, where both write eight bytes."""
    path = tmp_path / "p.s"
    path.write_text("""\
.data
v:      .dword 0, 0
.text
main:   li t0, 1
        slli t1, t0, 40
        la t2, v
        sd t1, 0(t2)
        addi t3, t1, -1
        sd t3, 8(t2)
        li a7, 93
        li a0, 0
        ecall
""")
    their = rars.run([path], options=("rv64", "ic", RANGE, *NAMES))
    code, out, _ = ours([path], "-x", "64", "-c", "-r", ",".join(NAMES),
                        "--memory", RANGE)

    our_registers, our_words, our_count = dump(out)
    their_registers, their_words, their_count = dump(their.stdout)
    assert {place: value & 0xFFFFFFFF for place, value in our_registers.items()} \
        == their_registers
    assert (our_words, our_count) == (their_words, their_count)
    assert our_registers["x6"] == 1 << 40  # the whole register, which RARS cuts
    assert code == their.exit_code


def test_the_breakpoint_of_our_command_line_has_no_counterpart(rars, tmp_path):
    """RARS has breakpoints only in its window; from a command line there is no way
    to ask for one (DEV-55). Both machines agree on everything up to that point."""
    path = CORPUS / "control.s"
    their = rars.run([path], options=("ic", RANGE, *NAMES), max_steps=4)
    code, out, report = ours([path], "-c", "-r", ",".join(NAMES), "--memory", RANGE,
                             "--break", "0x00400010")
    same(out, their.stdout)
    assert report.strip() == "Program stopped at a breakpoint 0x00400010"
    assert not any("breakpoint" in line for line in their.stdout.splitlines())
