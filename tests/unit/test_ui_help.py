"""What one word of a program is, told from the tables that assemble it.

Nothing here is prose written by hand: every line of it is made of what the
instruction, the directive or the register already says about itself, so there is
no second description to go stale.
"""

import pytest

from pyrars.asm import pseudo
from pyrars.isa.instructions import instructions
from pyrars.ui.help import (
    CONTROL, DIRECTIVE, FLOAT, INSTRUCTION, PSEUDO, REGISTER, about, every_word)


def test_a_basic_instruction_says_how_it_is_written():
    one = about("addi")
    assert one.kind == INSTRUCTION
    assert one.forms == ("addi rd, rs1, imm",)
    assert "I extension" in one.about and "I format" in one.about


def test_an_instruction_of_one_width_says_so():
    assert "64-bit machines only" in about("addiw", 64).about
    assert about("addiw", 32) is None  # and on a narrow machine it is nothing


def test_a_pseudo_instruction_says_what_it_turns_into():
    one = about("li")
    assert one.kind == PSEUDO
    assert one.forms == ("li rd, imm12", "li rd, imm32")
    assert one.becomes == ("addi", "lui + addi")


def test_a_pseudo_instruction_of_one_form():
    one = about("la")
    assert one.forms == ("la rd, symbol",)
    assert one.becomes == ("auipc + addi",)


def test_another_name_for_an_instruction_says_that_is_what_it_is():
    """Some rows of the table are a second name and nothing more; somebody looking
    one up is better told so than told it is written out."""
    names = [one for one in pseudo.TABLE if one.alias]
    assert names, "the table has rows that are aliases"
    one = about(names[0].mnemonic)
    assert one.about == "Another name of an instruction"


def test_a_directive_says_where_it_comes_from():
    assert about(".asciz").kind == DIRECTIVE
    assert about(".asciz").about == "A directive of the RARS dialect"
    assert about(".p2align").about == "A directive of the assembly manual"


def test_a_register_says_its_other_names():
    assert about("t0").kind == REGISTER
    assert about("t0").about.endswith("also written x5")
    assert about("x5").about.endswith("also written t0")
    assert "x8, s0" in about("fp").about  # the one alias of the dialect
    assert about("zero").about.endswith("also written x0")


def test_a_register_is_as_wide_as_the_machine():
    assert "32 bits wide" in about("t0", 32).about
    assert "64 bits wide" in about("t0", 64).about


def test_a_floating_point_register_is_always_sixty_four_bits():
    one = about("ft1", 32)
    assert one.kind == FLOAT
    assert "64 bits wide" in one.about
    assert one.about.endswith("also written f1")


def test_a_control_register_says_its_number():
    one = about("fcsr")
    assert one.kind == CONTROL
    assert one.about.endswith("number 0x003")


def test_a_word_of_the_program_itself_is_nothing_we_know():
    assert about("loop") is None
    assert about("table") is None
    assert about("") is None
    assert about("   ") is None


def test_the_case_of_the_word_does_not_matter():
    assert about("ADDI").kind == INSTRUCTION
    assert about("T0").kind == REGISTER
    # and it is told of under the name the tables give it, not the one it was typed
    # under: what is being looked up is the instruction, not the typing
    assert about("ADDI").word == "addi"


def test_an_instruction_is_looked_at_before_anything_else():
    """No word is two things at once today, and if one ever were, an instruction is
    what somebody writing a program means by it."""
    for one in instructions(64):
        found = about(one.mnemonic, 64)
        assert found.kind == INSTRUCTION, one.mnemonic


def test_every_word_the_editor_offers_can_be_told_of(tmp_path):
    """The two go together: a word offered for completion that nothing could be
    said about would be a word from nowhere."""
    for word in every_word(32):
        assert about(word, 32) is not None, word
