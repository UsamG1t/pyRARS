"""The editor: the files, what is done to them, and what the colouring really does.

That the definition holds the right words is tested without GTK in
`tests/unit/test_ui_highlighting.py`. What is tested here is that GtkSourceView
ACCEPTS it and paints with it, which nothing but GtkSourceView can say.
"""

import pytest

pytestmark = pytest.mark.ui

SUM = """\
.globl main
.data
msg:    .asciz "hi"
.text
main:   li t0, 3        # three of them
        ecall
"""


@pytest.fixture
def editor(gtk, tmp_path):
    from pyrars.ui.editor import Editor

    return Editor(str(tmp_path / "cache"))


@pytest.fixture
def file(tmp_path):
    path = tmp_path / "sum.s"
    path.write_text(SUM)
    return str(path)


def text_of(page) -> str:
    return page.text


# ------------------------------------------------------------- the colouring


def test_gtksourceview_takes_our_language(editor):
    from pyrars.ui.highlighting import ID

    assert editor.languages.get_language(ID) is not None
    assert editor.languages.get_language(ID).get_name() == "RISC-V (pyRARS)"


def test_what_the_editor_paints(editor, file):
    """A comment is a comment and a string is a string, which is the one thing only
    GtkSourceView itself can be asked."""
    page = editor.open(file).get_child()
    buffer = page.buffer
    buffer.ensure_highlight(buffer.get_start_iter(), buffer.get_end_iter())
    inside = SUM.index("three") + 2
    assert buffer.iter_has_context_class(buffer.get_iter_at_offset(inside), "comment")
    letter = SUM.index('"hi') + 1
    assert buffer.iter_has_context_class(buffer.get_iter_at_offset(letter), "string")
    plain = SUM.index("li t0")
    assert not buffer.iter_has_context_class(buffer.get_iter_at_offset(plain),
                                             "comment")


def test_the_language_is_written_out_where_it_can_be_found(gtk, tmp_path):
    from pyrars.ui.editor import languages
    from pyrars.ui.highlighting import language

    made = languages(str(tmp_path))
    written = tmp_path / "pyrars" / "pyrars.lang"
    assert written.read_text() == language()
    assert str(tmp_path / "pyrars") in made.get_search_path()


# ---------------------------------------------------------------- the files


def test_a_file_opened(editor, file):
    tab = editor.open(file)
    assert tab.get_title() == "sum.s"
    assert text_of(tab.get_child()) == SUM
    assert editor.paths == [file]
    assert editor.modified is False


def test_a_file_already_open_is_not_opened_twice(editor, file):
    first = editor.open(file)
    editor.add("", None)  # and something else in between
    assert editor.open(file) is first
    assert len(editor.pages) == 2
    assert editor.tabs.get_selected_page() is first


def test_a_file_that_was_changed_says_so(editor, file):
    from pyrars.ui.shown import CHANGED

    tab = editor.open(file)
    tab.get_child().buffer.insert_at_cursor("# and one more line\n")
    assert editor.modified is True
    assert tab.get_title() == f"sum.s {CHANGED}"


def test_a_file_saved(editor, file):
    tab = editor.open(file)
    page = tab.get_child()
    page.buffer.insert_at_cursor("# a new line\n")
    assert editor.save() == file
    assert "# a new line" in open(file).read()
    assert editor.modified is False
    assert tab.get_title() == "sum.s"


def test_a_file_that_has_never_been_saved(editor, tmp_path):
    from pyrars.ui.shown import UNTITLED

    tab = editor.add("li t0, 1\n")
    assert tab.get_title() == UNTITLED
    assert editor.paths == []  # there is nothing on the disk to assemble
    with pytest.raises(ValueError, match="name it first"):
        tab.get_child().save()
    where = str(tmp_path / "new.s")
    assert editor.save(where) == where
    assert open(where).read() == "li t0, 1\n"
    assert tab.get_title() == "new.s"


def test_a_file_is_saved_with_the_newline_its_last_line_needs(editor, tmp_path):
    where = str(tmp_path / "new.s")
    editor.add("ecall")
    editor.save(where)
    assert open(where).read() == "ecall\n"


def test_everything_that_changed_is_written_at_once(editor, tmp_path):
    for name in ("one.s", "two.s", "three.s"):
        (tmp_path / name).write_text("nop\n")
        editor.open(str(tmp_path / name))
    editor.pages[0].buffer.insert_at_cursor("# changed\n")
    editor.pages[2].buffer.insert_at_cursor("# changed\n")
    assert sorted(editor.save_every_change()) == sorted(
        [str(tmp_path / "one.s"), str(tmp_path / "three.s")])
    assert editor.modified is False
    assert "# changed" in (tmp_path / "one.s").read_text()
    assert "# changed" not in (tmp_path / "two.s").read_text()


def test_a_file_closed(editor, file):
    editor.open(file)
    editor.close()
    assert editor.pages == []
    assert editor.page is None


# --------------------------------------------------------- undoing and redoing


def test_what_was_typed_can_be_taken_back(editor, file):
    page = editor.open(file).get_child()
    page.buffer.insert_at_cursor("nop\n")
    assert page.buffer.get_can_undo() is True
    editor.undo()
    assert text_of(page) == SUM
    editor.redo()
    assert "nop" in text_of(page)


def test_opening_a_file_is_not_a_change_to_be_taken_back(editor, file):
    """The first Ctrl+Z after opening a file must not empty the window."""
    page = editor.open(file).get_child()
    assert page.buffer.get_can_undo() is False
    editor.undo()
    assert text_of(page) == SUM


# ------------------------------------------------------- finding and replacing


def test_a_word_is_found(editor, file):
    page = editor.open(file).get_child()
    editor.search.what.set_text("ecall")
    assert editor.search.next() is True
    start, end = page.buffer.get_selection_bounds()
    assert page.buffer.get_text(start, end, False) == "ecall"


def test_a_word_that_is_not_there(editor, file):
    editor.open(file)
    editor.search.what.set_text("nonsense")
    assert editor.search.next() is False


def test_a_word_replaced(editor, file):
    page = editor.open(file).get_child()
    editor.search.what.set_text("ecall")
    editor.search.instead.set_text("ebreak")
    assert editor.search.replace() is True
    assert "ebreak" in text_of(page)
    assert "ecall" not in text_of(page)


def test_every_one_of_them_replaced(editor, tmp_path):
    (tmp_path / "many.s").write_text("nop\nnop\nnop\n")
    page = editor.open(str(tmp_path / "many.s")).get_child()
    editor.search.what.set_text("nop")
    editor.search.instead.set_text("ecall")
    assert editor.search.replace_all() == 3
    assert text_of(page) == "ecall\necall\necall\n"


def test_the_search_follows_the_file_being_looked_at(editor, tmp_path):
    """A search that kept the file it began in would answer about a file nobody is
    looking at any more."""
    (tmp_path / "one.s").write_text("nop\nalpha\n")
    (tmp_path / "two.s").write_text("nop\nbeta\n")
    editor.open(str(tmp_path / "one.s"))
    editor.search.what.set_text("alpha")
    assert editor.search.next() is True
    editor.open(str(tmp_path / "two.s"))
    assert editor.search.next() is False  # "alpha" is not in this one
    editor.search.what.set_text("beta")
    assert editor.search.next() is True
    start, end = editor.page.buffer.get_selection_bounds()
    assert editor.page.buffer.get_text(start, end, False) == "beta"


def test_a_search_for_nothing_finds_nothing(editor, file):
    editor.open(file)
    editor.search.what.set_text("")
    assert editor.search.next() is False
    assert editor.search.replace_all() == 0


def test_the_search_asks_for_nothing_when_no_file_is_open(editor):
    editor.search.what.set_text("nop")
    assert editor.search.next() is False
    assert editor.search.replace() is False
    assert editor.search.replace_all() == 0


# ------------------------------------------------------------- the margin


def test_a_mark_in_the_margin_and_what_it_says(editor, file):
    page = editor.open(file).get_child()
    page.mark("error", 3, "nothing of the kind")
    assert page.marked("error") == [3]
    assert page.says[("error", 3)] == "nothing of the kind"
    page.unmark("error")
    assert page.marked("error") == []
    assert page.says == {}


def test_a_mark_is_counted_from_one_as_a_person_counts(editor, file):
    page = editor.open(file).get_child()
    page.mark("error", 1, "the first line")
    place = page.buffer.get_iter_at_line(0)[1]
    assert page.buffer.get_source_marks_at_iter(place, "error")


def test_a_breakpoint_goes_on_and_comes_off(editor, file):
    page = editor.open(file).get_child()
    assert editor.toggle_breakpoint(page, 5) is True
    assert page.marked("breakpoint") == [5]
    assert editor.toggle_breakpoint(page, 5) is False
    assert page.marked("breakpoint") == []


def test_whoever_watches_hears_of_every_breakpoint(editor, file):
    """It is the only way the machine hears of one."""
    heard = []
    editor.marked.append(lambda page, line, on: heard.append((line, on)))
    page = editor.open(file).get_child()
    editor.toggle_breakpoint(page, 5)
    editor.toggle_breakpoint(page, 5)
    assert heard == [(5, True), (5, False)]


def test_the_breakpoints_of_every_file(editor, tmp_path):
    for name in ("one.s", "two.s"):
        (tmp_path / name).write_text("nop\nnop\nnop\n")
        editor.open(str(tmp_path / name))
    editor.toggle_breakpoint(editor.pages[0], 2)
    editor.toggle_breakpoint(editor.pages[1], 3)
    assert sorted(editor.breakpoints()) == [
        (str(tmp_path / "one.s"), 2), (str(tmp_path / "two.s"), 3)]


def test_a_file_that_is_nowhere_has_no_breakpoints_to_give(editor):
    """A breakpoint is a place in a file, and a file that was never saved is in no
    place the assembler could be told about."""
    page = editor.add("nop\n").get_child()
    editor.toggle_breakpoint(page, 1)
    assert page.marked("breakpoint") == [1]
    assert editor.breakpoints() == []


def test_what_the_assembler_said_goes_into_the_margins(editor, tmp_path):
    from pyrars.ui.shown import Problem

    (tmp_path / "one.s").write_text("nop\nnop\n")
    page = editor.open(str(tmp_path / "one.s")).get_child()
    editor.problems({str(tmp_path / "one.s"): (Problem(2, "error", "no such thing"),)})
    assert page.marked("error") == [2]
    assert page.says[("error", 2)] == "no such thing"
    editor.problems({})  # assembled again, and this time it was sound
    assert page.marked("error") == []


def test_where_the_machine_stands_is_marked_in_the_right_file(editor, tmp_path):
    for name in ("one.s", "two.s"):
        (tmp_path / name).write_text("nop\nnop\nnop\n")
        editor.open(str(tmp_path / name))
    editor.here(str(tmp_path / "one.s"), 2)
    assert editor.pages[0].marked("here") == [2]
    assert editor.pages[1].marked("here") == []
    # and the file it is in is the one being looked at
    assert editor.page is editor.pages[0]
    editor.here(str(tmp_path / "two.s"), 3)
    assert editor.pages[0].marked("here") == []
    assert editor.pages[1].marked("here") == [3]


def test_a_place_in_no_file_marks_nothing(editor, file):
    page = editor.open(file).get_child()
    editor.here(file, 2)
    editor.here(None, 0)
    assert page.marked("here") == []


# --------------------------------------------------------- the words offered


class Asking:
    """What a completion asks of the buffer, without a completion to ask it."""

    def __init__(self, buffer):
        self.buffer = buffer

    def get_buffer(self):
        return self.buffer


def test_the_words_offered_come_from_where_the_typing_is(editor, file):
    from pyrars.ui.editor import Words

    page = editor.open(file).get_child()
    page.buffer.set_text("        ad")
    page.buffer.place_cursor(page.buffer.get_end_iter())
    assert Words().offered(Asking(page.buffer)) == ("add", "addi")


def test_the_names_of_the_program_are_offered_as_they_are_known(editor, file):
    from pyrars.ui.editor import Words

    page = editor.open(file).get_child()
    page.buffer.set_text("        la t0, ta")
    page.buffer.place_cursor(page.buffer.get_end_iter())
    words = Words(lambda: editor.labels)
    assert words.offered(Asking(page.buffer)) == ()
    editor.labels = ("table", "total")
    # only one of them begins as the typing does
    assert words.offered(Asking(page.buffer))[0] == "table"


# ------------------------------------------------- the word under the pointer


def test_the_word_a_place_is_inside(editor):
    from pyrars.ui.editor import _word_at

    page = editor.add("        addi t0, t1, 1  # and a comment\n").get_child()
    buffer = page.buffer
    #         addi t0, t1, 1  # and a comment
    #   8---^  12^ ^13   ^18 ^21  ^24
    # The place just after a word belongs to that word: a pointer resting at the
    # end of "addi" is resting on "addi", which is what anybody would expect.
    for offset, expected in ((8, "addi"), (12, "addi"), (13, "t0"), (18, "t1"),
                             (21, "1"), (24, "")):
        assert _word_at(buffer.get_iter_at_offset(offset)) == expected, offset


def test_a_word_is_not_taken_across_a_line(editor):
    from pyrars.ui.editor import _word_at

    page = editor.add("addi\nt0\n").get_child()
    assert _word_at(page.buffer.get_iter_at_offset(0)) == "addi"
    assert _word_at(page.buffer.get_iter_at_offset(5)) == "t0"
