"""T-EXEC, stage 17: the integer instructions against RARS.

A program runs in RARS and in our machine, and every register it leaves behind is
compared; where it stores something, the words of the data segment are compared as
well (RARS prints both at the end of a run when it is asked for them).

Our machine has no syscalls before stage 20, so a program ends where RARS calls
the one that exits: the registers hold the same values at that point.

Everything here agrees with RARS. The programs are ours, and they end with the
exit of RARS so that nothing is printed and nothing depends on the order of the
output.
"""

import pytest

from pyrars.asm.assembler import Options as AsmOptions
from pyrars.asm.assembler import assemble
from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.traps import ENVIRONMENT_CALL, Trap
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

DATA = DEFAULT.data_base
WORDS = 8  # words of the data segment that are compared
EXIT = "        li a7, 93\n        li a0, 0\n        ecall\n"
STEPS = 100_000


def ours(source: str, tmp_path, xlen: int) -> tuple[dict[int, int], list[int]]:
    """The registers and the first eight words of the data segment our machine
    leaves behind."""
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions(xlen=xlen))
    assert program.diagnostics == (), program.diagnostics

    machine = Machine(Options(xlen=xlen))
    machine.load(program)
    for _ in range(STEPS):
        fetched = machine.fetch()
        if fetched is None:
            break
        try:
            execute(machine, fetched)
        except Trap as trap:
            assert trap.cause == ENVIRONMENT_CALL, trap.message
            break  # the exit at the end of the program
        machine.csr.retire()
    else:
        raise AssertionError("the program does not end")
    return ({number: machine.x.read(number) for number in range(1, 32)},
            [machine.memory.peek(DATA + 4 * index, 4) for index in range(WORDS)])


def theirs(rars, tmp_path, xlen: int) -> tuple[dict[int, int], list[int]]:
    path = tmp_path / "p.s"
    names = tuple(f"x{number}" for number in range(1, 32))
    options = ((("rv64",) if xlen == 64 else ())
               + (f"{DATA:#x}-{DATA + 4 * WORDS - 4:#x}",) + names)
    done = rars.run([path], options=options)
    assert done.messages == [], done.stdout

    registers, words = {}, []
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].startswith("x"):
            registers[int(parts[0][1:])] = int(parts[1], 16)
        elif parts and parts[0].startswith("Mem["):
            words += [int(value, 16) for value in parts[1:]]  # four words to a line
    return registers, words


PROGRAMS = {
    "arithmetic": """\
.text
main:   li t0, 0x7fffffff
        li t1, -1
        add t2, t0, t1
        sub t3, t0, t1
        and t4, t0, t1
        or t5, t0, t1
        xor t6, t0, t1
        slt s0, t1, t0
        sltu s1, t1, t0
        addi s2, t0, 1
        addi s3, t1, -2048
        andi s4, t0, -1
        ori s5, x0, -2048
        xori s6, t1, 255
        slti s7, t1, 0
        sltiu s8, t1, -1
        lui s9, 0xfedcb
        auipc s10, 0x10
""",
    "shifts": """\
.text
main:   li t0, 0x80000001
        li t1, 31
        sll t2, t0, t1
        srl t3, t0, t1
        sra t4, t0, t1
        li t1, 33
        sll t5, t0, t1
        srl t6, t0, t1
        slli s0, t0, 1
        srli s1, t0, 1
        srai s2, t0, 1
        srai s3, t0, 31
        slli s4, t0, 0
""",
    "multiply and divide": """\
.text
main:   li t0, -5
        li t1, 2
        mul t2, t0, t1
        mulh t3, t0, t1
        mulhu t4, t0, t1
        mulhsu t5, t0, t1
        div t6, t0, t1
        rem s0, t0, t1
        divu s1, t0, t1
        remu s2, t0, t1
        div s3, t0, x0
        rem s4, t0, x0
        divu s5, t0, x0
        remu s6, t0, x0
        li t2, -2147483648
        li t3, -1
        div s7, t2, t3
        rem s8, t2, t3
        mul s9, t2, t2
        mulh s10, t2, t2
""",
    "memory": """\
.data
v:      .word 0x89abcdef, 0, 0, 0, 0, 0, 0, 0
.text
main:   la t0, v
        lw t1, 0(t0)
        lb t2, 0(t0)
        lbu t3, 0(t0)
        lh t4, 0(t0)
        lhu t5, 2(t0)
        lb t6, 3(t0)
        sw t1, 4(t0)
        sh t1, 8(t0)
        sb t1, 12(t0)
        li s0, -1
        sw s0, 16(t0)
        sh s0, 20(t0)
        sb s0, 24(t0)
        lw s1, 16(t0)
        lw s2, 20(t0)
""",
    "control flow": """\
.text
main:   li t0, 0
        li t1, 10
loop:   beq t1, x0, done
        add t0, t0, t1
        addi t1, t1, -1
        j loop
done:   li t2, 1
        blt t0, x0, skip
        li t3, 2
skip:   bge t0, x0, next
        li t4, 3
next:   jal ra, sub1
        li t6, 5
        j after
sub1:   li t5, 4
        ret
after:  li s0, 6
""",
    "control registers": """\
.text
main:   li t0, 0xff
        csrrw t1, uscratch, t0
        csrrs t2, uscratch, x0
        csrrc t3, uscratch, t0
        csrrs t4, uscratch, x0
        csrrwi t5, fcsr, 31
        csrrs t6, fcsr, x0
        csrrsi s0, fcsr, 8
        csrrci s1, fcsr, 1
        csrrs s2, fcsr, x0
        csrrw s3, ustatus, t0
        csrrs s4, ustatus, x0
""",
}

WIDE_PROGRAMS = {
    "32-bit forms": """\
.data
out:    .dword 0, 0, 0, 0, 0, 0, 0, 0
.text
main:   li t0, 0x7fffffff
        li t1, 1
        addw t2, t0, t1
        subw t3, x0, t1
        sllw t4, t1, t0
        addiw t5, t0, 1
        slliw t6, t1, 31
        li s0, -1
        srlw s1, s0, t1
        sraw s2, s0, t1
        srliw s3, s0, 1
        sraiw s4, s0, 1
        mulw s5, t0, t0
        divw s6, t0, x0
        remw s7, t0, t1
        divuw s8, s0, t1
        la a0, out
        sd t2, 0(a0)
        sd t4, 8(a0)
        sd s2, 16(a0)
        sd s5, 24(a0)
""",
    "wide values": """\
.data
v:      .dword 0x1122334455667788, 0, 0, 0
.text
main:   la t0, v
        ld t1, 0(t0)
        lw t2, 0(t0)
        lwu t3, 0(t0)
        sd t1, 8(t0)
        li t4, 1
        slli t5, t4, 63
        srai t6, t5, 63
        li s0, -1
        srli s1, s0, 1
        add s2, s0, t4
        mulh s3, s0, s0
        sd t1, 16(t0)
        sd t6, 24(t0)
""",
}


@pytest.mark.parametrize("name", list(PROGRAMS))
def test_a_program_of_32_bit_instructions(rars, tmp_path, name):
    source = PROGRAMS[name] + EXIT
    assert ours(source, tmp_path, 32) == theirs(rars, tmp_path, 32)


@pytest.mark.parametrize("name", list(WIDE_PROGRAMS))
def test_a_program_of_a_64_bit_machine(rars, tmp_path, name):
    """The command line of RARS prints the low 32 bits of a register, so the
    programs keep their wide results in memory, where both halves are compared."""
    source = WIDE_PROGRAMS[name] + EXIT
    our_registers, our_words = ours(source, tmp_path, 64)
    their_registers, their_words = theirs(rars, tmp_path, 64)
    assert {number: value & 0xFFFFFFFF for number, value in our_registers.items()} \
        == their_registers
    assert our_words == their_words


def test_the_instructions_are_counted_as_rars_counts_them(rars, tmp_path):
    """`instret` grows by one per instruction, the ecall of the exit included."""
    source = """\
.text
main:   li t0, 0
        li t1, 5
loop:   beq t1, x0, done
        addi t0, t0, 1
        addi t1, t1, -1
        j loop
done:   csrrs t2, instret, x0
""" + EXIT
    path = tmp_path / "p.s"
    path.write_text(source)
    done = rars.run([path], options=("x7",))
    theirs_count = int([line.split()[1] for line in done.stdout.splitlines()
                        if line.startswith("x7")][0], 16)
    registers, _ = ours(source, tmp_path, 32)
    assert registers[7] == theirs_count
