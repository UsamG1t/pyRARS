"""The editor: the files, what is done to them, and what the colouring really does.

That the definition holds the right words is tested without GTK in
`tests/unit/test_ui_highlighting.py`. What is tested here is that GtkSourceView
ACCEPTS it and paints with it, which nothing but GtkSourceView can say.
"""

import pytest

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402 - after require_version

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


def test_a_letter_typed_reaches_the_completion_and_the_window_lives(editor, file,
                                                                   showing, turning):
    """The whole path THROUGH GTK: a letter typed, the provider asked for words,
    the words shown in the popup.

    This is the test the project did not have, and its absence cost the architect
    his window (2026-10-23): every way of COMPLETING the populate from Python
    crashes GTK, because the callback it hands in cannot be called back from here,
    and a test that only called `offered` never went near the handing over. A
    segfault takes the whole test process with it, which is as loud as a failure
    can be, and the old code was put back underneath this test to be sure of it.

    It can only be done where the screen gives the window the keyboard FOCUS: GTK
    asks a provider for nothing while the view has not got it, and a display with
    nothing managing its windows may give it to nobody. So this one says that and
    steps aside rather than passing for the wrong reason.
    """
    showing(editor)
    page = editor.open(file).get_child()
    page.view.grab_focus()
    if not turning(lambda: page.view.has_focus(), 2.0):
        pytest.skip("the screen would not give the window the keyboard focus, and "
                    "GTK asks a completion provider for nothing while the view "
                    "has not got it")
    for letter in "\n        ad":
        page.buffer.insert_at_cursor(letter)
        assert turning(lambda: True, 0.2)  # let GTK ask, as it does while typing
    offered = page.words.proposals
    assert offered is not None, "the provider was never asked"
    words = [offered.get_item(index).text for index in range(offered.get_n_items())]
    assert words[:2] == ["add", "addi"]
    # and they are really on the screen, in the popup of the completion
    assert "addi" in _labels(editor.get_root())


def _labels(widget) -> list[str]:
    """Every word written anywhere in a window that is on the screen."""
    said = []
    if isinstance(widget, Gtk.Label) and widget.get_mapped():
        said.append(widget.get_text())
    child = widget.get_first_child()
    while child is not None:
        said += _labels(child)
        child = child.get_next_sibling()
    return said


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


def test_what_a_word_of_the_program_is_told_of_where_the_pointer_rests(editor,
                                                                      showing):
    """A place of the window, by its coordinates, to the word that is there.

    This needs the page to be ON THE SCREEN: coordinates mean nothing until there
    is a layout to measure them against, and that is exactly where the mistake was
    - two numbers come back from `window_to_buffer_coords` and three were taken,
    so the tooltip never once appeared and nothing noticed.
    """
    page = editor.add("addi t0, t1, 1\n").get_child()
    showing(page)
    markup = page.help_at(8, 8)
    assert markup is not None
    assert "<b>addi</b>" in markup
    assert "I extension" in markup  # what kind of word it is
    assert "Adds a number to rs1" in markup  # what it DOES, which is what is wanted
    assert "addi rd, rs1, imm" in markup  # and how it is written


def test_a_place_that_holds_no_word_anybody_knows(editor, showing):
    page = editor.add("loopy t0\n").get_child()  # a word of the program's own
    showing(page)
    assert page.help_at(8, 8) is None


def test_the_coordinates_are_those_of_the_window_and_not_of_the_text(editor,
                                                                    showing,
                                                                    turning):
    """A pointer rests at a place of the WINDOW, and the text under it has been
    scrolled: the two are the same only while the view sits at the top, which is
    exactly where a test that forgot the difference would pass."""
    lines = ["addi t0, t1, 1"] + ["nop"] * 200 + ["csrr t0, fcsr"]
    page = editor.add("\n".join(lines) + "\n").get_child()
    showing(page)
    far = page.buffer.get_iter_at_line(len(lines) - 1)[1]
    page.buffer.place_cursor(far)
    page.view.scroll_to_iter(far, 0.0, True, 0.0, 0.0)
    assert turning(lambda: page.view.get_visible_rect().y > 100)
    markup = page.help_at(8, 8)
    assert markup is not None
    assert "addi" not in markup  # which is the first line, far above


def test_a_place_of_the_window_that_is_no_place_of_the_program(editor, showing):
    page = editor.add("addi t0, t1, 1\n").get_child()
    showing(page)
    assert page.help_at(-100, -100) is None


def test_what_is_told_of_a_pseudo_instruction(editor):
    from pyrars.ui.editor import told_of
    from pyrars.ui.help import about

    markup = told_of(about("li"))
    assert "<b>li</b>" in markup
    assert "Puts a number in rd" in markup
    assert "li rd, imm32   → lui + addi" in markup
    assert told_of(None) is None


def test_a_breakpoint_on_the_line_the_cursor_is_on(editor, file):
    """For whoever did not find the margin: the same mark, by a key."""
    page = editor.open(file).get_child()
    page.buffer.place_cursor(page.buffer.get_iter_at_line(2)[1])
    assert editor.toggle_breakpoint_here() == 3
    assert page.marked("breakpoint") == [3]
    assert editor.toggle_breakpoint_here() == 3
    assert page.marked("breakpoint") == []


def test_a_breakpoint_by_key_with_no_file_open(editor):
    assert editor.toggle_breakpoint_here() is None


# --------------------------------------------------- what a mark looks like


def filled(pixbuf, x: int, y: int) -> bool:
    from pyrars.ui.editor import SIZE

    return pixbuf.get_pixels()[(y * SIZE + x) * 4 + 3] > 120


def colour_at(pixbuf, x: int, y: int) -> tuple[int, int, int]:
    from pyrars.ui.editor import SIZE

    start = (y * SIZE + x) * 4
    return tuple(pixbuf.get_pixels()[start:start + 3])


def test_a_mark_of_our_own_is_drawn_rather_than_named(gtk):
    """A named symbolic icon is painted in the colour of the text around it, which
    in a margin is grey, and grey in a margin is not seen at all."""
    from pyrars.ui.editor import MARKS, RED, GREEN

    assert MARKS["breakpoint"][0] == ("dot", RED)
    assert MARKS["here"][0] == ("arrow", GREEN)
    assert isinstance(MARKS["error"][0], str)  # those two keep their icons


def test_a_breakpoint_is_a_round_red_dot(gtk):
    from pyrars.ui.editor import RED, SIZE, drawn

    dot = drawn("dot", RED)
    assert (dot.get_width(), dot.get_height()) == (SIZE, SIZE)
    middle = SIZE // 2
    assert filled(dot, middle, middle)
    assert colour_at(dot, middle, middle) == RED
    assert not filled(dot, 0, 0)  # the corners are outside a circle
    assert not filled(dot, SIZE - 1, SIZE - 1)
    # as wide as it is tall, which a disc is and a blob is not
    across = sum(filled(dot, x, middle) for x in range(SIZE))
    down = sum(filled(dot, middle, y) for y in range(SIZE))
    assert across == down > 4


def test_the_place_the_machine_stands_at_is_an_arrow_pointing_on(gtk):
    from pyrars.ui.editor import GREEN, SIZE, drawn

    arrow = drawn("arrow", GREEN)
    middle = SIZE // 2
    assert filled(arrow, 2, middle) and colour_at(arrow, 2, middle) == GREEN
    # wide where it begins and a point where it ends: it points the way on
    begins = sum(filled(arrow, 2, y) for y in range(SIZE))
    ends = sum(filled(arrow, SIZE - 4, y) for y in range(SIZE))
    assert begins > ends
    assert not filled(arrow, SIZE - 1, middle)


def test_a_mark_is_drawn_in_the_colour_it_was_given(gtk):
    from pyrars.ui.editor import SIZE, drawn

    blue = (0x10, 0x20, 0xF0)
    assert colour_at(drawn("dot", blue), SIZE // 2, SIZE // 2) == blue
    assert colour_at(drawn("arrow", blue), 2, SIZE // 2) == blue
