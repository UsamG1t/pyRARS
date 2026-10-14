"""Which call a run is inside, as far as the convention lets anyone tell.

Expected values come from the convention itself (the RISC-V assembly manual: a
call leaves its return address in `ra`, and `ret` is `jalr x0, 0(ra)`), and every
test here is a test of a GUESS about a program's shape - which is why one of them
is a program that does not save `ra` and is read wrongly on purpose.
"""

import pytest

from pyrars.analysis.callstack import CallStack, Frame
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stepped, Stop
from pyrars.isa.codec import decode, encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

TEXT, STACK = DEFAULT.text_base, DEFAULT.stack_pointer


def word(mnemonic: str, **fields: int) -> int:
    return encode(find(mnemonic, 32), fields)


def watched(program: dict[int, int], turns: int, kept: int = 10_000,
            with_sp: bool = True) -> tuple[CallStack, Machine]:
    """Run a program laid out by offsets and watch the calls."""
    machine = Machine(Options())
    for offset, value in program.items():
        machine.memory.poke(TEXT + offset, 4, value)
    stack, simulator = CallStack(depth_kept=kept), Simulator(machine)
    for _ in range(turns):
        turn = simulator.step()
        if isinstance(turn, Stop):
            break
        stack.saw(turn, sp=machine.x.read(2) if with_sp else None)
    return stack, machine


RET = word("jalr", rd=0, rs1=1, imm=0)

# main calls f, which saves its return address, calls g, puts it back and returns.
PROPER = {
    0x00: word("jal", rd=1, imm=0x20),  # main: call f
    0x04: word("addi", rd=5, rs1=0, imm=1),
    0x20: word("addi", rd=2, rs1=2, imm=-4),  # f: make room
    0x24: word("sw", rs1=2, rs2=1, imm=0),  # and save ra
    0x28: word("jal", rd=1, imm=0x18),  # call g
    0x2C: word("lw", rd=1, rs1=2, imm=0),  # put ra back
    0x30: word("addi", rd=2, rs1=2, imm=4),
    0x34: RET,  # and return to main
    0x40: RET,  # g: return at once
}

# the same shape, but f never saves ra - so its own return goes astray
CARELESS = {
    0x00: word("jal", rd=1, imm=0x20),
    0x04: word("addi", rd=5, rs1=0, imm=1),
    0x20: word("jal", rd=1, imm=0x20),
    0x24: RET,
    0x40: RET,
}


# ------------------------------------------------------------------- the calls


def test_a_call_is_written_down_with_where_it_came_from_and_goes_back_to():
    stack, machine = watched({0x00: word("jal", rd=1, imm=0x20), 0x20: RET}, turns=1)
    assert stack.frames == [Frame(called=TEXT + 0x20, comes_back_to=TEXT + 4,
                                  called_from=TEXT, sp=STACK)]
    assert (stack.calls, stack.depth, stack.deepest) == (1, 1, 1)


def test_where_the_stack_pointer_stood_is_written_down_if_it_was_known():
    stack, machine = watched({0x00: word("jal", rd=1, imm=0x20), 0x20: RET}, turns=1,
                             with_sp=False)
    assert stack.frames[0].sp is None


def test_a_call_through_a_register_is_a_call():
    program = {0x00: word("addi", rd=6, rs1=0, imm=0x40),
               0x04: word("jalr", rd=1, rs1=6, imm=0)}
    stack, machine = watched(program, turns=2)
    assert stack.calls == 1 and stack.frames[0].comes_back_to == TEXT + 8


def test_a_jump_that_leaves_no_address_behind_is_no_call():
    """`j label` is `jal x0, label`: nothing to come back to, so nothing is a call."""
    stack, machine = watched({0x00: word("jal", rd=0, imm=0x20),
                              0x20: word("addi", rd=5, rs1=0, imm=1)}, turns=2)
    assert (stack.calls, stack.depth) == (0, 0)


# ----------------------------------------------------------------- the returns


def test_a_call_and_its_return_leave_nothing_behind():
    stack, machine = watched(PROPER, turns=9)
    assert (stack.calls, stack.returns) == (2, 2)
    assert (stack.depth, stack.deepest) == (0, 2)
    assert (stack.confused, stack.unmatched) == (0, 0)


def test_the_frames_say_what_the_run_is_inside():
    stack, machine = watched(PROPER, turns=4)  # inside both calls
    assert [frame.called for frame in stack.frames] == [TEXT + 0x20, TEXT + 0x40]
    assert [frame.comes_back_to for frame in stack.frames] == [TEXT + 4, TEXT + 0x2C]
    assert stack.frames[1].sp == STACK - 4  # f had made room on the stack


def test_a_program_that_does_not_save_its_return_address_is_read_wrongly():
    """And the model says so instead of pretending: the second return lands where
    the inner call left `ra`, not where the outer call expects."""
    stack, machine = watched(CARELESS, turns=4)
    assert (stack.calls, stack.returns) == (2, 2)
    assert stack.confused == 1
    assert stack.depth == 0


def test_a_return_with_nothing_to_return_from_is_counted():
    """A run may begin inside a call, so this is no error of the program."""
    stack, machine = watched({0x00: RET}, turns=1)
    assert (stack.returns, stack.unmatched, stack.depth) == (1, 1, 0)


def test_a_jump_through_another_register_is_no_return_by_the_convention():
    """The guess follows `ra` alone; a program that returns through another
    register is read wrongly, which is what a guess means."""
    program = {0x00: word("jal", rd=1, imm=0x20),
               0x20: word("addi", rd=6, rs1=1, imm=0),  # keep ra in t1
               0x24: word("jalr", rd=0, rs1=6, imm=0)}  # and return through it
    stack, machine = watched(program, turns=3)
    assert (stack.calls, stack.returns) == (1, 0)
    assert stack.depth == 1  # the call looks as if it never came back


def test_a_jump_to_the_return_address_that_keeps_one_of_its_own_is_no_return():
    """`jalr t1, 0(ra)` goes where a return would go but leaves an address behind,
    so it is a jump through `ra`, not a return from anything."""
    program = {0x00: word("jal", rd=1, imm=0x20),
               0x20: word("jalr", rd=6, rs1=1, imm=0)}
    stack, machine = watched(program, turns=2)
    assert (stack.returns, stack.depth) == (0, 1)


def test_a_jump_that_adds_to_the_return_address_is_no_return():
    program = {0x00: word("jal", rd=1, imm=0x20),
               0x20: word("jalr", rd=0, rs1=1, imm=4)}
    stack, machine = watched(program, turns=2)
    assert (stack.returns, stack.depth) == (0, 1)


# ------------------------------------------------------------- how deep it goes


def test_calls_deeper_than_the_model_follows_are_counted_only():
    """A recursion without an end must not eat the memory."""
    program = {0x00: word("jal", rd=1, imm=0x20),
               0x20: word("jal", rd=1, imm=0x20),
               0x40: word("jal", rd=1, imm=0x20),
               0x60: word("addi", rd=5, rs1=0, imm=1)}
    stack, machine = watched(program, turns=3, kept=2)
    assert (stack.calls, stack.depth, stack.beyond) == (3, 2, 1)
    assert stack.deepest == 2


def test_a_stack_of_no_frames_at_all():
    with pytest.raises(ValueError, match="at least one frame"):
        CallStack(depth_kept=0)


# ------------------------------------------------------------- what is not a call


def test_an_instruction_that_was_not_carried_out_is_neither():
    """The model counts what happened. No jump of our machine can fail - a target
    that is no word is refused when the next instruction is fetched, not by the
    jump itself - so the record is made here by hand; the model is not to know
    which machine handed it over."""
    turn = Stepped(pc=TEXT, word=word("jal", rd=1, imm=0x20),
                   instr=decode(word("jal", rd=1, imm=0x20), 32),
                   next_pc=TEXT + 0x20, trap=2, retired=False)
    stack = CallStack()
    stack.saw(turn)
    assert (stack.calls, stack.depth) == (0, 0)


def test_a_word_that_is_no_instruction_is_neither():
    stack, machine = watched({0x00: 0x11223344}, turns=1)
    assert (stack.calls, stack.returns) == (0, 0)


def test_a_stack_can_be_emptied():
    stack, machine = watched(PROPER, turns=5)
    stack.reset()
    assert (stack.frames, stack.calls, stack.deepest) == ([], 0, 0)
    assert (stack.unmatched, stack.confused, stack.beyond) == (0, 0, 0)


def test_watching_changes_nothing_of_the_run():
    """INV-P: the model watches and never touches."""
    def state(watch: bool) -> tuple:
        machine = Machine(Options())
        for offset, value in PROPER.items():
            machine.memory.poke(TEXT + offset, 4, value)
        stack, simulator = CallStack(), Simulator(machine)
        for _ in range(9):
            turn = simulator.step()
            if watch and not isinstance(turn, Stop):
                stack.saw(turn, sp=machine.x.read(2))
        return tuple(machine.x.values), machine.x.pc, simulator.count

    assert state(True) == state(False)
