"""The two windows that open from the main one: what the program is, and what can
be written in one.

What they hold is worked out without GTK (`ui/help.py`, `session/project.py`);
what is tried here is that a person can see it and change it.
"""

import json

import pytest

pytestmark = pytest.mark.ui

LIB = """\
        .globl  twice
        .text
twice:  add     a0, a0, a0
        ret
"""
USES = """\
        .globl  main
        .text
main:   li      a0, 21
        jal     ra, twice
        li      a7, 1
        ecall
        li      a7, 10
        ecall
"""


@pytest.fixture
def two_files(tmp_path):
    (tmp_path / "lib.s").write_text(LIB)
    (tmp_path / "uses.s").write_text(USES)
    return str(tmp_path / "lib.s"), str(tmp_path / "uses.s")


@pytest.fixture
def window(gtk, tmp_path, two_files):
    from pyrars.ui.window import Window

    made = Window(files=two_files, cache=str(tmp_path / "cache"))
    yield made
    made.close_up()


def shown(view) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


# ------------------------------------------------- what the program is made of


def test_one_file_is_the_program_until_somebody_says_otherwise(window, turning):
    """Several files open are several things somebody is working on, not one
    program in several pieces: assembling them together glued two programs end to
    end, which is nobody's idea of a default."""
    assert window.project is None
    window.editor.tabs.set_selected_page(
        window.editor.tabs.get_page(window.editor.pages[1]))  # uses.s
    window.do("assemble")
    assert turning(lambda: "assembling uses.s" in shown(window.messages))
    # it calls `twice`, which is in the other file and NOT part of the program
    assert turning(lambda: "has not been assembled" in shown(window.messages))


def test_a_project_makes_one_program_of_several_files(window, turning, two_files):
    asking = window.ask_what_the_program_is()
    try:
        for path in two_files:
            asking.chosen[path].set_active(True)
        asking.main_of[two_files[1]].set_active(True)  # uses.s first
        asking._use()
    finally:
        asking.destroy()
    assert window.project is not None
    assert window.project.ordered[0].endswith("uses.s")
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert len(window.program.text) == 8  # both files, one program
    window.do("continue")
    assert turning(lambda: shown(window.console) == "42")


def test_a_project_can_be_let_go_of_again(window, turning, two_files):
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking._use()
    asking.destroy()
    assert window.project is not None
    asking = window.ask_what_the_program_is()
    asking._let_go()
    asking.destroy()
    assert window.project is None
    assert "the file being looked at" in shown(window.messages)


def test_the_title_says_which_program_is_in_force(window, two_files):
    assert "project" not in window.get_title()
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking._use()
    asking.destroy()
    assert "a project of 2 files" in window.get_title()


def test_a_project_of_one_file_is_not_worth_saying_twice(window, two_files):
    """It does to the program exactly what no project does."""
    asking = window.ask_what_the_program_is()
    asking.chosen[two_files[0]].set_active(True)
    asking.chosen[two_files[1]].set_active(False)
    asking._use()
    asking.destroy()
    assert window.project is not None
    assert "project" not in window.get_title()


def test_a_project_with_no_file_ticked(window):
    asking = window.ask_what_the_program_is()
    try:
        for ticked in asking.chosen.values():
            ticked.set_active(False)
        assert asking.project_now() is None
        assert "Tick the files" in asking.says.get_text()
    finally:
        asking.destroy()


def test_a_project_written_to_a_file_and_read_back(window, tmp_path, two_files,
                                                   turning):
    from pyrars.session import project as projects

    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking.main_of[two_files[1]].set_active(True)
    where = str(tmp_path / "thing.pyrars.json")
    asking.where = where
    kept = asking.project_now().save(where)
    asking.destroy()
    held = json.loads((tmp_path / "thing.pyrars.json").read_text())
    assert held["files"] == ["lib.s", "uses.s"]
    assert held["main"] == "uses.s"
    assert projects.read(where) == kept


def test_a_project_of_a_wider_machine(window, two_files):
    asking = window.ask_what_the_program_is()
    try:
        asking.width.set_selected(1)  # 64
        asking.config.set_selected(1)
        asking.pseudo.set_active(False)
        made = asking.project_now()
        assert made.xlen == 64
        assert made.mem_config != "Default"
        assert made.pseudo is False
    finally:
        asking.destroy()


def test_a_project_may_name_a_file_nobody_has_opened(window, tmp_path, two_files):
    """A project is read from a file and names what it names; the window must offer
    those files whether anybody has opened them or not, or opening a project would
    quietly drop half of it."""
    from pyrars.session import project as projects

    elsewhere = tmp_path / "apart.s"
    elsewhere.write_text(".text\nnop\n")
    made = projects.of([str(elsewhere)], folder=str(tmp_path))
    window.the_program_is(made, "")
    asking = window.ask_what_the_program_is()
    try:
        assert str(elsewhere) in asking.files  # the one nobody opened
        assert all(path in asking.files for path in two_files)
        assert asking.chosen[str(elsewhere)].get_active()
    finally:
        asking.destroy()


def test_the_project_window_opens_with_what_is_already_settled(window, two_files):
    asking = window.ask_what_the_program_is()
    for path in two_files:
        asking.chosen[path].set_active(True)
    asking.width.set_selected(1)
    asking._use()
    asking.destroy()
    again = window.ask_what_the_program_is()
    try:
        assert all(again.chosen[path].get_active() for path in two_files)
        assert again.width.get_selected() == 1
    finally:
        again.destroy()


# ----------------------------------------------- what can be written in a program


def test_the_reference_holds_everything_the_assembler_takes(window):
    from pyrars.ui.help import every_word

    reading = window.open_the_reference()
    try:
        assert len(reading.rows) == len(every_word(32))
        assert reading.look_for("") == len(reading.rows)
    finally:
        reading.destroy()


def test_the_reference_is_looked_through(window):
    reading = window.open_the_reference()
    try:
        assert reading.look_for("addi") == 6
        # all six of them: the three that shift by a register and the three that
        # shift by a number. Their names say nothing about shifting; their
        # meanings do, and the search reads those too
        assert reading.look_for("shift") == 6
        assert reading.look_for("nonsense") == 0
        assert reading.shown.get_visible_child_name() == "nothing"
        reading.look_for("")
        assert reading.shown.get_visible_child_name() == "words"
    finally:
        reading.destroy()


def test_a_row_of_the_reference_says_what_the_word_does(window):
    """Three lines that must not run into one another: what KIND of word it is,
    what it DOES - which is what the looking was for - and how it is WRITTEN."""
    reading = window.open_the_reference()
    try:
        row = next(row for row, one in reading.rows.items() if one.word == "add")
        lines = _lines_of(row.get_child())
        assert lines[0][0] == "add"
        assert lines[1][0].startswith("A basic instruction")
        assert lines[2][0] == "Adds rs1 and rs2 and puts the sum in rd"
        assert lines[3][0] == "add rd, rs1, rs2"
        # and each of them is told apart from the one above it
        assert "dim-label" in lines[1][1]
        assert "accent" in lines[2][1]
        assert "monospace" in lines[3][1] and "accent" not in lines[3][1]
    finally:
        reading.destroy()


def test_a_word_is_found_by_what_it_does(window):
    reading = window.open_the_reference()
    try:
        assert reading.look_for("square root") == 2  # fsqrt in both precisions
        assert reading.look_for("stack pointer") >= 1
    finally:
        reading.destroy()


def _lines_of(box):
    """Every label of a row, with the css classes it carries."""
    found, child = [], box.get_first_child()
    while child is not None:
        found.append((child.get_text(), tuple(child.get_css_classes())))
        child = child.get_next_sibling()
    return found


def test_the_reference_follows_the_width_of_the_machine(window, two_files):
    asking = window.ask_what_the_program_is()
    asking.chosen[two_files[0]].set_active(True)
    asking.width.set_selected(1)  # 64
    asking._use()
    asking.destroy()
    reading = window.open_the_reference()
    try:
        # `addiw` itself, and the pseudo-instructions written out as one
        assert reading.look_for("addiw") >= 1
        assert any(one.word == "addiw" for one in reading.words)
    finally:
        reading.destroy()
