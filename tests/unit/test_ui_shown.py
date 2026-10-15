"""What the window writes, worked out where no widget can be seen."""

from pyrars.ui.shown import CHANGED, UNTITLED, tab_about, tab_title, window_title


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
