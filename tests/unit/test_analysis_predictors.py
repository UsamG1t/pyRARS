"""How a machine guesses where a branch will go.

Expected values are worked out by hand from the counter of the textbooks: a
counter of `bits` bits per entry, taken while it is in its upper half, moved one
step towards what happened and no further. One bit is therefore "expect what
happened last time", and two make a wrong guess happen twice in a row before the
expectation turns round. The entry of a branch is `(address >> 2) % entries`,
because the two low bits of the address of an instruction are always zero.

RARS keeps a history of outcomes instead and turns its expectation round only when
every one of them disagrees (DEV-61); at one bit the two rules are the same, which
is why its own default is one.
"""

import pytest

from pyrars.analysis.pipeline import Pipeline, Settings
from pyrars.analysis.predictors import History, Static
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop
from pyrars.isa.codec import encode
from pyrars.isa.instructions import find
from pyrars.isa.memory import DEFAULT

TEXT = DEFAULT.text_base
BRANCH = 0x00400100  # some branch, far enough from the others to pick its own entry


def word(mnemonic: str, **fields: int) -> int:
    return encode(find(mnemonic, 32), fields)


def asked(guesser, pc: int, *outcomes: bool) -> str:
    """What the guesser said about a branch that then did these things."""
    said = ""
    for went in outcomes:
        said += "t" if guesser.guess(pc) else "n"
        guesser.told(pc, went)
    return said


# ------------------------------------------------------------- the simple guesser


def test_a_machine_that_never_expects_a_branch_to_be_taken():
    guesser = Static()
    assert guesser.name == "never taken"
    assert asked(guesser, BRANCH, True, False, True, False) == "nnnn"
    assert (guesser.right, guesser.wrong) == (2, 2)
    assert guesser.accuracy == 0.5


def test_a_machine_that_always_expects_one():
    guesser = Static(taken=True)
    assert guesser.name == "always taken"
    assert asked(guesser, BRANCH, True, True, True, False) == "tttt"
    assert (guesser.right, guesser.wrong) == (3, 1)


def test_a_guesser_that_was_asked_nothing():
    assert Static().accuracy == 0.0
    assert History().accuracy == 0.0


# -------------------------------------------------------------------- the table


@pytest.mark.parametrize("pc, entries, where", [
    (0x00400000, 16, 0),
    (0x00400004, 16, 1),  # the next instruction falls into the next entry
    (0x0040003C, 16, 15),
    (0x00400040, 16, 0),  # and the seventeenth word comes round again
    (0x00400004, 4, 1),
    (0x00400014, 4, 1),  # four entries: every fourth word shares one
])
def test_which_entry_a_branch_falls_into(pc, entries, where):
    assert History(entries=entries).at(pc) == where


def test_one_bit_expects_what_happened_last_time():
    guesser = History(entries=4, bits=1)
    # not taken at first, then what happened last time: right once of the four
    assert asked(guesser, BRANCH, True, True, False, True) == "nttn"
    assert (guesser.right, guesser.wrong) == (1, 3)


def test_two_bits_turn_round_only_after_two_wrong_guesses():
    guesser = History(entries=4, bits=2)
    # not taken, not taken (though the first was wrong), then taken for good
    assert asked(guesser, BRANCH, True, True, True, False, False, True) == "nntttn"
    assert (guesser.right, guesser.wrong) == (1, 5)


def test_a_table_can_start_expecting_every_branch_to_be_taken():
    guesser = History(entries=4, bits=2, taken=True)
    assert asked(guesser, BRANCH, True, True) == "tt"
    assert guesser.wrong == 0


def test_a_counter_goes_no_further_than_its_ends():
    guesser = History(entries=1, bits=2)
    asked(guesser, BRANCH, *([True] * 6))
    assert guesser.table[0].counter == 3  # the highest a counter of two bits holds
    asked(guesser, BRANCH, *([False] * 6))
    assert guesser.table[0].counter == 0


def test_two_branches_of_their_own_entries_do_not_disturb_each_other():
    guesser = History(entries=16, bits=1)
    first, second = 0x00400000, 0x00400004
    asked(guesser, first, True, True)  # the first entry learns "taken"
    assert asked(guesser, second, False) == "n"  # the second knows nothing of it
    assert asked(guesser, first, True) == "t"


def test_two_branches_of_one_entry_fight_over_it():
    """Which is what a table too small for a program does."""
    guesser = History(entries=1, bits=1)
    assert asked(guesser, 0x00400000, True) == "n"
    assert asked(guesser, 0x00400100, False) == "t"  # the other branch taught it
    assert asked(guesser, 0x00400000, True) == "n"


def test_every_entry_says_how_it_has_done():
    guesser = History(entries=2, bits=1)
    asked(guesser, 0x00400000, True, True, True)  # one wrong, then two right
    entry = guesser.table[0]
    assert (entry.right, entry.wrong) == (2, 1)
    assert guesser.table[1].right == 0


def test_a_table_can_be_emptied():
    guesser = History(entries=2, bits=2)
    asked(guesser, BRANCH, True, True, True)
    guesser.reset()
    assert (guesser.guesses, guesser.right) == (0, 0)
    assert [entry.counter for entry in guesser.table] == [0, 0]
    assert asked(guesser, BRANCH, True) == "n"  # it knows nothing again


def test_the_name_of_a_table_says_how_it_is_built():
    assert History(entries=8, bits=2).name == "a table of 8 entries of 2 bits"


@pytest.mark.parametrize("options, says", [
    ({"entries": 0}, "at least one entry"),
    ({"bits": 0}, "at least one bit"),
])
def test_a_table_that_is_no_table(options, says):
    with pytest.raises(ValueError, match=says):
        History(**options)


def test_the_defaults_of_a_table():
    """Sixteen entries of one bit, expecting no branch to be taken - the numbers
    RARS starts its own table with, and at one bit its rule is ours."""
    guesser = History()
    assert (guesser.entries, guesser.bits) == (16, 1)
    assert guesser.guess(BRANCH) is False


# --------------------------------------------------------- with a pipeline round it


LOOP = (word("addi", rd=5, rs1=0, imm=4),  # four times round
        word("addi", rd=5, rs1=5, imm=-1),
        word("bne", rs1=5, rs2=0, imm=-4),
        word("addi", rd=6, rs1=0, imm=1))


def looped(predictor) -> Pipeline:
    machine = Machine(Options())
    for index, value in enumerate(LOOP):
        machine.memory.poke(TEXT + 4 * index, 4, value)
    pipeline, simulator = Pipeline(Settings(), predictor), Simulator(machine)
    for _ in range(12):
        turn = simulator.step()
        if isinstance(turn, Stop):
            break
        pipeline.saw(turn)
    return pipeline


@pytest.mark.parametrize("predictor, wrong, cycles", [
    # the branch of the loop is taken three times and not taken once
    (Static(), 3, 23),  # every taken one is a surprise
    (Static(taken=True), 1, 17),  # only the end of the loop is
    (History(bits=1), 2, 20),  # the first taken one, and then the end
    (History(bits=2), 3, 23),  # two bits need two surprises to learn: worse here
])
def test_how_a_loop_fares_under_each_guesser(predictor, wrong, cycles):
    pipeline = looped(predictor)
    assert pipeline.branches == 4
    assert pipeline.mispredictions == wrong
    assert pipeline.cycles == cycles


def test_a_pipeline_without_a_guesser_expects_no_branch_to_be_taken():
    assert isinstance(Pipeline().predictor, Static)
    assert Pipeline().predictor.taken is False


def test_emptying_a_pipeline_empties_its_guesser():
    pipeline = looped(History(bits=1))
    assert pipeline.predictor.guesses == 4
    pipeline.reset()
    assert pipeline.predictor.guesses == 0
