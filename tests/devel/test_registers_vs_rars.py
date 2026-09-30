"""T-REG, stage 16: the register files and the control registers against RARS.

RARS prints the registers it is asked for at the end of a run, and a program can
print anything else through the syscalls; our side does the same with
`pyrars.core.regs` and `pyrars.core.csr`.

Everything here agrees with RARS. What the counters count per instruction is
compared in stage 22, where a program of ours runs as well.
"""

import pytest

from pyrars.core.csr import ControlRegisters
from pyrars.core.options import Options
from pyrars.core.regs import FloatRegisters, Registers
from pyrars.core.traps import Trap
from pyrars.isa.memory import COMPACT_DATA_AT_ZERO, COMPACT_TEXT_AT_ZERO, DEFAULT
from pyrars.isa.registers import CSRS, X_NAMES
from pyrars.softfloat.formats import BINARY32

pytestmark = pytest.mark.devel

SHOW = """\
.macro show %r
        mv a0, %r
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
.end_macro
"""
EXIT = "        li a7, 93\n        li a0, 0\n        ecall\n"


def values_of(rars, tmp_path, source: str, options: tuple[str, ...] = ()) -> list[int]:
    path = tmp_path / "p.s"
    path.write_text(source)
    done = rars.run([path], options=options)
    assert done.messages == [], done.stdout
    return [int(line, 16) for line in done.stdout.splitlines() if line.startswith("0x")]


def printed_registers(rars, tmp_path, names, options=()) -> dict[str, int]:
    """What RARS prints for the named registers after a program that does nothing."""
    path = tmp_path / "p.s"
    path.write_text(".text\nmain:" + EXIT)
    done = rars.run([path], options=(*options, *names))
    found = {}
    for line in done.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("0x"):
            found[parts[0]] = int(parts[1], 16)
    return found


def message_of(call) -> str:
    try:
        call()
    except Trap as trap:
        return trap.message
    return ""


@pytest.mark.parametrize("config, option", [
    (DEFAULT, ()),
    (COMPACT_DATA_AT_ZERO, ("mc", "CompactDataAtZero")),
    (COMPACT_TEXT_AT_ZERO, ("mc", "CompactTextAtZero")),
])
def test_the_registers_a_program_starts_with(rars, tmp_path, config, option):
    names = ("x1", "x2", "x3", "x4", "x8", "x10", "x31")
    theirs = printed_registers(rars, tmp_path, names, option)
    ours = Registers(Options(config=config))
    assert theirs == {name: ours.read(X_NAMES.index("sp") if name == "x2" else
                                     X_NAMES.index("gp") if name == "x3" else int(name[1:]))
                      for name in names}
    assert theirs["x2"] == config.stack_pointer and theirs["x3"] == config.global_pointer


def test_x0_stays_zero(rars, tmp_path):
    source = SHOW + ".text\nmain:   li x0, 7\n        addi x0, x0, 5\n        show x0\n" + EXIT
    assert values_of(rars, tmp_path, source) == [0]
    ours = Registers()
    ours.write(0, 7)
    assert ours.read(0) == 0


def test_the_boxing_of_a_single_precision_value(rars, tmp_path):
    """A single is written boxed; read as a number it is the canonical NaN unless
    it is boxed, while `fmv.x.w` and `fsw` take the low word as it lies."""
    source = SHOW + """\
.data
scratch: .dword 0
dval:    .dword 0x1122334455667788
.text
main:   la s1, scratch
        li t0, 0x3f800000
        fmv.w.x ft0, t0
        fsd ft0, 0(s1)
        lw t1, 4(s1)
        show t1
        lw t1, 0(s1)
        show t1
        la s2, dval
        fld ft1, 0(s2)
        fmv.x.w t1, ft1
        show t1
        fadd.s ft2, ft1, ft1, rne
        fmv.x.w t1, ft2
        show t1
        fadd.s ft3, ft0, ft0, rne
        fsd ft3, 0(s1)
        lw t1, 4(s1)
        show t1
        lw t1, 0(s1)
        show t1
""" + EXIT
    high, low, moved, added, result_high, result_low = values_of(rars, tmp_path, source)

    f = FloatRegisters()
    f.set_single(0, 0x3F800000)
    assert (f.raw(0) >> 32, f.raw(0) & 0xFFFFFFFF) == (high, low)
    f.set_double(1, 0x1122334455667788)
    assert f.low_word(1) == moved  # fmv.x.w takes the bits as they lie
    assert f.single(1) == BINARY32.canonical_nan and added == BINARY32.canonical_nan
    f.set_single(3, 0x40000000)  # what fadd.s of 1.0 and 1.0 gives
    assert (f.raw(3) >> 32, f.raw(3) & 0xFFFFFFFF) == (result_high, result_low)


def test_the_masks_and_the_windows_of_the_control_registers(rars, tmp_path):
    source = SHOW + """\
.text
main:   li t0, 0xffffffff
        csrrw x0, ustatus, t0
        csrrs t1, ustatus, x0
        show t1
        csrrw x0, fcsr, t0
        csrrs t1, fcsr, x0
        show t1
        csrrs t1, fflags, x0
        show t1
        csrrs t1, frm, x0
        show t1
        csrrw x0, fcsr, x0
        li t2, 0xff
        csrrw x0, fflags, t2
        csrrs t1, fcsr, x0
        show t1
        csrrw x0, fcsr, x0
        li t2, 7
        csrrw x0, frm, t2
        csrrs t1, fcsr, x0
        show t1
        csrrw x0, fcsr, x0
        li t2, 0x20
        csrrw x0, fflags, t2
        csrrs t1, fcsr, x0
        show t1
        csrrw x0, uscratch, t0
        csrrs t1, uscratch, x0
        show t1
""" + EXIT
    theirs = values_of(rars, tmp_path, source)

    c = ControlRegisters()
    ours = []
    c.write(CSRS["ustatus"], 0xFFFFFFFF)
    ours.append(c.read(CSRS["ustatus"]))
    c.write(CSRS["fcsr"], 0xFFFFFFFF)
    ours += [c.read(CSRS["fcsr"]), c.read(CSRS["fflags"]), c.read(CSRS["frm"])]
    c.write(CSRS["fcsr"], 0)
    c.write(CSRS["fflags"], 0xFF)
    ours.append(c.read(CSRS["fcsr"]))
    c.write(CSRS["fcsr"], 0)
    c.write(CSRS["frm"], 7)
    ours.append(c.read(CSRS["fcsr"]))
    c.write(CSRS["fcsr"], 0)
    c.write(CSRS["fflags"], 0x20)
    ours.append(c.read(CSRS["fcsr"]))
    c.write(CSRS["uscratch"], 0xFFFFFFFF)
    ours.append(c.read(CSRS["uscratch"]))
    assert ours == theirs


@pytest.mark.parametrize("body, ours", [
    ("        li t0, 5\n        csrrw x0, cycle, t0\n",
     lambda c: c.write(CSRS["cycle"], 5)),
    ("        li t0, 1\n        csrrs t1, instret, t0\n",
     lambda c: c.write(CSRS["instret"], 1)),
    ("        csrrsi t1, cycleh, 1\n", lambda c: c.write(CSRS["cycleh"], 1)),
    ("        csrrs t1, 0x123, x0\n", lambda c: c.read(0x123)),
])
def test_the_messages_of_a_refused_register(rars, tmp_path, body, ours):
    path = tmp_path / "p.s"
    path.write_text(".text\nmain:\n" + body + EXIT)
    done = rars.run([path])
    theirs = ""
    for line in done.stdout.splitlines():
        if "Runtime exception at " in line:
            theirs = line.split(": ", 2)[-1]
    assert theirs, done.stdout
    assert message_of(lambda: ours(ControlRegisters())) == theirs


def test_reading_a_counter_without_writing_it_is_allowed(rars, tmp_path):
    """`csrrs` with x0 and `csrrsi` with 0 write nothing, so they pass."""
    source = SHOW + ".text\nmain:   csrrs t1, cycle, x0\n        csrrsi t2, instret, 0\n" + EXIT
    assert values_of(rars, tmp_path, source) == []
    c = ControlRegisters()
    assert c.read(CSRS["cycle"]) == 0 and c.read(CSRS["instret"]) == 0


def test_the_counters_and_the_clock_of_a_64_bit_machine(rars, tmp_path):
    """In RV64 a counter is read whole; `instreth` and `timeh` still read the
    upper half."""
    source = SHOW + """\
.text
main:   csrrs t1, cycleh, x0
        show t1
        csrrs t1, instret, x0
        srli t2, t1, 32
        show t2
""" + EXIT
    assert values_of(rars, tmp_path, source, options=("rv64",)) == [0, 0]

    c = ControlRegisters(Options(xlen=64), clock=lambda: 0x1A0BEEFCAFE)
    assert c.read(CSRS["cycleh"]) == 0
    c.poke("instret", 7)
    assert c.read(CSRS["instret"]) == 7 and c.read(CSRS["instreth"]) == 0
    assert c.read(CSRS["time"]) == 0x1A0BEEFCAFE and c.read(CSRS["timeh"]) == 0x1A0
