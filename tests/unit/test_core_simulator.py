"""The loop of the machine: one turn, a run, and every way a run can end.

Expected values come from R-SIM-LOOP and R-SIM-REASON, the verified order of RARS:
a waiting event is taken before the instruction, a faulting instruction does not
count as carried out, the step limit counts turns, and `ebreak` is no trap of the
machine. Where RARS cannot do a thing at all - a `wfi` nobody can answer (DEV-46)
and a breakpoint without its window (DEV-55) - the reason is ours.
"""

import pytest

from pyrars.core.machine import Machine
from pyrars.core.memory import Access
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop, StopReason, Stepped
from pyrars.core.traps import BREAKPOINT, ILLEGAL_INSTRUCTION, UIE_BIT
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT
from pyrars.isa.program import AssembledProgram, TextEntry
from pyrars.isa.registers import CSRS

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
HANDLER = TEXT + 0x100
NOP = 0x00000013  # addi x0, x0, 0
ECALL = encode(find("ecall", 32), {})
EBREAK = encode(find("ebreak", 32), {})
A0, A7 = 10, 17


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def simulator(*words: int, xlen: int = 32, depth: int = 0, **values: int) -> Simulator:
    """A simulator over a machine holding the words as its program."""
    machine = Machine(Options(xlen=xlen, history_depth=depth))
    for index, value in enumerate(words):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in values.items():
        machine.x.write(int(number[1:]), value)
    return Simulator(machine)


def exit_with(code: int) -> tuple[int, ...]:
    """The three instructions a program ends with: the service 93 and its code."""
    return (word("addi", rd=A7, rs1=0, imm=93), word("addi", rd=A0, rs1=0, imm=code),
            ECALL)


def handler(simulator: Simulator, *words: int) -> None:
    """A handler in place and interrupts allowed. It returns with `uret` unless the
    test gives it something else to do - and `uret` goes back to the instruction
    that faulted, which would fault again for ever."""
    for index, value in enumerate(words or (word("uret"),)):
        simulator.machine.memory.poke(HANDLER + 4 * index, 4, value)
    simulator.machine.csr.write(CSRS["utvec"], HANDLER)
    simulator.machine.csr.write(CSRS["ustatus"], UIE_BIT)


# ------------------------------------------------------------------- one turn


def test_a_turn_says_what_it_did():
    s = simulator(word("addi", rd=5, rs1=0, imm=7))
    turn = s.step()
    assert isinstance(turn, Stepped)
    assert (turn.pc, turn.word, turn.next_pc) == (TEXT, word("addi", rd=5, rs1=0, imm=7),
                                                  TEXT + 4)
    assert turn.instr.instr.mnemonic == "addi" and turn.retired is True
    assert (turn.trap, turn.taken) == (None, None)
    assert s.count == 1 and s.machine.x.read(5) == 7


def test_a_jump_says_where_the_machine_went():
    s = simulator(word("jal", rd=1, imm=0x40))
    turn = s.step()
    assert (turn.pc, turn.next_pc) == (TEXT, TEXT + 0x40)


def test_an_instruction_that_traps_does_not_count():
    s = simulator(word("lw", rd=5, rs1=0, imm=1))  # misaligned
    turn = s.step()
    assert turn.trap is not None and turn.retired is False
    assert s.count == 0 and s.machine.csr.read(CSRS["instret"]) == 0
    assert s.machine.pending.trap is not None  # waiting to be taken


def test_the_event_of_a_turn_is_the_one_it_took():
    s = simulator(word("lw", rd=5, rs1=0, imm=1), NOP)
    handler(s)
    s.step()  # the load faults
    turn = s.step()  # the trap is taken, then the handler runs
    assert turn.taken is not None and turn.taken.handled is True
    assert turn.pc == HANDLER


def test_a_word_that_is_no_instruction():
    s = simulator(0x11223344)
    s.step()
    stop = s.step()  # the trap has nowhere to go
    assert (stop.reason, stop.address) == (StopReason.EXCEPTION, TEXT)
    assert stop.message == "Undefined instruction 0x11223344"


def test_a_fetch_that_cannot_be_made_is_no_exception_of_python():
    """A jump to a misaligned address: the trap goes into its slot like any other
    (INV-E), and the machine stops on it the next turn."""
    s = simulator(word("jalr", rd=0, rs1=5, imm=0), x5=TEXT + 2)
    s.step()
    turn = s.step()
    assert turn.trap is not None and turn.retired is False
    stop = s.step()
    assert stop.reason is StopReason.EXCEPTION
    assert stop.message == f"Instruction address not aligned to word boundary 0x{TEXT + 2:08x}"


# ----------------------------------------------------------------- the reasons


def test_a_program_that_asks_to_stop():
    s = simulator(*exit_with(7))
    stop = s.run()
    assert (stop.reason, stop.code) == (StopReason.NORMAL_TERMINATION, 7)
    assert s.count == 2  # the service that ends a program does not count


def test_a_program_that_runs_off_its_text():
    s = simulator(NOP)
    stop = s.run()
    assert (stop.reason, stop.address) == (StopReason.CLIFF_TERMINATION, TEXT + 4)


def test_a_trap_with_nowhere_to_go():
    s = simulator(word("lw", rd=5, rs1=0, imm=1))
    stop = s.run()
    assert (stop.reason, stop.address) == (StopReason.EXCEPTION, TEXT)
    assert stop.message == "Load address not aligned to word boundary 0x00000001"


def test_a_trap_that_has_a_handler_is_no_stop():
    """The handler ends the program, because `uret` would go back to the load and
    fault again - which is what RARS does too."""
    s = simulator(word("lw", rd=5, rs1=0, imm=1))
    handler(s, *exit_with(0))
    assert s.run().reason is StopReason.NORMAL_TERMINATION


def test_waiting_for_an_interrupt_that_cannot_come():
    s = simulator(word("wfi"))
    stop = s.run()
    assert (stop.reason, stop.address) == (StopReason.WAITING, TEXT)


def test_the_step_limit_counts_turns():
    s = simulator(NOP, NOP, NOP, NOP)
    stop = s.run(max_steps=3)
    assert (stop.reason, stop.address) == (StopReason.MAX_STEPS, TEXT + 12)
    assert s.count == 3


def test_a_turn_that_only_takes_a_trap_is_a_turn():
    """The limit counts turns, as RARS counts them: the turn that takes the trap
    carries out no instruction, so three turns leave two instructions behind."""
    s = simulator(word("lw", rd=5, rs1=0, imm=1), NOP, NOP)
    handler(s, NOP, NOP, NOP)
    stop = s.run(max_steps=3)
    assert stop.reason is StopReason.MAX_STEPS
    assert s.count == 2


def test_a_breakpoint_of_the_command_line():
    s = simulator(NOP, NOP, NOP)
    stop = s.run(breakpoints=frozenset({TEXT + 8}))
    assert (stop.reason, stop.address) == (StopReason.BREAKPOINT, TEXT + 8)
    assert s.count == 2  # it stopped BEFORE the instruction there


def test_a_run_carries_on_from_the_breakpoint_it_stopped_at():
    s = simulator(NOP, NOP, *exit_with(0))
    breakpoints = frozenset({TEXT + 4})
    assert s.run(breakpoints=breakpoints).reason is StopReason.BREAKPOINT
    assert s.run(breakpoints=breakpoints).reason is StopReason.NORMAL_TERMINATION


def test_ebreak_counts_and_the_run_carries_on():
    """RARS stops at `ebreak` in its window and carries on past it from its command
    line (verified); ours does what it is told."""
    s = simulator(EBREAK, *exit_with(3))
    stop = s.run()
    assert (stop.reason, stop.code) == (StopReason.NORMAL_TERMINATION, 3)
    assert s.count == 3  # the breakpoint counts as carried out


def test_ebreak_stops_a_run_that_asked_for_it():
    s = simulator(NOP, EBREAK, *exit_with(0))
    stop = s.run(stop_at_ebreak=True)
    assert (stop.reason, stop.address) == (StopReason.BREAKPOINT, TEXT + 4)
    assert s.machine.pending.trap is None  # a breakpoint is no trap of the machine


def test_a_caller_can_pause_a_run():
    """`pause` comes from another thread than the one that runs (INV-T); here a
    subscriber of the memory stands for that thread."""
    s = simulator(word("sw", rs1=5, rs2=0, imm=0), NOP, NOP, x5=DATA)
    s.machine.memory.subscribe(Access.WRITE, lambda access: s.pause())
    stop = s.run()
    assert (stop.reason, stop.address) == (StopReason.PAUSE, TEXT + 4)
    assert s.run().reason is StopReason.CLIFF_TERMINATION  # and on again


def test_a_caller_can_stop_a_run():
    s = simulator(word("sw", rs1=5, rs2=0, imm=0), NOP, x5=DATA)
    s.machine.memory.subscribe(Access.WRITE, lambda access: s.stop())
    assert s.run().reason is StopReason.STOP


# ------------------------------------------------------- loading and going back


def test_loading_a_program_puts_the_machine_where_it_starts():
    machine = Machine(Options())
    s = Simulator(machine)
    program = AssembledProgram(
        xlen=32, mem_config="Default",
        text=(TextEntry(TEXT, word("addi", rd=5, rs1=0, imm=4), "addi x5,x0,4", None, ""),
              TextEntry(TEXT + 4, ECALL, "ecall", None, "")),
        data_base=DATA, data=b"", data_layout=(), symbols={}, globals=frozenset(),
        entry=TEXT, diagnostics=())
    s.load(program)
    assert machine.x.pc == TEXT and s.count == 0
    assert s.step().retired is True


def test_loading_a_program_again_starts_the_count_over():
    s = simulator(NOP, NOP)
    s.step()
    program = AssembledProgram(
        xlen=32, mem_config="Default",
        text=(TextEntry(TEXT, NOP, "addi x0,x0,0", None, ""),),
        data_base=DATA, data=b"", data_layout=(), symbols={}, globals=frozenset(),
        entry=TEXT, diagnostics=())
    s.load(program)
    assert s.count == 0


def test_a_turn_can_be_taken_back():
    s = simulator(word("addi", rd=5, rs1=0, imm=7), NOP, depth=10)
    s.step()
    s.step()
    assert (s.count, s.machine.x.pc) == (2, TEXT + 8)
    assert s.back_step() is True
    assert (s.count, s.machine.x.pc) == (1, TEXT + 4)
    assert s.back_step() is True
    assert (s.count, s.machine.x.read(5)) == (0, 0)
    assert s.back_step() is False


def test_without_a_journal_nothing_can_be_taken_back():
    s = simulator(NOP)
    s.step()
    assert s.machine.history is None and s.back_step() is False
