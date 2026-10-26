"""What the editor offers while a line is being typed.

Which words are offered is a rule about WHERE in a line the typing is, so it is
tested here and the widget only shows what it answers.
"""

import pytest

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.instructions import mnemonics
from pyrars.ui.completions import beginning, registers, typing, words


def test_the_word_being_typed():
    assert typing("        addi t0, t") == "t"
    assert typing("        .asc") == ".asc"
    assert typing("loop:") == ""
    assert typing("") == ""


def test_where_the_first_word_of_a_line_is():
    assert beginning("        ad") is True
    assert beginning("ad") is True
    assert beginning("loop:   ad") is True  # a label is not a word of the program
    assert beginning("3:  ad") is True  # nor is a local one
    assert beginning("        addi t") is False


def test_an_instruction_is_offered_where_an_instruction_goes():
    assert words("        ad") == ("add", "addi")
    assert "addi" in words("loop:   add")
    assert set(words("        a")) <= mnemonics(32) | pseudo.mnemonics(32)


def test_a_pseudo_instruction_is_offered_like_any_other():
    assert "li" in words("        l")
    assert "la" in words("        l")


def test_a_directive_is_offered_after_a_stop():
    assert words("        .as") == (".ascii", ".asciz")
    assert set(words("        .")) == set(DIRECTIVES)


def test_what_a_program_named_comes_first_among_the_operands():
    """A name of the program is what somebody is most likely to be typing in the
    place of an operand, so it is offered before the registers."""
    offered = words("        la t0, t", labels=("table", "total"))
    assert offered[:2] == ("table", "total")
    assert "t0" in offered


def test_a_register_is_offered_where_an_operand_goes():
    assert "t0" in words("        addi t")
    assert "ft1" in words("        fadd.s f", labels=())
    assert set(words("        addi ")) == set()  # nothing until something is typed


def test_a_control_register_is_offered_too():
    assert words("        csrr t0, fc") == ("fcsr",)


def test_an_instruction_is_not_offered_in_the_place_of_an_operand():
    assert "addi" not in words("        addi a")


def test_nothing_is_offered_inside_a_comment():
    """The words have to be ones that WOULD be offered outside a comment, or the
    test would pass whether a comment was noticed or not."""
    assert words("        addi t0, t1, 1  # and t") == ()  # not t0, t1, ...
    assert words("# li a") == ()  # not a0, a1, ...
    assert words("loop:  # ad") == ()  # not add, addi


def test_the_word_that_is_already_written_is_not_offered():
    """There is nothing to complete about a word that is complete."""
    assert "add" not in words("        add")
    assert "addi" in words("        add")


def test_the_case_of_what_is_typed_does_not_matter():
    """The assembler reads a mnemonic whatever its case, so the editor offers it."""
    assert "addi" in words("        AD")
    assert "add" in words("        A")
    assert ".ascii" in words("        .AS")


def test_every_name_a_register_answers_to_can_be_typed():
    held = set(registers())
    assert {"x0", "x31", "zero", "sp", "fp", "f0", "ft1"} <= held
    assert "x32" not in held
