"""What the integer instructions do to the machine.

Expected values are derived by hand from the RISC-V ISA manual v20260120: the
base integer set, the table of division by zero and of the single overflow in the
M extension, the sign extension of the 32-bit forms of RV64, and the rules of the
control register instructions in Zicsr.

The instruction words are built with `isa.codec.encode`, so a test says which
operands it means and no assembler stands between.
"""

import pytest

from pyrars.core.executor import as_signed, execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.traps import BREAKPOINT, ILLEGAL_INSTRUCTION, Trap
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, instructions
from pyrars.isa.memory import DEFAULT
from pyrars.isa.registers import CSRS

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
A, B, C = 5, 6, 7  # t0, t1, t2


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def machine(*words: int, xlen: int = 32, **values: int) -> Machine:
    """A machine holding the words as its program, with registers set."""
    m = Machine(Options(xlen=xlen))
    for index, value in enumerate(words):
        m.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in values.items():
        m.x.write(int(number[1:]), value)
    return m


def step(m: Machine) -> None:
    execute(m, m.fetch())


def run(m: Machine, count: int) -> Machine:
    for _ in range(count):
        step(m)
    return m


# ------------------------------------------------------------- the arithmetic


@pytest.mark.parametrize("mnemonic, left, right, expected", [
    ("add", 5, 7, 12),
    ("add", 0xFFFFFFFF, 1, 0),  # -1 + 1 wraps to zero
    ("add", 0x7FFFFFFF, 1, 0x80000000),
    ("sub", 5, 7, 0xFFFFFFFE),
    ("sub", 0, 1, 0xFFFFFFFF),
    ("and", 0xF0F0F0F0, 0xFF00FF00, 0xF000F000),
    ("or", 0xF0F0F0F0, 0x0F0F0F0F, 0xFFFFFFFF),
    ("xor", 0xFF00FF00, 0x0F0F0F0F, 0xF00FF00F),
    ("sll", 1, 31, 0x80000000),
    ("sll", 1, 32, 1),  # only the low five bits of the amount count
    ("sll", 0x80000001, 1, 2),
    ("srl", 0x80000000, 31, 1),
    ("srl", 0xFFFFFFFF, 4, 0x0FFFFFFF),
    ("sra", 0x80000000, 31, 0xFFFFFFFF),  # the sign is dragged along
    ("sra", 0x7FFFFFFF, 31, 0),
    ("slt", 0xFFFFFFFF, 1, 1),  # -1 < 1
    ("slt", 1, 0xFFFFFFFF, 0),
    ("sltu", 0xFFFFFFFF, 1, 0),  # but as unsigned numbers it is the larger one
    ("sltu", 1, 0xFFFFFFFF, 1),
])
def test_an_operation_of_two_registers(mnemonic, left, right, expected):
    m = machine(word(mnemonic, rd=C, rs1=A, rs2=B), x5=left, x6=right)
    step(m)
    assert m.x.read(C) == expected
    assert m.x.pc == TEXT + 4


@pytest.mark.parametrize("mnemonic, left, right, expected", [
    ("mul", 5, 7, 35),
    ("mul", 0xFFFFFFFF, 0xFFFFFFFF, 1),  # (-1) * (-1)
    ("mul", 0x80000000, 2, 0),  # only the low word is kept
    ("mulh", 0x80000000, 2, 0xFFFFFFFF),  # the high word of -2**32
    ("mulh", 0xFFFFFFFF, 0xFFFFFFFF, 0),
    ("mulhu", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFE),
    ("mulhsu", 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF),  # -1 * (2**32 - 1)
    ("div", 35, 7, 5),
    ("div", 0xFFFFFFFB, 2, 0xFFFFFFFE),  # -5 / 2 is -2: toward zero, not down
    ("div", 5, 0xFFFFFFFE, 0xFFFFFFFE),  # 5 / -2
    ("div", 7, 0, 0xFFFFFFFF),  # division by zero gives all ones
    ("div", 0x80000000, 0xFFFFFFFF, 0x80000000),  # the one overflow
    ("divu", 7, 0, 0xFFFFFFFF),
    ("divu", 0xFFFFFFFF, 2, 0x7FFFFFFF),
    ("rem", 0xFFFFFFFB, 2, 0xFFFFFFFF),  # -5 % 2 is -1
    ("rem", 5, 0xFFFFFFFE, 1),  # 5 % -2 is 1
    ("rem", 7, 0, 7),  # the dividend comes back
    ("rem", 0x80000000, 0xFFFFFFFF, 0),  # and the overflow gives zero
    ("remu", 7, 0, 7),
    ("remu", 0xFFFFFFFF, 7, 3),
])
def test_a_multiplication_or_a_division(mnemonic, left, right, expected):
    m = machine(word(mnemonic, rd=C, rs1=A, rs2=B), x5=left, x6=right)
    step(m)
    assert m.x.read(C) == expected


@pytest.mark.parametrize("mnemonic, left, imm, expected", [
    ("addi", 5, 7, 12),
    ("addi", 5, -7, 0xFFFFFFFE),
    ("andi", 0xFF00FF00, -1, 0xFF00FF00),  # the immediate has its sign extended
    ("ori", 0, -2048, 0xFFFFF800),
    ("xori", 0xFFFFFFFF, -1, 0),
    ("slti", 0xFFFFFFFF, 0, 1),
    ("sltiu", 0xFFFFFFFF, -1, 0),  # both are the same unsigned number
    ("sltiu", 0, -1, 1),
])
def test_an_operation_with_an_immediate(mnemonic, left, imm, expected):
    m = machine(word(mnemonic, rd=C, rs1=A, imm=imm), x5=left)
    step(m)
    assert m.x.read(C) == expected


@pytest.mark.parametrize("mnemonic, left, shamt, expected", [
    ("slli", 1, 0, 1),
    ("slli", 1, 31, 0x80000000),
    ("srli", 0x80000000, 31, 1),
    ("srai", 0x80000000, 31, 0xFFFFFFFF),
    ("srai", 0x40000000, 30, 1),
])
def test_a_shift_by_an_immediate(mnemonic, left, shamt, expected):
    m = machine(word(mnemonic, rd=C, rs1=A, shamt=shamt), x5=left)
    step(m)
    assert m.x.read(C) == expected


def test_the_zero_register_takes_no_result():
    m = machine(word("addi", rd=0, rs1=0, imm=7))
    step(m)
    assert m.x.read(0) == 0


# ------------------------------------------------------- the 64-bit machine


@pytest.mark.parametrize("mnemonic, left, right, expected", [
    ("add", 0xFFFFFFFF, 1, 0x100000000),  # a 64-bit machine has room for it
    ("addw", 0xFFFFFFFF, 1, 0),  # the 32-bit form wraps and extends the sign
    ("addw", 0x7FFFFFFF, 1, 0xFFFFFFFF80000000),
    ("subw", 0, 1, 0xFFFFFFFFFFFFFFFF),
    ("sllw", 1, 31, 0xFFFFFFFF80000000),
    ("sllw", 1, 32, 1),  # five bits of the amount, as in a 32-bit machine
    ("srlw", 0xFFFFFFFF80000000, 31, 1),  # only the low word is looked at
    ("sraw", 0x80000000, 31, 0xFFFFFFFFFFFFFFFF),
    ("mulw", 0x100000000, 3, 0),  # the high half takes no part
    ("divw", 7, 0, 0xFFFFFFFFFFFFFFFF),
    ("divw", 0xFFFFFFFF80000000, 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFF80000000),
    ("remw", 0xFFFFFFFFFFFFFFFB, 2, 0xFFFFFFFFFFFFFFFF),
    ("remuw", 0xFFFFFFFF, 7, 3),
    ("sll", 1, 63, 1 << 63),
    ("sll", 1, 64, 1),  # six bits of the amount in a 64-bit machine
    ("sra", 1 << 63, 63, 0xFFFFFFFFFFFFFFFF),
    ("mulhu", 1 << 63, 2, 1),
])
def test_an_operation_of_a_64_bit_machine(mnemonic, left, right, expected):
    m = machine(word(mnemonic, xlen=64, rd=C, rs1=A, rs2=B), xlen=64, x5=left, x6=right)
    step(m)
    assert m.x.read(C) == expected


@pytest.mark.parametrize("mnemonic, left, value, expected", [
    ("addiw", 0x7FFFFFFF, 1, 0xFFFFFFFF80000000),
    ("slliw", 1, 31, 0xFFFFFFFF80000000),
    ("srliw", 0xFFFFFFFF80000000, 31, 1),
    ("sraiw", 0x80000000, 31, 0xFFFFFFFFFFFFFFFF),
])
def test_a_32_bit_form_with_an_immediate(mnemonic, left, value, expected):
    name = "imm" if mnemonic == "addiw" else "shamt"
    m = machine(word(mnemonic, xlen=64, rd=C, rs1=A, **{name: value}), xlen=64, x5=left)
    step(m)
    assert m.x.read(C) == expected


# ---------------------------------------------------------- memory and jumps


@pytest.mark.parametrize("mnemonic, offset, expected", [
    ("lw", 0, 0x89ABCDEF),
    ("lb", 0, 0xFFFFFFEF),  # the sign of a byte is extended
    ("lbu", 0, 0x000000EF),
    ("lh", 0, 0xFFFFCDEF),
    ("lhu", 2, 0x000089AB),
    ("lb", 3, 0xFFFFFF89),
])
def test_a_load_and_its_sign(mnemonic, offset, expected):
    m = machine(word(mnemonic, rd=C, rs1=A, imm=offset), x5=DATA)
    m.memory.write(DATA, 4, 0x89ABCDEF)
    step(m)
    assert m.x.read(C) == expected


@pytest.mark.parametrize("mnemonic, size, expected", [
    ("sb", 1, 0x000000EF), ("sh", 2, 0x0000CDEF), ("sw", 4, 0x89ABCDEF)])
def test_a_store_writes_as_many_bytes_as_it_says(mnemonic, size, expected):
    m = machine(word(mnemonic, rs1=A, rs2=B, imm=0), x5=DATA, x6=0x89ABCDEF)
    step(m)
    assert m.memory.read(DATA, 4) == expected


def test_the_wide_loads_and_stores_of_a_64_bit_machine():
    m = machine(word("sd", xlen=64, rs1=A, rs2=B, imm=0),
                word("ld", xlen=64, rd=C, rs1=A, imm=0),
                word("lwu", xlen=64, rd=C, rs1=A, imm=0),
                word("lw", xlen=64, rd=C, rs1=A, imm=0),
                xlen=64, x5=DATA, x6=0x89ABCDEF01234567)
    step(m)
    assert m.memory.read(DATA, 8) == 0x89ABCDEF01234567
    step(m)
    assert m.x.read(C) == 0x89ABCDEF01234567
    step(m)
    assert m.x.read(C) == 0x01234567
    step(m)
    assert m.x.read(C) == 0x01234567  # lw extends the sign of the low word


@pytest.mark.parametrize("mnemonic, left, right, taken", [
    ("beq", 5, 5, True), ("beq", 5, 6, False),
    ("bne", 5, 6, True), ("bne", 5, 5, False),
    ("blt", 0xFFFFFFFF, 1, True), ("blt", 1, 0xFFFFFFFF, False),
    ("bge", 1, 0xFFFFFFFF, True), ("bge", 5, 5, True),
    ("bltu", 1, 0xFFFFFFFF, True), ("bgeu", 0xFFFFFFFF, 1, True),
])
def test_a_branch_goes_where_it_says(mnemonic, left, right, taken):
    m = machine(word(mnemonic, rs1=A, rs2=B, imm=16), x5=left, x6=right)
    step(m)
    assert m.x.pc == TEXT + (16 if taken else 4)


def test_a_branch_backwards():
    m = machine(0, 0, word("beq", rs1=0, rs2=0, imm=-8))
    m.x.pc = TEXT + 8
    step(m)
    assert m.x.pc == TEXT


def test_the_two_jumps():
    m = machine(word("jal", rd=1, imm=32))
    step(m)
    assert m.x.pc == TEXT + 32 and m.x.read(1) == TEXT + 4

    m = machine(word("jalr", rd=1, rs1=A, imm=4), x5=TEXT + 64)
    step(m)
    assert m.x.pc == TEXT + 68 and m.x.read(1) == TEXT + 4

    # the lowest bit of the target is dropped, and the target is read before rd
    m = machine(word("jalr", rd=A, rs1=A, imm=3), x5=TEXT + 64)
    step(m)
    assert m.x.pc == TEXT + 66 and m.x.read(A) == TEXT + 4


def test_the_two_upper_immediates():
    m = machine(word("lui", rd=C, imm=0x12345), word("auipc", rd=B, imm=0x10))
    step(m)
    assert m.x.read(C) == 0x12345000
    step(m)
    assert m.x.read(B) == TEXT + 4 + 0x10000

    wide = machine(word("lui", xlen=64, rd=C, imm=0x80000), xlen=64)
    step(wide)
    assert wide.x.read(C) == 0xFFFFFFFF80000000  # the sign of the 32-bit value


# ----------------------------------------------------- the system instructions


def test_the_control_register_instructions():
    number = CSRS["uscratch"]
    m = machine(word("csrrw", rd=B, csr=number, rs1=A),
                word("csrrs", rd=C, csr=number, rs1=0),
                word("csrrc", rd=0, csr=number, rs1=A),
                word("csrrsi", rd=0, csr=number, uimm=3),
                x5=0xF0)
    step(m)
    assert m.csr.read(number) == 0xF0 and m.x.read(B) == 0  # the old value comes back
    step(m)
    assert m.x.read(C) == 0xF0  # a source of x0 only reads
    step(m)
    assert m.csr.read(number) == 0  # csrrc cleared the bits again
    step(m)
    assert m.csr.read(number) == 3


def test_a_read_only_register_can_be_read_but_not_written():
    m = machine(word("csrrs", rd=C, csr=CSRS["cycle"], rs1=0),
                word("csrrs", rd=C, csr=CSRS["cycle"], rs1=A), x5=1)
    step(m)
    assert m.x.read(C) == 0
    with pytest.raises(Trap) as raised:
        step(m)
    assert raised.value.message == "Cannot write to the read-only control register cycle"


def test_a_breakpoint_is_raised_for_the_simulator():
    m = machine(word("ebreak"))
    with pytest.raises(Trap) as raised:
        step(m)
    assert (raised.value.cause, raised.value.message) == (BREAKPOINT, "ebreak")


def test_a_call_of_the_environment_reaches_the_services():
    """What each service does is in test_core_syscalls.py; here it is enough that
    `ecall` arrives there, which a number nobody serves shows."""
    m = machine(word("ecall"), x17=777)
    with pytest.raises(Trap) as raised:
        step(m)
    assert raised.value.message == "Invalid or unimplemented syscall service 777"


def test_a_fence_does_nothing_but_move_on():
    m = machine(word("fence", pred=15, succ=15), word("fence.i"))
    run(m, 2)
    assert m.x.pc == TEXT + 8


def test_a_word_that_encodes_no_instruction():
    m = machine(0x11223344)
    with pytest.raises(Trap) as raised:
        step(m)
    assert raised.value.cause == ILLEGAL_INSTRUCTION
    assert raised.value.message == "Undefined instruction 0x11223344"
    assert raised.value.value == 0x11223344


def test_every_instruction_of_the_set_is_carried_out():
    """Nothing is left over: the floating point instructions came in stage 18,
    `uret` and `wfi` with the traps of stage 19 (where they are tested)."""
    from pyrars.core import floats
    from pyrars.core.executor import (BRANCHES, HANDLERS, IMMEDIATE_FORMS, LOADS,
                                      REGISTER_FORMS, SHIFT_FORMS, STORES)
    known = (set(HANDLERS) | set(REGISTER_FORMS) | set(IMMEDIATE_FORMS) | set(SHIFT_FORMS)
             | set(LOADS) | set(STORES) | set(BRANCHES) | floats.MNEMONICS)
    for xlen in (32, 64):
        assert [instr.mnemonic for instr in instructions(xlen)
                if instr.mnemonic not in known] == []


# ------------------------------------------------------------------ a program


def test_a_loop_that_adds_the_first_ten_numbers():
    """t0 = 0; t1 = 10; while t1 != 0: t0 += t1; t1 -= 1"""
    m = machine(
        word("addi", rd=A, rs1=0, imm=0),
        word("addi", rd=B, rs1=0, imm=10),
        word("beq", rs1=B, rs2=0, imm=16),  # to the end
        word("add", rd=A, rs1=A, rs2=B),
        word("addi", rd=B, rs1=B, imm=-1),
        word("jal", rd=0, imm=-12),  # back to the test
        word("ecall"),
    )
    for _ in range(100):
        fetched = m.fetch()
        try:
            execute(m, fetched)
        except Trap:
            break
        m.csr.retire()
    assert m.x.read(A) == 55 and m.x.read(B) == 0
    assert m.csr.read(CSRS["instret"]) == 2 + 10 * 4 + 1


def test_the_helper_reads_a_value_as_a_number():
    assert as_signed(0xFFFFFFFF, 32) == -1
    assert as_signed(0x7FFFFFFF, 32) == 0x7FFFFFFF
    assert as_signed(1 << 63, 64) == -(1 << 63)
