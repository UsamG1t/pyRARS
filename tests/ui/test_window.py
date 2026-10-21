"""The window itself: that it is built, and that it says what the run is doing.

There is nothing here to compare with RARS - its window is Swing and D4 chose GTK
4 - so what is tested is that the window shows what the controller tells it and
offers only what can be done. Everything these tests lean on about WHICH actions
are possible is tested without GTK in `tests/unit/test_ui_actions.py`.
"""

from pathlib import Path

import pytest

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from pyrars.session import project as projects  # noqa: E402

pytestmark = pytest.mark.ui

SUM = """\
.globl main
.data
total:  .word 0
.text
main:   li t0, 3
        li t1, 0
loop:   add t1, t1, t0
        addi t0, t0, -1
        bne t0, x0, loop
        la t2, total
        sw t1, 0(t2)
        li a7, 93
        li a0, 0
        ecall
"""
WHOLE = 2 + 3 * 3 + 2 + 1 + 2  # the loop three times, `la` being two instructions

ASKS = """\
.globl main
.text
main:   li a7, 5        # a number, please
        ecall
        mv t0, a0
        li a7, 1        # and here it is again
        mv a0, t0
        ecall
        li a7, 10
        ecall
"""

SPEAKS = """\
.globl main
.data
hello:  .asciz "hello"
.text
main:   li a7, 4
        la a0, hello
        ecall
        li a7, 93
        li a0, 0
        ecall
"""


@pytest.fixture
def window(gtk, tmp_path, request):
    """A window over a program, closed however the test ends."""
    from pyrars.ui.window import Window

    source = getattr(request, "param", SUM)
    (tmp_path / "main.s").write_text(source)
    project = projects.of([str(tmp_path / "main.s")], folder=str(tmp_path))
    made = Window(project=project, cache=str(tmp_path / "cache"))
    yield made
    made.close_up()


def sensible(window) -> set[str]:
    return {name for name, button in window.buttons.items() if button.get_sensitive()}


def shown(view) -> str:
    """What a view of text holds; a label is asked for its text instead."""
    if isinstance(view, Gtk.Label):
        return view.get_text()
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


# ------------------------------------------------------------------ the shape


def test_a_window_is_built(window):
    assert window.get_title() == "main.s - pyRARS"  # the file it was opened on
    assert window.get_content() is not None
    # the nine of the run, and the two of the files that have a button of their own
    assert len(window.buttons) == 11


def test_the_program_is_open_in_the_editor_before_anything_is_assembled(window):
    assert "main:   li t0, 3" in window.editor.page.text
    assert window.editor.page.path.endswith("main.s")
    # of the run, only assembling; of the files, what one open file allows.
    # `sensible` sees the buttons of the header; the rest live in the menu, which
    # is why what CAN be done is asked of the window itself.
    assert sensible(window) == {"assemble", "open"}
    assert window.allowed() >= {"assemble", "open", "new", "find", "close_tab"}
    assert not window.allowed() & {"step", "continue", "back", "pause", "stop"}


# --------------------------------------------------------------- what it does


def test_a_program_assembled(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert "0x00400000" in window.standing.get_text()
    assert "0 carried out" in window.standing.get_text()
    assert sensible(window) >= {"assemble", "continue", "step", "over", "finish",
                                "restart"}
    assert not sensible(window) & {"pause", "stop", "back"}


def test_a_step_and_what_the_window_says_of_it(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("step")
    assert turning(lambda: "1 carried out" in window.standing.get_text())
    assert "stepped" in window.standing.get_text()
    assert "back" in sensible(window)  # there is something to take back now


def test_a_step_back(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("step")
    assert turning(lambda: window.journal == 1)
    window.do("back")
    assert turning(lambda: window.journal == 0)
    assert "0 carried out" in window.standing.get_text()
    assert "back" not in sensible(window)  # and nothing left to take back


def test_a_run_to_its_end(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    assert f"{WHOLE} carried out" in window.standing.get_text()
    assert "exited" in window.standing.get_text()
    assert sensible(window) >= {"assemble", "restart", "back"}
    assert not sensible(window) & {"step", "continue", "over", "finish", "pause"}


def test_what_cannot_be_done_is_not_even_asked_for(window, turning):
    """A window asked for something that is not possible does nothing AT ALL - it
    does not hand it to the controller to refuse, which would say so in the
    messages. The rule is one place, and a key is no way around it."""
    window.do("step")  # nothing is open
    assert turning(lambda: True)
    assert window.state == "nothing"
    assert "failed" not in shown(window.messages)


def test_a_run_is_not_ended_by_a_stop_it_never_heard(window, turning):
    """Why the rule has to be kept by the window and not only by the controller:
    `stop` ends the run it is given to, and a machine that stands still is in no
    run to end. Were the window to pass it on, the NEXT step would find a session
    that had been told the run was over."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("stop")  # not possible: the machine is standing still
    window.do("step")
    assert turning(lambda: "1 carried out" in window.standing.get_text())
    assert window.state == "standing"


def test_a_restart(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    window.do("restart")
    assert turning(lambda: window.state == "standing")
    assert "0 carried out" in window.standing.get_text()


# ------------------------------------------------ the program asks for a line


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_a_program_waiting_says_so_and_can_only_be_stopped(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "waiting")
    assert "waiting" in window.standing.get_text()
    assert "waiting for a line" in window.typing.get_placeholder_text()
    assert sensible(window) & {"pause", "step", "continue", "restart"} == set()
    assert "stop" in sensible(window)
    window.do("stop")
    assert turning(lambda: window.state == "ended")


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_what_is_typed_goes_to_the_program_and_into_the_console(window, turning):
    """A terminal is one thing: what was typed is written where the program writes,
    so that what is read afterwards is the whole conversation."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "waiting")
    window.typing.set_text("40")
    window._typed()
    assert turning(lambda: window.state == "ended")
    assert shown(window.console) == "40\n40"  # typed, then printed back
    assert window.typing.get_text() == ""  # and the line is clear for the next one
    assert "waiting" not in window.typing.get_placeholder_text()


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_the_console_is_brought_forward_when_the_program_asks(window, turning):
    window.views.set_current_page(0)  # looking at the text segment
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.views.get_current_page() == window.console_page)


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_a_line_may_be_typed_before_the_program_asks_for_it(window, turning):
    """As it may at a terminal: what is typed waits until the program reads it, and
    nobody is told that the program is waiting, because it never had to."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.typing.set_text("7")
    window._typed()
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    assert shown(window.console) == "7\n7"


def test_a_file_that_is_not_there_is_said_and_not_thrown(gtk, tmp_path):
    """A window given a name nobody has must still open."""
    from pyrars.ui.window import Window

    made = Window(files=(str(tmp_path / "nothing.s"),),
                  cache=str(tmp_path / "cache"))
    try:
        assert "No such file" in shown(made.messages)
        assert made.editor.pages == []
    finally:
        made.close_up()


# --------------------------------------------- the console holds one run


@pytest.mark.parametrize("window", [SPEAKS], indirect=True)
def test_the_console_is_cleared_when_a_program_is_assembled(window, turning):
    """What the last run said is not what this one is saying, and two of them in
    one place read as one."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: "hello" in shown(window.console))
    window.do("assemble")
    assert turning(lambda: shown(window.console) == "")


@pytest.mark.parametrize("window", [SPEAKS], indirect=True)
def test_the_console_is_cleared_when_a_program_begins_again(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: "hello" in shown(window.console))
    window.do("restart")
    assert turning(lambda: shown(window.console) == "")


@pytest.mark.parametrize("window", [SPEAKS], indirect=True)
def test_the_console_may_be_cleared_by_hand(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: "hello" in shown(window.console))
    window.clear_console()
    assert shown(window.console) == ""


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_a_line_typed_for_a_run_that_never_began_is_not_fed_to_the_next(window,
                                                                       turning):
    """A line is typed FOR a run - the one that was open when it was typed.
    Somebody who types ahead and changes their mind must not find a program they
    never meant to feed eating it."""
    window.typing.set_text("111")
    window._typed()
    window.typing.set_text("222")
    window._typed()
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    # it asks, rather than taking what was typed before it existed
    assert turning(lambda: window.state == "waiting")
    assert shown(window.console) == ""
    window.typing.set_text("7")
    window._typed()
    assert turning(lambda: window.state == "ended")
    assert shown(window.console) == "7\n7"


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_a_program_that_begins_again_asks_again(window, turning):
    """A restart is a fresh run: what was typed for the last one is gone with it,
    and the program asks for its own."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "waiting")
    window.typing.set_text("7")
    window._typed()
    assert turning(lambda: window.state == "ended")
    window.do("restart")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "waiting")  # asked again
    assert shown(window.console) == ""  # and the console holds this run only
    window.typing.set_text("9")
    window._typed()
    assert turning(lambda: window.state == "ended")
    assert shown(window.console) == "9\n9"


# ----------------------------------------- what the editor is told of a program


BROKEN = """\
.text
main:   li t0, 1
        nonsense t0, t1
        ecall
"""


@pytest.mark.parametrize("window", [BROKEN], indirect=True)
def test_what_the_assembler_said_goes_into_the_margin(window, turning):
    window.do("assemble")
    assert turning(lambda: "not been assembled" in shown(window.messages))
    page = window.editor.page
    assert page.marked("error") == [3]
    assert "not a recognized operator" in page.says[("error", 3)]
    assert window.state == "nothing"  # and there is nothing to run


def test_a_program_that_assembles_leaves_no_marks_behind(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    assert page.marked("error") == []
    assert "assembled: " in shown(window.messages)


def test_the_names_of_the_program_reach_the_words_offered(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert "main" in window.editor.labels
    assert "loop" in window.editor.labels


def test_a_breakpoint_put_in_the_margin_stops_the_run(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    window.editor.toggle_breakpoint(page, 7)  # the `add` of the loop
    assert turning(lambda: True)
    window.do("continue")
    assert turning(lambda: window.state == "standing"
                   and "breakpoint" in window.standing.get_text())
    assert page.marked("here") == [7]  # and the margin says where it stands


def test_a_breakpoint_taken_off_again_stops_nothing(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    window.editor.toggle_breakpoint(page, 7)
    window.editor.toggle_breakpoint(page, 7)
    assert turning(lambda: True)
    window.do("continue")
    assert turning(lambda: window.state == "ended")


def test_a_breakpoint_where_no_instruction_is_comes_off_again(window, turning):
    """A line that holds no instruction cannot be stopped before, so the mark goes
    and the person is told why rather than left to wonder."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    window.editor.toggle_breakpoint(page, 2)  # ".data"
    assert turning(lambda: "no instruction of the program is there"
                   in shown(window.messages))
    assert page.marked("breakpoint") == []


def test_the_breakpoints_of_the_margin_are_given_to_a_program_as_it_is_assembled(
        window, turning):
    """They are put in before there is anything to put them in, which is the
    ordinary way of working: open a file, mark a line, assemble."""
    page = window.editor.page
    window.editor.toggle_breakpoint(page, 7)
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: "breakpoint" in window.standing.get_text())


def test_the_margin_follows_the_machine(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    assert turning(lambda: page.marked("here") == [5])  # `main`
    window.do("step")
    assert turning(lambda: page.marked("here") == [6])
    window.do("back")
    assert turning(lambda: page.marked("here") == [5])


# ------------------------------------------------- the editor and the machine


def test_what_is_on_the_screen_is_what_is_assembled(window, turning):
    """An assembler reads files from the disk, so what has been changed is written
    there first - and then the machine runs what the person typed, not what the
    file held when it was opened."""
    page = window.editor.page
    page.buffer.set_text(SUM.replace("li t0, 3", "li t0, 9"))
    assert window.editor.modified is True
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert window.editor.modified is False  # it was saved on the way
    assert "li t0, 9" in Path(page.path).read_text()
    window.do("step")
    assert turning(lambda: "1 carried out" in window.standing.get_text())
    window.control.ask("t0", lambda session: session.registers(("t0",))[0].value)
    assert turning(lambda: "t0: 9" in shown(window.messages))


def test_a_file_that_is_nowhere_cannot_be_assembled(gtk, tmp_path, turning):
    from pyrars.ui.window import Window

    made = Window(cache=str(tmp_path / "cache"))
    try:
        made.editor.add("li t0, 1\n")  # never saved, so it is on no disk
        made.do("assemble")
        assert turning(lambda: "nothing to assemble" in shown(made.messages))
        assert made.state == "nothing"
    finally:
        made.close_up()


def test_the_window_says_which_file_is_being_worked_on(window, turning):
    from pyrars.ui.shown import CHANGED

    assert window.get_title() == "main.s - pyRARS"
    window.editor.page.buffer.insert_at_cursor("# a change\n")
    assert window.get_title() == f"main.s {CHANGED} - pyRARS"


def test_a_new_file_and_what_can_be_done_to_it(window):
    window.do("new")
    assert len(window.editor.pages) == 2
    assert window.editor.page.path is None
    # it is on no disk, so it may always be saved - the person is asked where
    assert "save" in window.allowed()
    assert window.get_title().startswith("Untitled")


# ------------------------------------------------------------- what it shows


@pytest.mark.parametrize("window", [SPEAKS], indirect=True)
def test_what_the_program_writes_reaches_the_console(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: "hello" in shown(window.console))


def test_what_the_controller_says_reaches_the_messages(window, turning):
    """What an assembly came to is said in a line a person can read, and not as the
    whole of an assembled program printed out."""
    window.do("assemble")
    assert turning(lambda: "assembled: " in shown(window.messages))
    assert "instructions" in shown(window.messages)
    assert "AssembledProgram(" not in shown(window.messages)


def test_a_question_that_failed_is_said_in_the_messages(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.control.ask("nonsense", lambda session: session.registers(("t9",)))
    assert turning(lambda: "nonsense failed:" in shown(window.messages))
    assert "no register of that name" in shown(window.messages)


def test_a_question_asked_before_a_program_is_open(window, turning):
    window.control.ask("where", lambda session: session.where())
    assert turning(lambda: "where failed: no program is open" in shown(window.messages))


# ------------------------------------------------------ the views of the machine


def test_the_registers_are_shown_as_soon_as_a_program_is_open(window, turning):
    window.do("assemble")
    assert turning(lambda: any(row[0] == "t0"
                               for row in window.views_of["registers"].rows))
    rows = {row[0]: row for row in window.views_of["registers"].rows}
    assert len(rows) == 32
    assert rows["zero"] == ("zero", "x0", "0x00000000")
    assert len(window.views_of["floats"].rows) == 32
    assert any(row[0] == "fcsr" for row in window.views_of["control"].rows)


def test_the_registers_follow_the_machine(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("step")  # li t0, 3
    assert turning(lambda: _row(window, "registers", "t0")[2] == "0x00000003")
    window.do("back")
    assert turning(lambda: _row(window, "registers", "t0")[2] == "0x00000000")


def test_the_text_segment_is_the_program_with_its_places_marked(window, turning):
    from pyrars.ui.shown import BREAK, HERE

    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    rows = window.views_of["text"].rows
    assert rows[0][1] == "0x00400000"
    assert rows[0][3].startswith("addi")  # the basic form of what was written
    assert rows[0][0] == HERE  # and the machine is at the beginning
    window.editor.toggle_breakpoint(window.editor.page, 7)
    assert turning(lambda: any(BREAK in row[0] for row in window.views_of["text"].rows))


def test_the_data_the_labels_and_the_frames(window, turning):
    window.do("assemble")
    assert turning(lambda: window.views_of["labels"].rows != [])
    assert ("main", "0x00400000", "global") in window.views_of["labels"].rows
    assert any(row[1] == ".word" for row in window.views_of["data"].rows)
    assert window.views_of["frames"].rows == []  # it is inside no call yet
    window.editor.toggle_breakpoint(window.editor.page, 7)
    assert turning(lambda: True)
    window.do("continue")
    assert turning(lambda: window.views_of["data"].rows != [])
    # the one word the program keeps is there, wherever the run has got to
    assert any(row[0] == "0x10010000" for row in window.views_of["data"].rows)


def test_what_a_run_wrote_shows_in_the_data(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    kept = [row for row in window.views_of["data"].rows if row[0] == "0x10010000"]
    assert kept and kept[0][3] == "0x00000006"  # 3 + 2 + 1, as the loop counts down


def test_the_format_chosen_reaches_every_view(window, turning):
    window.do("assemble")
    assert turning(lambda: _row(window, "registers", "t0") is not None)
    window.do("step")
    assert turning(lambda: _row(window, "registers", "t0")[2] == "0x00000003")
    window.format = "dec"
    window._views_again()
    assert turning(lambda: _row(window, "registers", "t0")[2] == "3")
    assert all(not row[2].startswith("0x") for row in window.views_of["text"].rows)


def test_the_views_are_left_alone_while_the_machine_runs(gtk, tmp_path, turning):
    """While the machine runs, the window does the least it can.

    The thread of the run holds the interpreter nearly all the time - a loop of a
    million instructions a second is a loop of Python - so every call this thread
    makes waits its turn. A window that rebuilt its tables thirty times a second
    answered the pointer in half a second instead of at once; measured at six
    hundred milliseconds a snapshot before this, and under forty after.

    Nothing of what is left out could be read at that speed anyway, and all of it
    is put up the moment the machine stands still.
    """
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(
        ".globl main\n.text\nmain: li t0, 0\nloop: addi t0, t0, 1\n      j loop\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        asked = len(made.views_of["labels"].rows)
        registers = len(made.views_of["registers"].rows)
        assert asked and registers
        made.do("continue")
        assert turning(lambda: made.state == "running")
        for name in ("labels", "registers", "text"):
            made.views_of[name].show([])  # nothing fills them again while it runs
        assert turning(lambda: True)
        assert [made.views_of[name].rows for name in ("labels", "registers", "text")] \
            == [[], [], []]
        # and the line that says where the run is DOES keep moving
        assert "running" in made.standing.get_text()
        made.do("pause")
        assert turning(lambda: len(made.views_of["labels"].rows) == asked)
        assert len(made.views_of["registers"].rows) == registers
        assert made.views_of["text"].rows != []
    finally:
        made.close_up()


def _row(window, which: str, name: str):
    for row in window.views_of[which].rows:
        if row[0] == name:
            return row
    return None


# ------------------------------------------- a table with nothing in it


def test_a_table_with_nothing_in_it_says_why(window, turning):
    """An empty table answers two questions at once - is there nothing, or is this
    broken? - and only one of them is the one being asked."""
    assert window.views_of["text"].saying == "No program is assembled yet"
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert window.views_of["text"].saying == ""  # it holds rows now
    assert window.views_of["frames"].saying.startswith("The run is inside no call")


def test_the_frames_of_a_recursion(gtk, tmp_path, turning):
    """A frame for every call the run is inside, which a recursion makes several
    of - and the one view nothing else in the window shows."""
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text("""\
.globl main
.text
main:   li a0, 4
        jal ra, fact
        li a7, 10
        ecall
fact:   addi sp, sp, -8
        sw ra, 4(sp)
        sw a0, 0(sp)
        li t0, 2
        blt a0, t0, one
        addi a0, a0, -1
        jal ra, fact
        lw t1, 0(sp)
        mul a0, a0, t1
        j back
one:    li a0, 1
back:   lw ra, 4(sp)
        addi sp, sp, 8
        ret
""")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        made.editor.toggle_breakpoint(made.editor.page, 17)  # `one:`, the bottom
        assert turning(lambda: True)
        made.do("continue")
        assert turning(lambda: made.state == "standing"
                       and made.views_of["frames"].rows != [])
        frames = made.views_of["frames"].rows
        assert len(frames) == 4  # fact(4) calling itself down to fact(1)
        assert [row[0] for row in frames] == ["1", "2", "3", "4"]
        assert all("<fact>" in row[1] for row in frames)
        # the first was called from `main`, the rest from `fact` itself
        assert frames[0][2] != frames[1][2]
        assert frames[1][2] == frames[2][2] == frames[3][2]
        # and every frame stands lower than the one before it
        corners = [int(row[3], 16) for row in frames]
        assert corners == sorted(corners, reverse=True)
        assert made.views_of["frames"].saying == ""
    finally:
        made.close_up()
