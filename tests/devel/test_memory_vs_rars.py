"""T-MEM, stage 15: the memory of the machine against RARS.

RARS runs a program that touches memory and prints what it read; our side does
the same with `pyrars.core.memory` and compares. A program that provokes a fault
stops, so those cases run one at a time and the message texts are compared.

What differs on purpose, each stated on both sides here:
 - DEV-43: RARS reaches only four windows of 4 MiB (the sizes of its tables),
   while we follow the limits its own configuration declares;
 - DEV-44: RARS checks a load of eight bytes against four and a store of eight
   bytes not at all, while we require the natural alignment of every width;
 - DEV-45: its four messages about alignment read four different ways, ours read
   the same way.
"""

import pytest

from pyrars.core.memory import Memory
from pyrars.core.traps import Trap
from pyrars.core.options import Options
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

DATA = DEFAULT.data_base
TEXT = DEFAULT.text_base

HEAD = """\
.data
val:    .dword 0x1122334455667788, 0x99aabbccddeeff00
.text
main:
"""

TAIL = """\
        li a7, 93
        li a0, 0
        ecall
print:  mv s11, ra
        li a7, 34
        ecall
        li a0, 10
        li a7, 11
        ecall
        jalr x0, 0(s11)
"""


def outcome(rars, tmp_path, body: str, options: tuple[str, ...] = ()) -> tuple[list[int], str]:
    """Run a program; returns the values it printed and the text of the runtime
    message, if it stopped on one."""
    path = tmp_path / "p.s"
    path.write_text(HEAD + body + TAIL)
    done = rars.run([path], options=options)
    values = [int(line, 16) for line in done.stdout.splitlines() if line.startswith("0x")]
    message = ""
    for line in done.stdout.splitlines():
        marker = "Runtime exception at "
        if marker in line:
            message = line.split(": ", 2)[-1]
    return values, message


def fault_of(call) -> str:
    """The message of the fault a call raises, or "" when it raises none."""
    try:
        call()
    except Trap as fault:
        return fault.message
    return ""


def memory(**options) -> Memory:
    return Memory(Options(**options))


# ------------------------------------------------------------------- agreement


def test_values_of_every_width(rars, tmp_path):
    body = """\
        la t1, val
        lw a0, 0(t1)
        jal print
        lhu a0, 0(t1)
        jal print
        lbu a0, 1(t1)
        jal print
        lw a0, 4(t1)
        jal print
        li t2, 0x0000dead
        sh t2, 2(t1)
        lw a0, 0(t1)
        jal print
        sb t2, 0(t1)
        lw a0, 0(t1)
        jal print
"""
    values, message = outcome(rars, tmp_path, body)
    assert message == ""

    m = memory()
    m.write_bytes(DATA, (0x1122334455667788).to_bytes(8, "little"))
    ours = [m.read(DATA, 4), m.read(DATA, 2), m.read(DATA + 1, 1), m.read(DATA + 4, 4)]
    m.write(DATA + 2, 2, 0xDEAD)
    ours.append(m.read(DATA, 4))
    m.write(DATA, 1, 0xAD)
    ours.append(m.read(DATA, 4))
    assert values == ours


def test_memory_that_was_never_written_and_the_far_areas(rars, tmp_path):
    body = """\
        li t1, 0x10010040
        lw a0, 0(t1)
        jal print
        li t1, 0xffff0004
        li t2, 7
        sw t2, 0(t1)
        lw a0, 0(t1)
        jal print
        li t1, 0x7ffffffc
        li t2, 9
        sw t2, 0(t1)
        lw a0, 0(t1)
        jal print
        li t1, 0x10000000
        li t2, 5
        sw t2, 0(t1)
        lw a0, 0(t1)
        jal print
"""
    values, message = outcome(rars, tmp_path, body)
    assert (values, message) == ([0, 7, 9, 5], "")

    m = memory()
    ours = [m.read(DATA + 0x40, 4)]
    for address, value in ((0xFFFF0004, 7), (0x7FFFFFFC, 9), (0x10000000, 5)):
        m.write(address, 4, value)
        ours.append(m.read(address, 4))
    assert ours == values


@pytest.mark.parametrize("body, action, theirs, mine", [
    ("        li t1, 0x00400000\n        lw a0, 0(t1)\n",
     lambda m: m.read(TEXT, 4),
     "Cannot read directly from text segment!0x00400000",
     "Cannot read directly from text segment 0x00400000"),
    ("        li t1, 0x00400000\n        sw x0, 0(t1)\n",
     lambda m: m.write(TEXT, 4, 0),
     "Cannot write directly to text segment!0x00400000",
     "Cannot write directly to text segment 0x00400000"),
    ("        li t1, 0x90000000\n        lw a0, 0(t1)\n",
     lambda m: m.read(0x90000000, 4),
     "address out of range 0x90000000",
     "Address out of range 0x90000000"),
    ("        lw a0, 1(x0)\n", lambda m: m.read(1, 4),
     "Load address not aligned to word boundary 0x00000001",
     "Load address not aligned to word boundary 0x00000001"),
])
def test_the_messages_of_a_refused_access(rars, tmp_path, body, action, theirs, mine):
    """The words of RARS, in the one shape every message of the machine has: a
    capital letter, no glue before the address (DEV-54). Both machines refuse the
    same accesses, which is what matters; the texts are stated on both sides."""
    values, message = outcome(rars, tmp_path, body)
    assert message == theirs
    assert fault_of(lambda: action(memory())) == mine


def test_self_modifying_code(rars, tmp_path):
    body = """\
        li t1, 0x00400000
        lw a0, 0(t1)
        jal print
        li t2, 0x00100513
        sw t2, 0(t1)
        lw a0, 0(t1)
        jal print
"""
    values, message = outcome(rars, tmp_path, body, options=("smc",))
    assert message == "" and values[1] == 0x00100513

    m = memory(self_modifying=True)
    m.poke(TEXT, 4, values[0])  # the same first word the program read
    assert m.read(TEXT, 4) == values[0]
    m.write(TEXT, 4, 0x00100513)
    assert m.read(TEXT, 4) == values[1]
    assert m.fetch(TEXT).instr.instr.mnemonic == "addi"


# ------------------------------------------------------------------ deviations


@pytest.mark.parametrize("address", [0x10400000, 0x50000000, 0x7FBFFFFC])
def test_rars_reaches_less_than_its_configuration_says(rars, tmp_path, address):  # DEV-43
    """These addresses lie inside the data segment of the configuration, but
    outside the 4 MiB tables RARS keeps, so RARS refuses them and we do not."""
    body = f"        li t1, {address:#010x}\n        li t2, 3\n        sw t2, 0(t1)\n"
    _, message = outcome(rars, tmp_path, body)
    assert message == f"address out of range 0x{address:08x}"  # DEV-54: ours is capital

    m = memory()
    m.write(address, 4, 3)
    assert m.read(address, 4) == 3


def test_rars_reaches_less_of_the_text_segment_too(rars, tmp_path):  # DEV-43
    """0x00800000 is text by the configuration; RARS calls it out of range and we
    refuse it as text."""
    body = "        li t1, 0x00800000\n        lw a0, 0(t1)\n"
    _, message = outcome(rars, tmp_path, body)
    assert message == "address out of range 0x00800000"
    assert fault_of(lambda: memory().read(0x00800000, 4)) == (
        "Cannot read directly from text segment 0x00800000")


def test_rars_lets_an_eight_byte_access_lie_askew(rars, tmp_path):  # DEV-44
    """A load of eight bytes is checked against four in RARS, a store not at
    all: it really writes eight bytes across the word boundary."""
    body = """\
        la t1, val
        ld a0, 4(t1)
        jal print
        li t2, 0x1111111122222222
        sd t2, 2(t1)
        lw a0, 0(t1)
        jal print
        lw a0, 4(t1)
        jal print
"""
    values, message = outcome(rars, tmp_path, body, options=("rv64",))
    assert message == "" and values[1:] == [0x22227788, 0x11112222]

    m = memory(xlen=64)
    m.write_bytes(DATA, (0x1122334455667788).to_bytes(8, "little"))
    assert fault_of(lambda: m.read(DATA + 4, 8)) == (
        f"Load address not aligned to doubleword boundary 0x{DATA + 4:08x}")
    assert fault_of(lambda: m.write(DATA + 2, 8, 0x1111111122222222)) == (
        f"Store address not aligned to doubleword boundary 0x{DATA + 2:08x}")


@pytest.mark.parametrize("body, theirs, ours", [
    ("        la t1, val\n        lh a0, 1(t1)\n",
     "Load address not aligned on halfword boundary 0x10010001",
     "Load address not aligned to halfword boundary 0x10010001"),
    ("        la t1, val\n        sh x0, 1(t1)\n",
     "store address not aligned on halfword boundary 0x10010001",
     "Store address not aligned to halfword boundary 0x10010001"),
])
def test_the_wording_of_the_alignment_messages(rars, tmp_path, body, theirs, ours):  # DEV-45
    """RARS says "on halfword boundary" but "to word boundary", and writes
    "store" in lower case where every other message has a capital."""
    _, message = outcome(rars, tmp_path, body)
    assert message == theirs
    m = memory()
    call = ((lambda: m.read(DATA + 1, 2)) if theirs.startswith("Load")
            else (lambda: m.write(DATA + 1, 2, 0)))
    assert fault_of(call) == ours


def test_the_message_of_a_misaligned_jump(rars, tmp_path):  # DEV-45
    path = tmp_path / "p.s"
    path.write_text(HEAD + "        li t1, 0x00400003\n        jalr x0, 0(t1)\n" + TAIL)
    done = rars.run([path])
    assert "Instruction load alignment error" in done.stdout
    assert fault_of(lambda: memory().fetch(TEXT + 3)) == (
        f"Instruction address not aligned to word boundary 0x{TEXT + 3:08x}")


def test_the_message_of_a_jump_outside_the_text(rars, tmp_path):
    """RARS says `Instruction load access error` and keeps the address to itself,
    though it is the one thing a reader needs; ours names it (DEV-54)."""
    path = tmp_path / "p.s"
    path.write_text(HEAD + "        la t1, val\n        jalr x0, 0(t1)\n" + TAIL)
    done = rars.run([path])
    assert "Instruction load access error" in done.stdout
    assert fault_of(lambda: memory().fetch(DATA)) == (
        f"Cannot fetch an instruction from 0x{DATA:08x}")


def test_a_program_that_runs_off_its_text(rars, tmp_path):
    """RARS stops with a message of its own; our memory says there is no
    instruction there and the simulator will stop on that (stage 22)."""
    path = tmp_path / "p.s"
    path.write_text(".text\nmain:   addi t0, x0, 1\n")
    done = rars.run([path])
    assert "dropping off the bottom" in done.stdout
    m = memory()
    m.poke(TEXT, 4, 0x00100293)
    assert m.fetch(TEXT) is not None and m.fetch(TEXT + 4) is None
