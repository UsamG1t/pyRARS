"""T-HIST, stage 21: the journal of a step against RARS.

RARS cannot be asked to take a step back from its command line - that is an action
of its window - so the journal is compared the other way round: RARS is stopped at
the step limit and prints the state it reached, while our machine runs further and
then takes the extra steps back. What the journal puts back must be exactly the
state RARS stands in, which makes RARS the witness of the truth at that step.

The other half of the test runs forward again afterwards: a machine that took
steps back must carry on to the same state as one that never did, and RARS tells
what that state is as well.

Every program here ends in an endless jump, so that a step limit always falls
inside it and the state at the limit is well defined; the limit is counted from
the number of words our assembler produced, which T-ASM proved equal to the code
of RARS.
"""

import pytest

import driver
from pyrars.asm.assembler import Options as AsmOptions
from pyrars.asm.assembler import assemble
from pyrars.core.options import Options
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

DATA = DEFAULT.data_base
WORDS = 8  # words of the data segment that are compared
NAMES = tuple(f"x{number}" for number in range(1, 32))


def ours(source: str, tmp_path, steps: int, back: int = 0, forward: int = 0,
         xlen: int = 32) -> tuple[dict[int, int], list[int]]:
    """Our machine after `steps` steps, `back` steps back and `forward` again."""
    program = compiled(source, tmp_path, xlen)
    outcome = driver.run(program, Options(xlen=xlen, history_depth=2000), steps=steps)
    assert outcome.reason == "steps", outcome.reason
    machine = outcome.machine
    for _ in range(back):
        assert outcome.simulator.back_step() is True
    for _ in range(forward):
        outcome.simulator.step()
    # The command line of RARS prints the low 32 bits of a register, so that is
    # what is compared; a wide result of RV64 is compared through memory.
    return ({number: machine.x.read(number) & 0xFFFFFFFF for number in range(1, 32)},
            [machine.memory.peek(DATA + 4 * index, 4) for index in range(WORDS)])


def theirs(rars, source: str, tmp_path, steps: int,
           xlen: int = 32) -> tuple[dict[int, int], list[int]]:
    """The state RARS stands in when it has carried out `steps` instructions."""
    path = tmp_path / "p.s"
    path.write_text(source)
    options = ((("rv64",) if xlen == 64 else ())
               + (f"{DATA:#x}-{DATA + 4 * WORDS - 4:#x}",) + NAMES)
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


def compiled(source: str, tmp_path, xlen: int = 32):
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions(xlen=xlen))
    assert program.diagnostics == (), program.diagnostics
    return program


def length(source: str, tmp_path, xlen: int = 32) -> int:
    """Instructions of the straight part of a program: everything but its endless
    jump at the end."""
    return len(compiled(source, tmp_path, xlen).text) - 1


END = "end:    j end\n"

PROGRAMS = {
    # name: (source, steps taken back)
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
        lui s2, 0xabcde
""" + END, 5),
    "memory": ("""\
.data
v:      .word 0x89abcdef, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        lw t1, 0(t0)
        li t2, 0x11223344
        sw t2, 4(t0)
        sh t2, 8(t0)
        sb t2, 12(t0)
        lw t3, 4(t0)
        lhu t4, 8(t0)
        li t5, -1
        sw t5, 16(t0)
        sw t5, 20(t0)
""" + END, 6),
    "control flow": ("""\
.data
v:      .word 0, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        li t1, 0
        li t2, 4
loop:   sw t1, 0(t0)
        addi t0, t0, 4
        addi t1, t1, 1
        blt t1, t2, loop
        jal ra, after
        li t3, 0x55
after:  li t4, 0x66
""" + END, 7),
    "floating point": ("""\
.data
v:      .word 0, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        li t1, 0x3fc00000
        fmv.w.x f1, t1
        fadd.s f2, f1, f1
        fmul.s f3, f2, f1
        fdiv.s f4, f1, f3
        fsqrt.s f5, f2
        fsw f2, 0(t0)
        fsw f3, 4(t0)
        fsw f4, 8(t0)
        fsw f5, 12(t0)
        frflags t2
""" + END, 6),
}


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_a_step_back_reaches_the_state_rars_stands_in(name, rars, tmp_path):
    source, back = PROGRAMS[name]
    steps = length(source, tmp_path)
    assert steps > back
    assert ours(source, tmp_path, steps, back=back) == theirs(
        rars, source, tmp_path, steps - back)


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_a_machine_that_went_back_carries_on_the_same(name, rars, tmp_path):
    source, back = PROGRAMS[name]
    steps = length(source, tmp_path)
    assert ours(source, tmp_path, steps, back=back, forward=back) == theirs(
        rars, source, tmp_path, steps)


def test_the_heap_of_sbrk_comes_back(rars, tmp_path):
    """The top of the heap is ours to restore (DEV-51): a step back over `sbrk`
    and forward again hands out the same piece, so the machine ends where RARS
    ends, which never went back at all."""
    source = """\
.text
main:   li a7, 9
        li a0, 16
        ecall
        mv s0, a0
        li a7, 9
        li a0, 32
        ecall
        mv s1, a0
""" + END
    steps = length(source, tmp_path)
    assert ours(source, tmp_path, steps, back=5, forward=5) == theirs(
        rars, source, tmp_path, steps)


@pytest.mark.parametrize("xlen", [32, 64])
def test_a_whole_run_taken_back_and_made_again(xlen, rars, tmp_path):
    """Every step of a program taken back, and then made again: the machine must
    stand where RARS stands, which proves that the journal left nothing behind."""
    source = """\
.data
v:      .word 0, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        li t1, 0x7fff
        sw t1, 0(t0)
        slli t2, t1, 12
        sw t2, 4(t0)
        addi t3, t2, -1
        mul t4, t2, t3
        sw t4, 8(t0)
        csrrs t5, instret, x0
""" + END
    steps = length(source, tmp_path, xlen)
    assert ours(source, tmp_path, steps, back=steps, forward=steps, xlen=xlen) == theirs(
        rars, source, tmp_path, steps, xlen=xlen)
