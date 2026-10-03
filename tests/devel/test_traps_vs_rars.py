"""T-TRAP, stage 19: the traps and the interrupts against RARS.

A program installs a handler, provokes something, and keeps what the handler saw
in registers; RARS prints them at the end of the run and our machine is driven
through the same program by the loop of `driver.py`. Where a program is meant to
stop instead, the message is compared.

The programs print nothing, because the syscalls are stage 20: our driver ends a
run at the call of the environment, which is where RARS exits.
"""

import subprocess

import pytest

import driver
from pyrars.asm.assembler import Options as AsmOptions
from pyrars.asm.assembler import assemble
from pyrars.core.options import Options
from pyrars.core.traps import NO_HANDLER

pytestmark = pytest.mark.devel

EXIT = "        li a7, 93\n        li a0, 0\n        ecall\n"

# Every program installs this handler, which keeps what it saw in s1..s4 and
# steps over the instruction that faulted.
HANDLER = """\
handler:
        csrrs s1, ucause, x0
        csrrs s2, uepc, x0
        csrrs s3, utval, x0
        csrrs s4, ustatus, x0
        addi s5, s2, 4
        csrrw x0, uepc, s5
        uret
"""

PROGRAMS = {
    "a misaligned load": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        lw t1, 1(x0)
        li s6, 111
""",
    "a misaligned store": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        li t2, 0x10010002
        sw t2, 0(t2)
        li s6, 222
""",
    "an address out of range": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        li t2, 0x90000000
        lw t1, 0(t2)
        li s6, 333
""",
    "a write into the text segment": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        li t2, 0x00400000
        sw x0, 0(t2)
        li s6, 444
""",
    "two traps one after the other": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        lw t1, 1(x0)
        lw t1, 2(x0)
        li s6, 555
""",
    "a software interrupt": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, uie, 1
        csrrsi x0, ustatus, 1
        csrrsi x0, uip, 1
        csrrci x0, uip, 1
        li s6, 666
""",
    "the handler reads and writes": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        li t3, 7
        lw t1, 1(x0)
        addi t3, t3, 1
        li s6, 777
""",
    "a breakpoint is passed over": """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        li t3, 1
        ebreak
        li t4, 2
        li s6, 888
""",
}

STOPPING = {
    "a trap with no handler": (
        """\
.text
main:   lw t1, 1(x0)
        li s6, 111
""", "Load address not aligned to word boundary 0x00000001"),
    "a trap while interrupts are not allowed": (
        """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        lw t1, 1(x0)
        li s6, 111
""", "Load address not aligned to word boundary 0x00000001"),
    "a second trap inside the handler": (
        """\
.text
main:   la t0, bad
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        lw t1, 1(x0)
        li s6, 111
bad:    lw t2, 3(x0)
""", "Load address not aligned to word boundary 0x00000003"),
    "an interrupt with no handler": (
        """\
.text
main:   csrrsi x0, uie, 1
        csrrsi x0, ustatus, 1
        csrrsi x0, uip, 1
        nop
""", NO_HANDLER),
}


def ours(source: str, tmp_path) -> driver.Outcome:
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions())
    assert program.diagnostics == (), program.diagnostics
    return driver.run(program, Options())


def theirs(rars, tmp_path) -> tuple[dict[int, int], str]:
    """The registers RARS prints, and the runtime message if it stopped on one."""
    names = tuple(f"x{number}" for number in range(1, 32))
    done = rars.run([tmp_path / "p.s"], options=names)
    registers, message = {}, ""
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("x"):
            registers[int(parts[0][1:])] = int(parts[1], 16)
        elif "Runtime exception at " in line:
            message = line.split(": ", 2)[-1]
        elif "Interrupt handler was not supplied" in line:
            message = line.split(": ", 1)[-1]
    return registers, message


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_a_program_that_takes_a_trap(rars, tmp_path, name):
    outcome = ours(PROGRAMS[name] + EXIT + HANDLER, tmp_path)
    assert outcome.reason == "exit", outcome.reason
    their_registers, message = theirs(rars, tmp_path)
    assert message == ""
    assert outcome.registers == their_registers


@pytest.mark.parametrize("name", list(STOPPING))
def test_a_program_that_cannot_go_on(rars, tmp_path, name):
    source, expected = STOPPING[name]
    outcome = ours(source + EXIT + HANDLER, tmp_path)
    assert outcome.reason == expected
    _, message = theirs(rars, tmp_path)
    assert message == expected


def test_the_vectored_mode_of_an_interrupt(rars, tmp_path):
    """With the mode bits set, each cause has its own place: the software
    interrupt is cause 0, so it lands at the base itself, and the timer at the
    base plus sixteen. Only the first can be asked for from a program."""
    source = """\
.text
main:   la t0, table
        ori t0, t0, 2
        csrrw x0, utvec, t0
        csrrsi x0, uie, 1
        csrrsi x0, ustatus, 1
        csrrsi x0, uip, 1
        csrrci x0, uip, 1
        li s6, 999
""" + EXIT + """\
table:  li s1, 1
        csrrci x0, uip, 1
        uret
        nop
"""
    outcome = ours(source, tmp_path)
    assert outcome.reason == "exit"
    their_registers, message = theirs(rars, tmp_path)
    assert message == "" and outcome.registers == their_registers
    assert outcome.registers[9] == 1  # s1: the handler at the base did run


def test_a_faulting_instruction_is_not_counted(rars, tmp_path):
    """Verified in RARS: the instruction that faults does not reach `instret`."""
    source = """\
.text
main:   la t0, handler
        csrrw x0, utvec, t0
        csrrsi x0, ustatus, 1
        csrrs s7, instret, x0
        lw t1, 1(x0)
        csrrs s8, instret, x0
        sub s9, s8, s7
""" + EXIT + HANDLER
    outcome = ours(source, tmp_path)
    their_registers, _ = theirs(rars, tmp_path)
    assert outcome.registers == their_registers
    # s9: the four reads, the addi, the csrrw and the uret of the handler, and
    # the csrrs that follows the fault; the faulting load is not among them
    assert outcome.registers[25] == 8


def test_a_program_that_waits_for_an_interrupt_that_cannot_come(rars, tmp_path):
    """DEV-46: RARS blocks its thread for ever here; our machine stops and says
    what it is waiting for, so that a session can carry it on later."""
    source = ".text\nmain:   li t0, 1\n        wfi\n        li t1, 2\n" + EXIT
    outcome = ours(source, tmp_path)
    assert outcome.reason == "waiting"
    assert outcome.registers[5] == 1 and outcome.registers[6] == 0  # it stopped at wfi

    # RARS waits for an event that no device can send here, and keeps waiting
    with pytest.raises(subprocess.TimeoutExpired):
        rars.run([tmp_path / "p.s"], max_steps=1000, timeout=5)
