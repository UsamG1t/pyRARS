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


def ours(source: str, tmp_path, xlen: int,
         words: int = WORDS) -> tuple[dict[int, int], list[int]]:
    """The registers and the first words of the data segment our machine leaves
    behind."""
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
            [machine.memory.peek(DATA + 4 * index, 4) for index in range(words)])


def theirs(rars, tmp_path, xlen: int,
           words: int = WORDS) -> tuple[dict[int, int], list[int]]:
    path = tmp_path / "p.s"
    names = tuple(f"x{number}" for number in range(1, 32))
    options = ((("rv64",) if xlen == 64 else ())
               + (f"{DATA:#x}-{DATA + 4 * words - 4:#x}",) + names)
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


# ------------------------------------------- stage 18: the floating point part

# The programs keep their results in memory, because the command line of RARS
# prints only 32 bits of a register, and they read fflags into an integer
# register, so that the flags of every operation are compared as well.
FLOAT_PROGRAMS = {
    "single arithmetic": """\
.data
out:    .space 64
one:    .float 1.0
three:  .float 3.0
big:    .float 3.4e38
tiny:   .float 1e-44
.text
main:   la s1, out
        la t0, one
        flw ft0, 0(t0)
        la t0, three
        flw ft1, 0(t0)
        fadd.s ft2, ft0, ft1, rne
        fsw ft2, 0(s1)
        fsub.s ft2, ft0, ft1, rne
        fsw ft2, 4(s1)
        fmul.s ft2, ft1, ft1, rne
        fsw ft2, 8(s1)
        fdiv.s ft2, ft0, ft1, rne
        fsw ft2, 12(s1)
        fsqrt.s ft2, ft1, rne
        fsw ft2, 16(s1)
        csrrs t2, fflags, x0
        la t0, big
        flw ft3, 0(t0)
        fmul.s ft2, ft3, ft3, rne
        fsw ft2, 20(s1)
        la t0, tiny
        flw ft4, 0(t0)
        fmul.s ft2, ft4, ft4, rne
        fsw ft2, 24(s1)
        csrrs t3, fflags, x0
""",
    "rounding modes": """\
.data
out:    .space 64
one:    .float 1.0
three:  .float 3.0
.text
main:   la s1, out
        la t0, one
        flw ft0, 0(t0)
        la t0, three
        flw ft1, 0(t0)
        fdiv.s ft2, ft0, ft1, rne
        fsw ft2, 0(s1)
        fdiv.s ft2, ft0, ft1, rtz
        fsw ft2, 4(s1)
        fdiv.s ft2, ft0, ft1, rdn
        fsw ft2, 8(s1)
        fdiv.s ft2, ft0, ft1, rup
        fsw ft2, 12(s1)
        fdiv.s ft2, ft0, ft1, rmm
        fsw ft2, 16(s1)
        csrrwi x0, frm, 1
        fdiv.s ft2, ft0, ft1, dyn
        fsw ft2, 20(s1)
        csrrwi x0, frm, 3
        fdiv.s ft2, ft0, ft1, dyn
        fsw ft2, 24(s1)
        csrrs t2, fcsr, x0
""",
    "double arithmetic and the fused ones": """\
.data
out:    .space 64
done:   .double 1.0
dthree: .double 3.0
.text
main:   la s1, out
        la t0, done
        fld ft0, 0(t0)
        la t0, dthree
        fld ft1, 0(t0)
        fdiv.d ft2, ft0, ft1, rne
        fsd ft2, 0(s1)
        fsqrt.d ft2, ft1, rne
        fsd ft2, 8(s1)
        fmadd.d ft2, ft1, ft1, ft0, rne
        fsd ft2, 16(s1)
        fnmsub.d ft2, ft1, ft1, ft0, rne
        fsd ft2, 24(s1)
        csrrs t2, fflags, x0
""",
    "comparisons and classes": """\
.data
out:    .space 32
one:    .float 1.0
three:  .float 3.0
nan:    .word 0x7fc00000
snan:   .word 0x7f800001
nzero:  .word 0x80000000
.text
main:   la t0, one
        flw ft0, 0(t0)
        la t0, three
        flw ft1, 0(t0)
        la t0, nan
        flw ft2, 0(t0)
        la t0, snan
        flw ft3, 0(t0)
        la t0, nzero
        flw ft4, 0(t0)
        feq.s t0, ft0, ft0
        flt.s t1, ft0, ft1
        fle.s t2, ft1, ft0
        feq.s t3, ft2, ft0
        csrrs s2, fflags, x0
        flt.s t4, ft2, ft0
        csrrs s3, fflags, x0
        feq.s t5, ft3, ft0
        csrrs s4, fflags, x0
        fclass.s t6, ft0
        fclass.s s5, ft4
        fclass.s s6, ft2
        fclass.s s7, ft3
        la s1, out
        fmin.s ft5, ft0, ft1
        fsw ft5, 0(s1)
        fmax.s ft5, ft4, ft0
        fsw ft5, 4(s1)
        fmin.s ft5, ft2, ft1
        fsw ft5, 8(s1)
        fsgnj.s ft5, ft0, ft4
        fsw ft5, 12(s1)
        fsgnjn.s ft5, ft0, ft4
        fsw ft5, 16(s1)
        fsgnjx.s ft5, ft0, ft4
        fsw ft5, 20(s1)
""",
    "conversions": """\
.data
out:    .space 64
pi:     .float 3.14159265
npi:    .float -3.14159265
big:    .float 3e9
dpi:    .double 3.14159265358979
.text
main:   la s1, out
        la t0, pi
        flw ft0, 0(t0)
        la t0, npi
        flw ft1, 0(t0)
        la t0, big
        flw ft2, 0(t0)
        fcvt.w.s t3, ft0, rtz
        fcvt.w.s t4, ft1, rtz
        fcvt.w.s t5, ft2, rtz
        fcvt.wu.s t6, ft1, rtz
        csrrs s2, fflags, x0
        fcvt.w.s s3, ft0, rne
        fcvt.w.s s4, ft0, rup
        li s5, -7
        fcvt.s.w ft3, s5, rne
        fsw ft3, 0(s1)
        fcvt.s.wu ft3, s5, rne
        fsw ft3, 4(s1)
        fcvt.d.s ft4, ft0, rne
        fsd ft4, 8(s1)
        la t0, dpi
        fld ft5, 0(t0)
        fcvt.s.d ft6, ft5, rne
        fsw ft6, 16(s1)
        fcvt.w.d s6, ft5, rtz
        fcvt.d.w ft7, s5, rne
        fsd ft7, 24(s1)
        csrrs s7, fflags, x0
""",
    "moves and boxing": """\
.data
out:    .space 32
dval:   .dword 0x1122334455667788
one:    .float 1.0
.text
main:   la s1, out
        la t0, dval
        fld ft0, 0(t0)
        la t0, one
        flw ft1, 0(t0)
        fmv.x.w t1, ft0
        fmv.x.w t2, ft1
        li t3, 0xc0000000
        fmv.w.x ft2, t3
        fsw ft2, 0(s1)
        fsd ft2, 8(s1)
        fadd.s ft3, ft0, ft1, rne
        fsw ft3, 16(s1)
        csrrs t4, fflags, x0
        fsw ft0, 20(s1)
""",
}

WIDE_FLOAT_PROGRAMS = {
    "the wide conversions": """\
.data
out:    .space 64
big:    .float 4.6e18
npi:    .float -3.14159265
.text
main:   la s1, out
        la t0, big
        flw ft0, 0(t0)
        la t0, npi
        flw ft1, 0(t0)
        fcvt.l.s t2, ft0, rtz
        sd t2, 0(s1)
        fcvt.lu.s t3, ft0, rtz
        sd t3, 8(s1)
        fcvt.l.s t4, ft1, rtz
        sd t4, 16(s1)
        fcvt.wu.s t5, ft0, rtz
        sd t5, 24(s1)
        csrrs s2, fflags, x0
        li t6, -3
        fcvt.s.l ft2, t6, rne
        fsw ft2, 32(s1)
        fcvt.s.lu ft3, t6, rne
        fsw ft3, 36(s1)
        fcvt.d.l ft4, t6, rne
        fsd ft4, 40(s1)
        fmv.x.d s3, ft0
        sd s3, 48(s1)
        fmv.d.x ft5, s3
        fsd ft5, 56(s1)
""",
}


@pytest.mark.parametrize("name", list(FLOAT_PROGRAMS))
def test_a_program_of_floating_point_instructions(rars, tmp_path, name):
    source = FLOAT_PROGRAMS[name] + EXIT
    assert ours(source, tmp_path, 32, words=16) == theirs(rars, tmp_path, 32, words=16)


@pytest.mark.parametrize("name", list(WIDE_FLOAT_PROGRAMS))
def test_a_floating_point_program_of_a_64_bit_machine(rars, tmp_path, name):
    source = WIDE_FLOAT_PROGRAMS[name] + EXIT
    our_registers, our_words = ours(source, tmp_path, 64, words=16)
    their_registers, their_words = theirs(rars, tmp_path, 64, words=16)
    assert {number: value & 0xFFFFFFFF for number, value in our_registers.items()} \
        == their_registers
    assert our_words == their_words


def test_a_nan_operand_of_an_operation(rars, tmp_path):  # DEV-32, DEV-33
    """The one place where the machines part over floating point: RARS hands a
    NaN operand back as it is and raises no flag, while we give the canonical NaN
    and raise the invalid flag for a signalling one. The flags travel through the
    machine the same way in both cases, which is what this test is for."""
    source = """\
.data
out:    .space 16
qnan:   .word 0x7fc00001
snan:   .word 0x7f800001
one:    .float 1.0
.text
main:   la s1, out
        la t0, qnan
        flw ft0, 0(t0)
        la t0, snan
        flw ft1, 0(t0)
        la t0, one
        flw ft2, 0(t0)
        fadd.s ft3, ft0, ft2, rne
        fsw ft3, 0(s1)
        csrrs t3, fflags, x0
        csrrw x0, fflags, x0
        fadd.s ft4, ft1, ft2, rne
        fsw ft4, 4(s1)
        csrrs t4, fflags, x0
""" + EXIT
    our_registers, our_words = ours(source, tmp_path, 32, words=4)
    their_registers, their_words = theirs(rars, tmp_path, 32, words=4)

    assert our_words[:2] == [0x7FC00000, 0x7FC00000]  # the canonical NaN twice
    assert their_words[:2] == [0x7FC00001, 0x7F800001]  # the operands themselves
    assert (our_registers[28], our_registers[29]) == (0, 0x10)  # nothing, then invalid
    assert (their_registers[28], their_registers[29]) == (0, 0)
