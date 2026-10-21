"""What a run would have cost a machine with a pipeline of five stages.

Expected values are worked out by hand from the model itself, which is the one of
the textbooks: five stages of a cycle each, so one instruction takes five cycles
and a stream of them one cycle apiece afterwards; a value may be forwarded as soon
as it has been computed, and a load's as soon as it has been read, which is why a
load used by the instruction right after it costs one cycle; a stage holds its
instruction until the next takes it; and a branch settled in EX throws away the two
instructions fetched behind it when the guess was wrong. Nothing here comes from
RARS, which times nothing at all.
"""

import pytest

from pyrars.analysis.pipeline import (BRANCH, BUSY, DATA, LOAD, PORT, Pipeline, Settings,
                                      TRAP)
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop
from pyrars.isa.classes import Kind
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

TEXT, DATA_BASE = DEFAULT.text_base, DEFAULT.data_base


def word(mnemonic: str, **fields: int) -> int:
    return encode(find(mnemonic, 32), fields)


def timed(*words: int, settings: Settings = Settings(), steps: int | None = None,
          **values: int) -> Pipeline:
    """Run the words and time them."""
    machine = Machine(Options())
    for index, value in enumerate(words):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in values.items():
        machine.x.write(int(number[1:]), value)
    pipeline, simulator = Pipeline(settings), Simulator(machine)
    for _ in range(steps if steps is not None else len(words)):
        turn = simulator.step()
        if isinstance(turn, Stop):
            break
        pipeline.saw(turn)
    return pipeline


def starts(pipeline: Pipeline) -> list[tuple[int, ...]]:
    return [row.starts for row in pipeline.diagram]


NOP = word("addi", rd=9, rs1=0, imm=1)


# ------------------------------------------------------------------ the five stages


def test_a_machine_that_does_not_overlap_at_all():
    """Not a hindrance of a pipeline but the absence of one: every instruction
    costs its whole five cycles, which is the comparison the whole idea of a
    pipeline rests on (the architect, 2026-10-23)."""
    pipeline = timed(NOP, NOP, NOP, NOP, NOP, settings=Settings(overlap=False))
    assert pipeline.instructions == 5
    assert pipeline.cycles == 25  # five instructions of five cycles, none shared
    assert pipeline.cpi == 5.0
    assert pipeline.lost == 0  # it waited for nothing: there was nothing to wait for
    assert starts(pipeline) == [(0, 1, 2, 3, 4), (5, 6, 7, 8, 9),
                                (10, 11, 12, 13, 14), (15, 16, 17, 18, 19),
                                (20, 21, 22, 23, 24)]
    # and the same five instructions on a machine that does overlap
    assert timed(NOP, NOP, NOP, NOP, NOP).cycles == 9


def test_the_cycle_the_next_instruction_would_be_fetched_in():
    """Whoever walks the diagram a cycle at a time needs it: what is in the
    pipeline at a cycle is wholly known only once something has been fetched
    after it."""
    assert Pipeline().fetching == 0
    assert timed(NOP).fetching == 1  # one instruction fetched to a cycle
    assert timed(NOP, NOP, NOP).fetching == 3
    assert timed(NOP, NOP, settings=Settings(overlap=False)).fetching == 10


def test_one_instruction_takes_the_five_stages():
    pipeline = timed(NOP)
    assert pipeline.cycles == 5
    assert starts(pipeline) == [(0, 1, 2, 3, 4)]
    assert pipeline.lost == 0


def test_a_stream_of_instructions_takes_one_cycle_apiece():
    pipeline = timed(NOP, NOP, NOP)
    assert pipeline.cycles == 7  # five for the first and one for each after it
    assert pipeline.instructions == 3
    assert pipeline.cpi == 7 / 3
    assert starts(pipeline) == [(0, 1, 2, 3, 4), (1, 2, 3, 4, 5), (2, 3, 4, 5, 6)]


def test_nothing_takes_no_time():
    pipeline = Pipeline()
    assert (pipeline.cycles, pipeline.instructions, pipeline.cpi) == (0, 0, 0.0)


def test_a_word_that_is_no_instruction_times_nothing():
    pipeline = timed(0x11223344, steps=1)
    assert (pipeline.cycles, pipeline.instructions) == (0, 0)


# ------------------------------------------------------------ waiting for a value


def test_a_value_computed_can_be_used_at_once():
    """Forwarding: the result of the first is in the second's EX in time."""
    pipeline = timed(word("addi", rd=5, rs1=0, imm=1),
                     word("addi", rd=6, rs1=5, imm=1))
    assert pipeline.cycles == 6 and pipeline.lost == 0


def test_without_forwarding_a_value_waits_to_be_written_back():
    pipeline = timed(word("addi", rd=5, rs1=0, imm=1),
                     word("addi", rd=6, rs1=5, imm=1),
                     settings=Settings(forwarding=False))
    assert pipeline.cycles == 8
    assert pipeline.stalls[DATA] == 2


def test_a_load_used_by_the_instruction_after_it_costs_a_cycle():
    """Which forwarding cannot help: the value is still being read."""
    pipeline = timed(word("lw", rd=5, rs1=6, imm=0),
                     word("addi", rd=7, rs1=5, imm=1), x6=DATA_BASE)
    assert pipeline.cycles == 7
    assert pipeline.stalls[LOAD] == 1
    assert starts(pipeline) == [(0, 1, 2, 3, 4), (1, 2, 4, 5, 6)]


def test_a_load_used_two_instructions_later_costs_nothing():
    pipeline = timed(word("lw", rd=5, rs1=6, imm=0), NOP,
                     word("addi", rd=7, rs1=5, imm=1), x6=DATA_BASE)
    assert pipeline.cycles == 7 and pipeline.lost == 0


def test_a_value_out_of_memory_is_told_from_one_that_was_computed():
    """A wait is counted as a load where the value was coming out of memory, and as
    data where it was being computed - in both modes."""
    pipeline = timed(word("lw", rd=5, rs1=6, imm=0),
                     word("addi", rd=7, rs1=5, imm=1), x6=DATA_BASE,
                     settings=Settings(forwarding=False))
    assert pipeline.stalls[LOAD] == 2 and pipeline.stalls[DATA] == 0


def test_the_register_that_holds_zero_is_no_dependence():
    pipeline = timed(word("addi", rd=0, rs1=0, imm=1),
                     word("addi", rd=5, rs1=0, imm=1),
                     settings=Settings(forwarding=False))
    assert pipeline.cycles == 6 and pipeline.lost == 0


def test_the_two_register_files_are_their_own():
    """f1 and x1 are different registers, so nothing waits for anything."""
    pipeline = timed(word("fmv.w.x", rd=1, rs1=0),
                     word("addi", rd=5, rs1=1, imm=1),
                     settings=Settings(forwarding=False))
    assert pipeline.cycles == 6 and pipeline.lost == 0


# ------------------------------------------------------------ waiting for a stage


def test_an_instruction_that_holds_its_stage_holds_the_others_up():
    pipeline = timed(word("div", rd=5, rs1=6, rs2=7), NOP, NOP,
                     settings=Settings(latency={Kind.DIVIDE: 4}), x6=10, x7=3)
    assert pipeline.cycles == 10
    assert pipeline.stalls[BUSY] == 3
    # the division holds EX from cycle 2 to 5, so the next instruction computes at 6
    assert starts(pipeline) == [(0, 1, 2, 6, 7), (1, 2, 6, 7, 8), (2, 6, 7, 8, 9)]


def test_a_kind_of_instruction_may_be_given_any_length():
    pipeline = timed(word("mul", rd=5, rs1=6, rs2=7), NOP,
                     settings=Settings(latency={Kind.MULTIPLY: 3}), x6=2, x7=3)
    assert pipeline.cycles == 8  # five, two cycles more of EX, and one after it


def test_one_port_to_memory_holds_a_fetch_up():
    """The instruction fetched in the cycle a load reaches memory waits for it; the
    one right behind the load does not, for it is fetched long before."""
    load = word("lw", rd=5, rs1=6, imm=0)
    assert timed(load, NOP, NOP, NOP, NOP, NOP, NOP, x6=DATA_BASE).cycles == 11
    held = timed(load, NOP, NOP, NOP, NOP, NOP, NOP, x6=DATA_BASE,
                 settings=Settings(one_port=True))
    assert held.cycles == 12 and held.stalls[PORT] == 1


def test_every_load_holds_a_fetch_up_where_there_is_one_port():
    """Two loads far apart hold two fetches up: the cycle the first reached memory
    in is let go of once a fetch has passed it, or the second would be missed."""
    load = word("lw", rd=5, rs1=6, imm=0)
    program = (load, NOP, NOP, NOP, NOP, load, NOP, NOP, NOP, NOP)
    assert timed(*program, x6=DATA_BASE).cycles == 14
    held = timed(*program, x6=DATA_BASE, settings=Settings(one_port=True))
    assert held.cycles == 16 and held.stalls[PORT] == 2


def test_two_ports_are_the_default():
    """Which is what a machine with a cache of its own for the instructions has."""
    assert Settings().one_port is False


# ----------------------------------------------------------------- the guessing


def test_a_branch_that_was_not_taken_was_guessed_right():
    pipeline = timed(word("bne", rs1=0, rs2=0, imm=8), NOP, steps=2)
    assert (pipeline.branches, pipeline.mispredictions) == (1, 0)
    assert pipeline.stalls[BRANCH] == 0


def test_a_branch_that_was_taken_throws_away_what_was_fetched():
    pipeline = timed(word("beq", rs1=0, rs2=0, imm=8), NOP, NOP, steps=2)
    assert (pipeline.branches, pipeline.mispredictions) == (1, 1)
    assert pipeline.stalls[BRANCH] == 2  # the two fetched behind it
    assert pipeline.cycles == 9


def test_what_a_wrong_guess_costs_can_be_said():
    pipeline = timed(word("beq", rs1=0, rs2=0, imm=8), NOP, NOP, steps=2,
                     settings=Settings(penalty=4))
    assert pipeline.stalls[BRANCH] == 4


# -------------------------------------------------------------------- the traps


def test_an_instruction_that_could_not_be_carried_out_empties_the_pipeline():
    pipeline = timed(word("lw", rd=5, rs1=0, imm=1), NOP, steps=1)  # misaligned
    assert pipeline.stalls[TRAP] == 2
    assert pipeline.instructions == 1  # it took the stages up to the one it failed in


# -------------------------------------------------------------- what is kept of it


def test_the_diagram_holds_the_first_instructions_and_no_more():
    pipeline = timed(NOP, NOP, NOP, NOP, settings=Settings(diagram=2))
    assert len(pipeline.diagram) == 2
    assert pipeline.instructions == 4  # and the totals are exact


def test_a_diagram_of_nothing_is_kept():
    pipeline = timed(NOP, NOP, settings=Settings(diagram=0))
    assert pipeline.diagram == [] and pipeline.cycles == 6


def test_a_row_of_the_diagram_says_what_happened():
    pipeline = timed(word("lw", rd=5, rs1=6, imm=0),
                     word("addi", rd=7, rs1=5, imm=1), x6=DATA_BASE)
    first, second = pipeline.diagram
    assert (first.mnemonic, first.pc, first.ex_cycles) == ("lw", TEXT, 1)
    assert (second.mnemonic, second.waited) == ("addi", 1)


def test_the_cycles_lost_are_the_sum_of_the_causes():
    pipeline = timed(word("lw", rd=5, rs1=6, imm=0),
                     word("addi", rd=7, rs1=5, imm=1),
                     word("beq", rs1=0, rs2=0, imm=8), steps=3, x6=DATA_BASE)
    assert pipeline.lost == sum(pipeline.stalls.values()) == 3  # one load, two branch


def test_a_pipeline_can_be_emptied():
    """And then it times from the first cycle again: the stages are free, no
    register is waited for and nothing of the run before is left."""
    machine = Machine(Options())
    machine.memory.poke(TEXT, 4, word("addi", rd=5, rs1=0, imm=1))
    machine.memory.poke(TEXT + 4, 4, word("addi", rd=6, rs1=5, imm=1))
    pipeline, simulator = Pipeline(Settings(forwarding=False)), Simulator(machine)
    pipeline.saw(simulator.step())
    pipeline.saw(simulator.step())
    assert pipeline.lost == 2  # the second waited for the first to be written back

    pipeline.reset()
    assert (pipeline.cycles, pipeline.instructions, pipeline.diagram) == (0, 0, [])
    machine.x.pc = TEXT + 4  # the second instruction once more, on its own
    pipeline.saw(Simulator(machine).step())
    assert (pipeline.cycles, pipeline.lost) == (5, 0)
    assert starts(pipeline) == [(0, 1, 2, 3, 4)]


# ------------------------------------------------------------------ the settings


@pytest.mark.parametrize("options, says", [
    ({"penalty": -1}, "never below nothing"),
    ({"trap_penalty": -1}, "never below nothing"),
    ({"diagram": -1}, "never below nothing"),
    ({"latency": {Kind.DIVIDE: 0}}, "at least one cycle"),
])
def test_settings_that_make_no_machine(options, says):
    with pytest.raises(ValueError, match=says):
        Settings(**options)


def test_timing_changes_nothing_of_the_run():
    """INV-P: the model watches and never touches."""
    words = (word("addi", rd=5, rs1=0, imm=7), word("lw", rd=6, rs1=7, imm=0),
             word("sw", rs1=7, rs2=5, imm=4))

    def state(time: bool) -> tuple:
        machine = Machine(Options())
        for index, value in enumerate(words):
            machine.memory.poke(TEXT + 4 * index, 4, value)
        machine.x.write(7, DATA_BASE)
        pipeline, simulator = Pipeline(), Simulator(machine)
        for _ in range(3):
            turn = simulator.step()
            if time and not isinstance(turn, Stop):
                pipeline.saw(turn)
        return (tuple(machine.x.values), machine.x.pc, simulator.count,
                machine.memory.peek(DATA_BASE + 4, 4))

    assert state(True) == state(False)
