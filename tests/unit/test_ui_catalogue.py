"""The catalogue the reference window reads from.

What is in it and what order it is in are rules about the tables of the assembler,
so they are tested here; that a window can show them is tested in `tests/ui/`.
"""

import pytest

from pyrars.isa.instructions import instructions
from pyrars.ui.help import (
    CONTROL, DIRECTIVE, FLOAT, INSTRUCTION, PSEUDO, REGISTER, about, catalogue,
    every_word, matches)


@pytest.fixture
def whole():
    return catalogue(32)


def words_of(whole, kind: str) -> list[str]:
    return [one.word for one in whole if one.kind == kind]


def test_everything_that_can_be_told_of_is_in_it(whole):
    assert {one.word for one in whole} == every_word(32)


def test_nothing_in_it_is_a_word_nothing_is_known_about(whole):
    assert all(about(one.word, 32) is not None for one in whole)


def test_the_instructions_come_first(whole):
    """It is read by somebody who wants to know what to write, and an instruction
    is what a line of a program is made of."""
    assert whole[0].kind == INSTRUCTION
    kinds = [one.kind for one in whole]
    assert kinds.index(INSTRUCTION) < kinds.index(PSEUDO) < kinds.index(DIRECTIVE)
    assert kinds.index(DIRECTIVE) < kinds.index(REGISTER)
    # and each kind is together, not scattered through the list
    for kind in (INSTRUCTION, PSEUDO, DIRECTIVE, REGISTER, FLOAT, CONTROL):
        places = [index for index, one in enumerate(kinds) if one == kind]
        assert places == list(range(places[0], places[-1] + 1)), kind


def test_the_instructions_are_in_the_order_of_the_alphabet(whole):
    held = words_of(whole, INSTRUCTION)
    assert held == sorted(held)
    assert held == sorted(one.mnemonic for one in instructions(32))


def test_the_registers_are_in_the_order_the_machine_numbers_them(whole):
    """A list where x10 came between x1 and x2 would be nobody's reference, and one
    where `t0` stood under `a0` rather than beside `x5` would be worse."""
    held = words_of(whole, REGISTER)
    assert held[:6] == ["x0", "zero", "x1", "ra", "x2", "sp"]
    assert held.index("x10") > held.index("x9")
    assert held.index("t0") == held.index("x5") + 1
    assert words_of(whole, FLOAT)[:4] == ["f0", "ft0", "f1", "ft1"]


def test_a_word_answers_to_itself():
    assert matches(about("addi"), "addi")
    assert matches(about("addi"), "ADD")  # whatever the case
    assert not matches(about("addi"), "sub")


def test_a_word_answers_to_what_is_said_about_it():
    """Somebody looking for "shift" does not know the mnemonic yet, which is why
    they are looking."""
    assert matches(about("slli"), "shift")
    assert matches(about("fcsr"), "control")


def test_a_word_answers_to_the_operands_it_takes():
    assert matches(about("add"), "rs2")
    assert not matches(about("addi"), "rs2")  # it has no second source


def test_a_pseudo_instruction_answers_to_what_it_turns_into():
    assert matches(about("li"), "lui")
    assert matches(about("la"), "auipc")


def test_everything_answers_to_nothing_at_all(whole):
    assert all(matches(one, "") for one in whole)
    assert all(matches(one, "   ") for one in whole)


def test_the_catalogue_of_a_wider_machine():
    narrow = {one.word for one in catalogue(32)}
    wide = {one.word for one in catalogue(64)}
    assert narrow < wide
    assert "addiw" in wide and "addiw" not in narrow


# ------------------------------------------------- what the window opens with


def test_files_named_on_the_line_are_only_open(tmp_path):
    """Files NAMED when the window is started are files to work on, not a program
    in several pieces: a program of several files is a project, and saying so is
    what `--project` and the project window are for."""
    import argparse

    from pyrars.ui.__main__ import _opened

    project, files = _opened(argparse.Namespace(project=None,
                                                files=["a.s", "b.s"]))
    assert project is None
    assert files == ("a.s", "b.s")


def test_a_project_named_on_the_line_is_opened_with_its_own_files(tmp_path):
    import argparse
    import json

    from pyrars.ui.__main__ import _opened

    (tmp_path / "main.s").write_text(".text\nnop\n")
    path = tmp_path / "thing.pyrars.json"
    path.write_text(json.dumps({"files": ["main.s"]}))
    project, files = _opened(argparse.Namespace(project=str(path), files=[]))
    assert project is not None
    assert files == (str(tmp_path / "main.s"),)


def test_a_project_and_files_together_are_refused():
    import argparse

    from pyrars.ui.__main__ import _opened

    with pytest.raises(ValueError, match="cannot be named as well"):
        _opened(argparse.Namespace(project="p.json", files=["a.s"]))
