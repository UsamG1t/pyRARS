"""What a run was made of: the counters.

Expected values are derived from the programs the tests run: how many instructions
of each kind they carry out, how many branches go and how many do not. The kinds
and the five of RARS come from `isa/classes.py`. The counters are passive (INV-P):
a run counted and a run not counted must leave the machine in the same state.
"""

import pytest

from pyrars.analysis.stats import Statistics
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop
from pyrars.isa.classes import Kind
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
NOP = 0x00000013


def word(mnemonic: str, xlen: int = 32, **fields: int) -> int:
    return encode(find(mnemonic, xlen), fields)


def counted(*words: int, turns: int = 0, **values: int) -> tuple[Statistics, Simulator]:
    """Run the words and count what happened; `turns` of them, or all of them."""
    machine = Machine(Options())
    for index, value in enumerate(words):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    for number, value in values.items():
        machine.x.write(int(number[1:]), value)
    simulator, statistics = Simulator(machine), Statistics()
    for _ in range(turns or len(words)):
        turn = simulator.step()
        if isinstance(turn, Stop):
            break
        statistics.saw(turn)
    return statistics, simulator


# ------------------------------------------------------------------ the counting


def test_what_a_short_run_was_made_of():
    statistics, _ = counted(
        word("addi", rd=5, rs1=0, imm=3),
        word("mul", rd=6, rs1=5, rs2=5),
        word("lw", rd=7, rs1=0, imm=0),  # x0 + 0 is no address, but it is a load
    )
    assert statistics.instructions == 2  # the load faulted
    assert statistics.kinds() == {"alu": 1, "multiply": 1}
    assert statistics.traps == 1 and statistics.turns == 3


def test_every_kind_is_counted_as_its_own():
    statistics, _ = counted(
        word("add", rd=5, rs1=0, rs2=0),
        word("mul", rd=5, rs1=5, rs2=5),
        word("div", rd=5, rs1=5, rs2=5),
        word("csrrs", rd=5, rs1=0, csr=1),
        word("fence", pred=15, succ=15),
        word("fmv.w.x", rd=1, rs1=0),
    )
    assert statistics.kinds() == {"alu": 1, "multiply": 1, "divide": 1, "csr": 1,
                                 "fence": 1, "float": 1}
    assert statistics.instructions == 6


def test_a_store_and_a_load_are_counted():
    statistics, _ = counted(
        word("sw", rs1=5, rs2=0, imm=0),
        word("lw", rd=6, rs1=5, imm=0),
        x5=DATA,
    )
    assert statistics.kinds() == {"store": 1, "load": 1}
    assert statistics.categories()["Memory"] == 2


def test_the_branches_that_went_and_the_ones_that_did_not():
    statistics, _ = counted(
        word("beq", rs1=0, rs2=0, imm=8),  # taken: over the next word
        NOP,
        word("bne", rs1=0, rs2=0, imm=8),  # not taken
        NOP,
        turns=3,
    )
    assert (statistics.taken, statistics.not_taken) == (1, 1)
    assert statistics.kinds()["branch"] == 2


def test_a_word_that_is_no_instruction():
    statistics, _ = counted(0x11223344, turns=1)
    assert (statistics.unknown, statistics.instructions) == (1, 0)
    assert statistics.kinds() == {}


def test_a_faulting_instruction_is_a_turn_but_not_an_instruction():
    """And the turn that ends a run is no turn of the loop at all: it carries
    nothing out, so nothing is handed over to be counted."""
    statistics, simulator = counted(
        word("lw", rd=5, rs1=0, imm=1),  # misaligned: it faults
        NOP,
        turns=2,  # the second turn takes the trap, finds no handler and stops
    )
    assert (statistics.turns, statistics.traps, statistics.instructions) == (1, 1, 0)


# ------------------------------------------------------------- the five of RARS


def test_the_five_kinds_rars_counts_by():
    statistics, _ = counted(
        word("addi", rd=5, rs1=0, imm=1),
        word("mul", rd=6, rs1=5, rs2=5),  # RARS counts this as ALU as well
        word("jal", rd=1, imm=8),
        NOP,
        turns=3,
    )
    assert statistics.categories() == {"ALU": 2, "Jump": 1, "Branch": 0,
                                       "Memory": 0, "Other": 0}


def test_the_five_kinds_are_always_all_there():
    statistics, _ = counted(NOP)
    assert list(statistics.categories()) == ["ALU", "Jump", "Branch", "Memory", "Other"]
    assert sum(statistics.categories().values()) == 1


# ---------------------------------------------------------------- what it is not


def test_counting_changes_nothing_of_the_run():
    """INV-P: the analysis watches and never touches."""
    words = (word("addi", rd=5, rs1=0, imm=7), word("mul", rd=6, rs1=5, rs2=5),
             word("sw", rs1=7, rs2=6, imm=0))

    def state(count: bool) -> tuple:
        machine = Machine(Options())
        for index, value in enumerate(words):
            machine.memory.poke(TEXT + 4 * index, 4, value)
        machine.x.write(7, DATA)
        simulator, statistics = Simulator(machine), Statistics()
        for _ in range(3):
            turn = simulator.step()
            if count and not isinstance(turn, Stop):
                statistics.saw(turn)
        return (tuple(machine.x.values), machine.x.pc, simulator.count,
                machine.memory.peek(DATA, 4), machine.csr.values["instret"])

    assert state(True) == state(False)


def test_a_counter_of_nothing():
    statistics = Statistics()
    assert (statistics.turns, statistics.instructions) == (0, 0)
    assert statistics.kinds() == {}
    assert statistics.categories() == {"ALU": 0, "Jump": 0, "Branch": 0,
                                       "Memory": 0, "Other": 0}


def test_the_kinds_nobody_met_are_left_out():
    statistics, _ = counted(NOP)
    assert set(statistics.kinds()) == {"alu"}
    assert Kind.FLOAT not in statistics.by_kind
