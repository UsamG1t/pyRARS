"""What each word of the language DOES, in one line.

This is the one table of the project that is not made of another table: what an
instruction is FOR cannot be read out of its encoding. So it is held to the tables
beside it instead - everything the assembler takes must have a line here, and
nothing here may be a word nobody has.
"""

import pytest

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.instructions import instructions
from pyrars.isa.registers import CSRS
from pyrars.ui.help import about
from pyrars.ui.meanings import (
    OF_CONTROL, OF_DIRECTIVES, OF_FLOATS, OF_INSTRUCTIONS, OF_PSEUDO, OF_REGISTERS,
    missing)


def test_everything_the_assembler_takes_says_what_it_does():
    """The day somebody adds an instruction, this is what says it owes a line."""
    assert missing() == {"instructions": (), "pseudo-instructions": (),
                         "directives": (), "registers": (),
                         "floating point registers": (), "control registers": (),
                         "settings of a run": ()}


def test_everything_that_can_be_settled_about_a_run_says_what_it_means():
    """The settings are held to the models the same way: what CAN be set is read
    off the models and the devices themselves, so an option added to one is owed a
    line here that day."""
    from pyrars.devices import DEVICES
    from pyrars.session.settings import options_of
    from pyrars.ui.meanings import OF_SETTINGS, of_a_setting

    for what in ("cache", "pipeline", "guesser", *DEVICES):
        assert of_a_setting(what), what
        for one in options_of(what):
            assert of_a_setting(f"{what}.{one.name}"), f"{what}.{one.name}"
    for name in ("statistics", "fetches", "instructions"):
        assert of_a_setting(name), name
    # and nothing here is a setting nobody has
    for name in OF_SETTINGS:
        what, _, option = name.partition(".")
        assert what in ("statistics", "fetches", "instructions", "cache",
                        "pipeline", "guesser", *DEVICES), name
        if option:
            assert option in [one.name for one in options_of(what)], name


def test_what_is_said_of_a_setting_is_a_line_like_any_other():
    from pyrars.ui.meanings import OF_SETTINGS

    for name, said in OF_SETTINGS.items():
        assert said[0].isupper() or said.startswith("A "), (name, said)
        assert not said.endswith("."), name
        assert "\n" not in said, name
        assert len(said) < 230, (name, len(said))


def test_nothing_here_is_a_word_nobody_has():
    """A line about an instruction that does not exist is a line nobody will ever
    read, and a sign that a name was got wrong."""
    assert set(OF_INSTRUCTIONS) == {one.mnemonic for one in instructions(64)}
    assert set(OF_PSEUDO) == set(pseudo.mnemonics(64))
    assert set(OF_DIRECTIVES) == set(DIRECTIVES)
    assert set(OF_CONTROL) == set(CSRS)
    assert set(OF_REGISTERS) == set(range(32))
    assert set(OF_FLOATS) == set(range(32))


def test_every_line_is_a_line_and_not_a_paragraph():
    """It is read beside the word, in a row of a list: one line, no full stop at
    the end, and a capital to begin, as everything else this project writes."""
    for table in (OF_INSTRUCTIONS, OF_PSEUDO, OF_DIRECTIVES, OF_CONTROL):
        for word, said in table.items():
            assert said[0].isupper() or said[0] in "123", (word, said)
            assert not said.endswith("."), (word, said)
            assert "\n" not in said, word
            assert len(said) < 180, (word, len(said))


@pytest.mark.parametrize("word, expected", [
    ("add", "Adds rs1 and rs2 and puts the sum in rd"),
    ("lw", "Reads a word from memory and puts it in rd"),
    ("sb", "Writes the low byte of rs2 to memory"),
    ("beq", "Goes to the label when rs1 and rs2 are equal"),
    ("ecall", "Asks the system for something; a7 says what, and a0 onwards are what "
              "it is given"),
])
def test_what_some_of_them_say(word, expected):
    assert OF_INSTRUCTIONS[word] == expected


def test_the_wide_instructions_say_what_they_do_differently():
    """A 64-bit machine has a second form of the arithmetic that works on the low
    half; the difference is the whole of what somebody wants to know about it."""
    assert OF_INSTRUCTIONS["addw"].startswith(OF_INSTRUCTIONS["add"])
    assert "low 32 bits" in OF_INSTRUCTIONS["addw"]
    assert "sign of the result" in OF_INSTRUCTIONS["addiw"]


def test_the_floating_point_family_is_made_and_not_written_out():
    """Sixty of them, exactly regular: the same operation in two precisions, and a
    conversion between every pair of formats. Written out by hand they would be
    sixty chances to get one wrong."""
    assert OF_INSTRUCTIONS["fadd.s"].endswith("in single precision")
    assert OF_INSTRUCTIONS["fadd.d"].endswith("in double precision")
    assert OF_INSTRUCTIONS["fadd.s"][:-len("single precision")] == (
        OF_INSTRUCTIONS["fadd.d"][:-len("double precision")])
    assert OF_INSTRUCTIONS["fcvt.d.w"] == (
        "Turns a 32-bit signed number in rs1 into a double precision number in rd")
    assert OF_INSTRUCTIONS["fcvt.w.d"] == (
        "Turns a double precision number in rs1 into a 32-bit signed number in rd")


def test_a_register_says_what_the_convention_asks_of_it():
    """Which is what a program of somebody else's takes for granted."""
    assert OF_REGISTERS[0].startswith("Always zero")
    assert OF_REGISTERS[1] == "Where a call leaves the way back"
    assert OF_REGISTERS[2] == "The stack pointer"
    assert "Kept across a call" in OF_REGISTERS[8]
    assert OF_REGISTERS[10].startswith("An argument to a call, and where it leaves")
    assert OF_FLOATS[10] == OF_REGISTERS[10]  # the same convention, the same words


def test_what_a_word_is_carries_its_meaning():
    """The reference and the tooltip both read it from here."""
    assert about("add").means == OF_INSTRUCTIONS["add"]
    assert about("li").means == OF_PSEUDO["li"]
    assert about(".word").means == OF_DIRECTIVES[".word"]
    assert about("sp").means == OF_REGISTERS[2]
    assert about("ft1").means == OF_FLOATS[1]
    assert about("fcsr").means == OF_CONTROL["fcsr"]


def test_a_word_is_found_by_what_it_does():
    """Somebody looking for "square root" does not know it is called fsqrt - which
    is exactly why they are looking."""
    from pyrars.ui.help import catalogue, matches

    whole = catalogue(64)
    assert [one.word for one in whole if matches(one, "square root")] == [
        "fsqrt.d", "fsqrt.s"]
    assert "sp" in [one.word for one in whole if matches(one, "stack pointer")]
    assert "beqz" in [one.word for one in whole if matches(one, "when rs is zero")]
