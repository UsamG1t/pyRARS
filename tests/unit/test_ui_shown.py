"""What the window writes, worked out where no widget can be seen."""

from pyrars.isa.program import Diagnostic, SourceLoc
from pyrars.ui.shown import (
    CHANGED, ERROR, UNTITLED, WARNING, Problem, problems, said, tab_about, tab_title,
    window_title)


def test_a_tab_says_the_name_of_its_file():
    assert tab_title("/home/someone/programs/sum.s") == "sum.s"


def test_a_tab_says_that_a_file_has_been_changed():
    assert tab_title("/home/someone/sum.s", modified=True) == f"sum.s {CHANGED}"


def test_a_file_that_has_never_been_saved():
    assert tab_title(None) == UNTITLED
    assert tab_title(None, modified=True) == f"{UNTITLED} {CHANGED}"
    assert tab_about(None) == "not saved anywhere yet"


def test_a_tab_says_where_its_file_really_is(tmp_path):
    (tmp_path / "sum.s").write_text("")
    assert tab_about(str(tmp_path / "deeper" / ".." / "sum.s")) == str(
        tmp_path / "sum.s")


def test_the_window_says_what_is_being_worked_on():
    assert window_title("/home/someone/sum.s") == "sum.s - pyRARS"
    assert window_title("/home/someone/sum.s", True) == f"sum.s {CHANGED} - pyRARS"
    assert window_title(None) == f"{UNTITLED} - pyRARS"


# ------------------------------------------- what the assembler had to say


def diagnostic(kind: str, file: str | None, line: int, message: str) -> Diagnostic:
    return Diagnostic(kind, SourceLoc(file, line, 1) if file else None, message)


def test_what_was_said_is_sorted_by_the_file_it_was_said_about():
    by_file, loose = problems([
        diagnostic("Error", "main.s", 3, "nothing of the kind"),
        diagnostic("Warning", "lib.s", 7, "it might be meant"),
        diagnostic("Error", "main.s", 9, "nor that"),
    ])
    assert loose == ()
    assert by_file["main.s"] == (Problem(3, ERROR, "nothing of the kind"),
                                 Problem(9, ERROR, "nor that"))
    assert by_file["lib.s"] == (Problem(7, WARNING, "it might be meant"),)


def test_what_was_said_about_no_place_at_all():
    """It belongs to no line and cannot be marked in the margin of anything, so it
    comes back on its own for a window to say somewhere a person will see it."""
    by_file, loose = problems([diagnostic("Error", None, 0, "the whole thing is wrong")])
    assert by_file == {}
    assert loose == ("the whole thing is wrong",)


def test_nothing_was_said_at_all():
    assert problems(()) == ({}, ())


def test_what_the_margin_of_a_line_says():
    assert said([Problem(3, ERROR, "nothing of the kind"),
                 Problem(3, WARNING, "and this too")]) == (
        "error: nothing of the kind\nwarning: and this too")
