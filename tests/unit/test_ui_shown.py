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


def test_what_the_program_is_called_in_the_title():
    from pyrars.ui.shown import project_called

    # one kept in a file is called by that file
    assert project_called("/home/someone/thing.pyrars.json", 3) == "thing.pyrars.json"
    # one made in the window is called by what it holds, which is all there is
    assert project_called("", 3) == "a project of 3 files"
    # and one of a single file is called nothing: it does to the program exactly
    # what no project does, and a title saying so twice says nothing
    assert project_called("", 1) == ""
    assert project_called("", 0) == ""


def test_the_window_says_what_is_being_worked_on():
    assert window_title("/home/someone/sum.s") == "sum.s - pyRARS"
    assert window_title("/home/someone/sum.s", False, "thing.pyrars.json") == (
        "sum.s - thing.pyrars.json - pyRARS")
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


# ------------------------------------------------- the views of the machine

from pyrars.session.control import Snapshot  # noqa: E402
from pyrars.session.debug import (  # noqa: E402
    FrameSeen, Item, Place, Stopped, Symbol, Value)
from pyrars.isa.program import TextEntry  # noqa: E402
from pyrars.ui.shown import (  # noqa: E402
    BREAK, HERE, control, data, floats, frames, labels, registers, standing, text)


def test_which_cell_goes_in_which_column():
    from pyrars.ui.shown import cell

    assert cell(("a", "b", "c"), 1) == "b"
    # a row may be shorter than the table is wide, and a column shows something
    # either way: a place with no source line, a frame with no name
    assert cell(("a",), 2) == ""
    assert cell((), 0) == ""


def test_the_registers_as_rows():
    assert registers([Value("t0", 5, 0x1234, 32), Value("zero", 0, 0, 32)]) == (
        ("t0", "x5", "0x00001234"), ("zero", "x0", "0x00000000"))


def test_the_registers_in_the_format_chosen():
    assert registers([Value("t0", 5, 0xFFFFFFFF, 32)], "dec")[0][2] == "-1"
    assert registers([Value("t0", 5, 0x41424344, 32)], "ascii")[0][2] == "  A  B  C  D"


def test_a_register_of_a_wider_machine_shows_every_digit():
    assert registers([Value("t0", 5, 1, 64)])[0][2] == "0x0000000000000001"


def test_the_floating_point_registers_show_their_bits_as_bits():
    """A float read as a signed number says nothing to anybody, so the bits are
    bits whatever format was chosen for the rest."""
    value = Value("ft1", 1, 0x3FF0000000000000, 64, "1.0", "f")
    assert floats([value], "dec") == (
        ("ft1", "f1", "0x3ff0000000000000", "1.0"),)


def test_the_control_registers_spell_out_what_they_hold():
    """Which is what the "flags" of another machine would be (the entry of M8)."""
    value = Value("fcsr", 3, 0x8, 32, "flags 0x08, rounding 0", "csr")
    assert control([value]) == (
        ("fcsr", "0x003", "0x00000008", "flags 0x08, rounding 0"),)


def entry(address: int, basic: str, source: str) -> TextEntry:
    return TextEntry(address, 0x13, basic, None, source)


def test_the_text_segment_as_rows():
    assert text([entry(0x400000, "addi x5,x0,3", "main:   li t0, 3")]) == (
        ("", "0x00400000", "0x00000013", "addi x5,x0,3", "main:   li t0, 3"),)


def test_the_text_segment_marks_where_the_machine_stands():
    rows = text([entry(0x400000, "a", "a"), entry(0x400004, "b", "b")],
                here=0x400004)
    assert [row[0] for row in rows] == ["", HERE]


def test_the_text_segment_marks_what_the_run_stops_before():
    rows = text([entry(0x400000, "a", "a"), entry(0x400004, "b", "b")],
                breaks={0x400000})
    assert [row[0] for row in rows] == [BREAK, ""]


def test_a_place_that_is_both_is_marked_as_both():
    rows = text([entry(0x400000, "a", "a")], here=0x400000, breaks={0x400000})
    assert rows[0][0] == BREAK + HERE


def test_the_data_segment_as_the_directives_wrote_it():
    items = [Item(0x10010000, ".word", 4, (3,)),
             Item(0x10010004, ".asciz", 3, (0x6968,), "hi")]
    assert data(items) == (
        ("0x10010000", ".word", "4", "0x00000003", ""),
        # three bytes are shown as three bytes, not padded out to a word
        ("0x10010004", ".asciz", "3", "0x006968", "hi"))


def test_the_data_segment_in_the_format_chosen():
    assert data([Item(0x10010000, ".word", 4, (65,))], "dec")[0][3] == "65"


def test_a_thing_of_several_words():
    assert data([Item(0x10010000, ".space", 8, (1, 2))])[0][3] == (
        "0x00000001 0x00000002")


def test_the_labels_say_how_far_they_reach():
    assert labels([Symbol("main", 0x400000, True), Symbol("loop", 0x400010, False)]) == (
        ("main", "0x00400000", "global"), ("loop", "0x00400010", "local"))


def place(address: int, symbol: str = "") -> Place:
    return Place(address, symbol=symbol)


def test_the_frames_of_the_calls_the_run_is_inside():
    assert frames([FrameSeen(1, place(0x400034, "keep"), place(0x400024), 0x7FFFEFFC)]) == (
        ("1", "0x00400034 <keep>", "0x00400024", "0x7fffeffc"),)


def test_a_frame_whose_stack_pointer_nobody_saw():
    assert frames([FrameSeen(1, place(0x400034), place(0x400024), None)])[0][3] == "?"


def test_the_line_that_says_where_the_run_is():
    shot = Snapshot("standing", Place(0x400010, basic="lw x28,0(x5)"), 7, 7, 7,
                    Stopped("breakpoint", Place(0x400010)))
    assert standing(shot) == (
        "standing  |  0x00400010  |  lw x28,0(x5)  |  7 carried out  |  "
        "7 to take back  |  breakpoint")


def test_the_line_before_anything_is_open():
    assert standing(Snapshot("nothing")) == "nothing  |  0 carried out"
