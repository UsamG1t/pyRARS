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

# Two keys of the digital lab read as hexadecimal digits, their sum shown in
# decimal on the two displays. The architect's own test of the lab (2026-10-22),
# and the one program of this suite that cannot run without somebody pressing
# something.
LAB = """\
.globl main
.data
digits: .byte   0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f
.text
main:   li      s0, 0xffff0010
        la      s1, digits
        jal     ra, key
        mv      s2, a0
        jal     ra, gone
        jal     ra, key
        add     s2, s2, a0
        li      t0, 10
        li      s3, 0
tens:   blt     s2, t0, show
        sub     s2, s2, t0
        addi    s3, s3, 1
        j       tens
show:   add     t1, s1, s3
        lbu     t1, 0(t1)
        sb      t1, 1(s0)
        add     t2, s1, s2
        lbu     t2, 0(t2)
        sb      t2, 0(s0)
        li      a7, 10
        ecall
key:    li      t3, 0
row:    li      t0, 1
        sll     t0, t0, t3
        sb      t0, 2(s0)
        lbu     t1, 4(s0)
        bne     t1, zero, which
        addi    t3, t3, 1
        andi    t3, t3, 3
        j       row
which:  srli    t1, t1, 4
        li      t2, 0
column: andi    t4, t1, 1
        bne     t4, zero, found
        srli    t1, t1, 1
        addi    t2, t2, 1
        j       column
found:  slli    a0, t3, 2
        add     a0, a0, t2
        ret
gone:   li      t3, 0
empty:  li      t0, 1
        sll     t0, t0, t3
        sb      t0, 2(s0)
        lbu     t1, 4(s0)
        bne     t1, zero, gone
        addi    t3, t3, 1
        li      t4, 4
        blt     t3, t4, empty
        ret
"""

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


def looking(window, page: str) -> None:
    """Open a page of the lower views, as a person does before reading it.

    The window asks the session for the page that is OPEN and for nothing else
    (`Window.wanted_now`), so a test that wants to read a view must say that
    somebody is looking at it - which is also what makes the tests read like use.
    """
    window.views.set_current_page(window.pages().index(page))


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
    # the eleven of the run - the cycle of the pipeline among them, which is
    # hidden until a pipeline is modelled - and the two of the files
    assert len(window.buttons) == 13
    assert not window.buttons["cycle"].get_visible()


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


def test_the_margins_are_read_once_for_the_text_segment(window, turning):
    """Asking a page which of its lines are marked walks the whole of its buffer,
    so it is asked ONCE and not once for every instruction of the program. It was
    the other way, which cost nothing while the text segment was put up at a stop
    and buried the window the day it began to be put up as a run went on
    (2026-10-25)."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    asked, marked = [], page.marked
    page.marked = lambda category: (asked.append(category), marked(category))[1]
    window._text_again()
    assert asked == ["breakpoint"]  # once, however many rows the table has
    assert len(window.views_of["text"].rows) > 5


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
    assert turning(lambda: window.state == "standing")
    looking(window, "labels")
    assert turning(lambda: window.views_of["labels"].rows != [])
    assert ("main", "0x00400000", "global") in window.views_of["labels"].rows
    looking(window, "frames")
    assert turning(lambda: True)
    assert window.views_of["frames"].rows == []  # it is inside no call yet
    looking(window, "data")
    assert turning(lambda: any(row[1] == ".word"
                               for row in window.views_of["data"].rows))
    window.editor.toggle_breakpoint(window.editor.page, 7)
    assert turning(lambda: True)
    window.do("continue")
    assert turning(lambda: window.state == "standing")
    # the one word the program keeps is there, wherever the run has got to
    assert turning(lambda: any(row[0] == "0x10010000"
                               for row in window.views_of["data"].rows))


def test_what_a_run_wrote_shows_in_the_data(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    looking(window, "data")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    assert turning(lambda: window.views_of["data"].rows != [])
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


def test_the_tables_are_left_alone_while_the_machine_runs(gtk, tmp_path, turning):
    """A table is a call into GTK for every row of it, and such a call costs a
    hundred times its price while a thread of Python runs flat out: the main loop
    gets the interpreter back only when the running thread's turn runs out.
    Measured 2026-10-25 - the text segment took TWO SECONDS to put up while a
    program ran - and measured at six hundred milliseconds a snapshot back in
    stage 45, which is where this rule began.

    So the tables wait for the machine to stand still (or for the run to be
    slowed, which the test below this one is about), and nothing of them could be
    read at that speed anyway.
    """
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(
        ".globl main\n.text\nmain: li t0, 0\nloop: addi t0, t0, 1\n      j loop\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "labels")
        assert turning(lambda: made.views_of["labels"].rows != [])
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


# --------------------------------------------- on to the line being looked at


def test_a_run_on_to_the_line_the_cursor_is_on(window, turning):
    """The one movement that comes from the editor: the line being LOOKED at is
    where the run stops, which is what every debugger calls running to the
    cursor."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    page.buffer.place_cursor(page.buffer.get_iter_at_line(9)[1])  # `la t2, total`
    window.do("until")
    # it stopped BEFORE that line, with the loop behind it and nothing after it
    assert turning(lambda: window.editor.page.marked("here") == [10])
    assert turning(lambda: _row(window, "registers", "t1")[2] == "0x00000006")
    assert _row(window, "registers", "t2")[2] == "0x00000000"
    assert window.state == "standing"


def test_a_line_with_no_instruction_on_it_cannot_be_run_to(window, turning):
    """Said in the same words as a breakpoint on such a line: it is the same
    question asked twice."""
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    page = window.editor.page
    page.buffer.place_cursor(page.buffer.get_iter_at_line(1)[1])  # `.data`
    window.do("until")
    assert turning(lambda: "no instruction" in shown(window.messages))
    assert window.state == "standing"  # and nothing of the run moved
    assert "until failed" in shown(window.messages)


def test_a_file_that_is_nowhere_has_no_line_to_run_to(gtk, tmp_path, turning):
    """The machine was given a file and not a buffer, so a buffer that is on no
    disk names no line of the program."""
    from pyrars.ui.window import Window

    made = Window(cache=str(tmp_path / "cache"))
    try:
        made.editor.add()
        made.state = "standing"  # as if a program were open: the action is allowed
        made.do("until")
        assert turning(lambda: "not saved anywhere yet" in shown(made.messages))
    finally:
        made.close_up()


# --------------------------------------------------- how fast the run goes


def test_the_picture_of_a_cache_fills_while_the_run_goes_on(gtk, tmp_path, turning):
    """The reason anybody watches a cache at all: the grid fills while the program
    runs, instead of after it. A picture is one call into GTK and a redraw, so it
    keeps up at any speed - the numbers beside it wait."""
    from pyrars.session import settings as runs
    from pyrars.ui import shown as writing
    from pyrars.ui.window import Window

    # a program that walks through memory and does not stop: a run to watch
    (tmp_path / "main.s").write_text(
        ".globl main\n.data\ntable: .space 256\n.text\n"
        "main:  la t1, table\nloop:  lw t0, 0(t1)\n       addi t1, t1, 4\n"
        "       j loop\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(cache={"sets": 4}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "cache")
        assert turning(lambda: made.views_of["cache"].rows != [])
        made.do("continue")  # at the speed of the machine, and no slower
        assert turning(lambda: made.state == "running")
        # the grid fills while the run goes on: blocks it is holding, drawn
        assert turning(lambda: any(part.fill == "clean" for part in
                                   made.pictures["cache"].picture.parts))
        assert made.state == "running"
        # and the numbers wait, because a table is dear while a run is flat out:
        # the cache has been reached hundreds of times by now, and the table still
        # says what it said before the run began
        said = {row[1]: row[2] for row in made.views_of["cache"].rows}
        assert said["accesses"] == "0"
        made.do("pause")
        assert turning(lambda: any(row[1] == "accesses" and row[2] != "0"
                                   for row in made.views_of["cache"].rows))
    finally:
        made.close_up()


def test_a_bitmap_display_paints_while_the_program_runs(gtk, tmp_path, turning):
    """What all of this was for (the architect, 2026-10-25): a program that paints
    at the speed of the machine, and a picture that FILLS while it does - instead
    of appearing all at once when the program is stopped.

    A picture is one call into GTK and a redraw, so it can be put up thirty times
    a second even while a thread of Python runs flat out; a table cannot, and the
    numbers of the display wait (the test above).
    """
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    # a program that paints its own words, one pixel at a time, and never stops
    (tmp_path / "main.s").write_text(
        ".globl main\n.text\n"
        "main:  li s0, 0x10040000\n       li s1, 0x00ff00\n"
        "loop:  sw s1, 0(s0)\n       addi s0, s0, 4\n       j loop\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(devices={"bitmap": {
                      "place": "heap", "width": 64, "height": 32}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "device:bitmap")
        painted = made.panels["device:bitmap"].picture
        assert turning(lambda: painted.looks != {})
        assert not any(painted.looks["pixels"])  # nothing is painted yet
        made.do("continue")
        assert turning(lambda: made.state == "running")
        # the picture fills WHILE the program runs, and goes on filling
        assert turning(lambda: any(painted.looks["pixels"]), 5.0)
        painted_now = sum(1 for one in painted.looks["pixels"] if one)
        assert made.state == "running"
        # and the NUMBERS of the display wait: a table is a call for every row
        said = dict(made.panels["device:bitmap"].table.rows)
        assert said["painted"].startswith("0 of")
        assert turning(lambda: sum(1 for one in painted.looks["pixels"]
                                   if one) > painted_now, 5.0)
        made.do("stop")
        assert turning(lambda: made.state == "ended")
    finally:
        made.close_up()


def test_the_speed_chosen_reaches_the_run(window, turning):
    """And with it what the thread of the run answers for while it goes: the open
    page always, and the REGISTERS once a speed is set, because a slowed run is
    one somebody is reading the registers of."""
    from pyrars.ui import shown as writing
    from pyrars.ui.window import REGISTERS, SHOWN

    looking(window, "labels")
    assert turning(lambda: True)
    assert set(window.control.watching) == {SHOWN}  # the page that is open
    window.how_fast.set_selected(len(writing.SPEEDS) - 1)  # the slowest there is
    assert window.speed == min(speed for speed in writing.SPEEDS if speed)
    assert window.control.speed == window.speed
    assert set(window.control.watching) == {REGISTERS, SHOWN}
    window.how_fast.set_selected(0)  # as fast as it can again
    assert window.speed is None and window.control.speed is None
    assert set(window.control.watching) == {SHOWN}
    looking(window, "console")  # and a page that needs nothing asks for nothing
    assert turning(lambda: True)
    assert window.control.watching == {}


def test_the_views_keep_up_while_a_slowed_run_goes(gtk, tmp_path, turning):
    """A slowed run is one somebody is WATCHING, which is the whole reason to slow
    one: the thread of the run sleeps between instructions, so there is time to
    show everything, and the views are put up as they are when the machine stands
    still. The opposite case - a run at the speed of the machine - is the test
    above this one.
    """
    from pyrars.ui import shown as writing
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(
        ".globl main\n.text\nmain: li t0, 0\nloop: addi t0, t0, 1\n      j loop\n")
    (tmp_path / "notes.s").write_text("# no part of the program\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        made.open(str(tmp_path / "notes.s"))  # and this is what is being looked at
        looking(made, "labels")
        assert turning(lambda: made.views_of["labels"].rows != [])
        made.how_fast.set_selected(writing.SPEEDS.index(10.0))
        made.do("continue")
        assert turning(lambda: made.state == "running")
        for name in ("labels", "registers", "text"):
            made.views_of[name].show([])
        assert turning(lambda: all(made.views_of[name].rows
                                   for name in ("labels", "registers", "text")))
        # and what they show follows the machine: the counter keeps rising
        counted = _row(made, "registers", "t0")[2]
        assert turning(lambda: _row(made, "registers", "t0")[2] != counted)
        # but the editor is not dragged to the line thirty times a second: a
        # window that jumped about while a run went on could not be read, and the
        # file somebody is looking at is not always the file being run
        assert made.editor.page.path.endswith("notes.s")
        # and nothing is ASKED while the run goes on: a question would wait in the
        # queue behind a movement nobody has stopped, and pile up there as fast as
        # the snapshots arrive. What is shown comes with the snapshots instead.
        assert made.control.queued == 0
        made.do("pause")
        # and once it stands still it does follow, as it always has
        assert turning(lambda: made.editor.page.path.endswith("main.s"))
        assert made.state == "standing"
    finally:
        made.close_up()


# ------------------------- the things around the machine, and the models of it


def test_a_page_is_there_only_while_the_run_is_set_up_to_fill_it(window, turning):
    """A page about a thing nobody asked to watch says nothing and takes the room
    of a page that would (the architect, 2026-10-22). The counting is the one
    thing a run comes with, so Counted is the one that is there to begin with."""
    from pyrars.session import settings as runs

    assert window.pages_wanted() == ["counted"]
    titles = _titles(window)
    assert titles[-1] == "Counted" and "Cache" not in titles
    window.the_run_is(runs.Settings(cache={}, pipeline={}, statistics=False,
                                    devices={"timer": {}, "dma": {}}))
    assert window.pages_wanted() == ["cache", "pipeline", "device:dma",
                                     "device:timer"]
    titles = _titles(window)
    assert titles[-4:] == ["Cache", "Pipeline", "DMA", "Timer"]
    assert "Counted" not in titles  # nobody is counting any more
    # and the pages that are always there are where they always were
    assert titles[:6] == ["Text", "Data", "Labels", "Frames", "Console",
                          "Messages"]
    kept = window.panels["device:timer"]
    window.the_run_is(runs.Settings())
    assert _titles(window)[-1] == "Counted"
    # a panel taken off the notebook and put back is the SAME panel: what it was
    # holding is what somebody was reading
    window.the_run_is(runs.Settings(devices={"timer": {}}))
    assert window.panels["device:timer"] is kept
    assert _titles(window)[-2:] == ["Counted", "Timer"]


def test_a_page_of_a_model_puts_the_picture_beside_the_table(window):
    """The same way round as a device's panel, and for the same reason: the views
    are wide and shallow, and both a picture and a table are narrow and long."""
    pane = window._page_of("cache")
    assert isinstance(pane, Gtk.Paned)
    assert pane.get_orientation() == Gtk.Orientation.HORIZONTAL


def test_a_page_whose_model_the_machine_has_not_got_says_so(window, turning):
    """The settings reach the machine at an Assemble, so a cache switched on while
    a program is already open is a page with nothing in it until the program is
    assembled again - which is what it says, rather than looking broken. This is
    what a cache that showed nothing really was (the architect, 2026-10-22)."""
    from pyrars.session import settings as runs

    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.the_run_is(runs.Settings(cache={}))
    assert "Cache" in _titles(window)
    looking(window, "cache")
    assert turning(lambda: "not been assembled since a cache was asked for"
                   in window.views_of["cache"].saying)
    assert "assemble again to run it that way" in shown(window.messages)
    window.do("assemble")
    assert turning(lambda: window.views_of["cache"].rows != [])
    assert window.views_of["cache"].saying == ""


def test_the_models_and_the_devices_of_a_run(gtk, tmp_path, turning):
    """What was asked for in the run window is what the machine is given, and
    every view of it fills from the session and from nowhere else."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(SUM)
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(cache={"sets": 4}, pipeline={},
                                         guesser={"predictor": "table"},
                                         devices={"timer": {"mode": "virtual"}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        made.do("continue")
        assert turning(lambda: made.state == "ended")
        looking(made, "cache")
        assert turning(lambda: made.views_of["cache"].rows != [])

        # the cache was built as it was asked for, and it saw the run
        said = {row[1]: row[2] for row in made.views_of["cache"].rows}
        assert said["sets"] == "4"
        assert said["the instructions reach it"] == "no"  # nobody asked for that
        # the program touches memory once - the one word it keeps - and the first
        # touch of a block is always a miss
        assert said["accesses"] == "1" and said["misses"] == "1"
        assert said["hits"] == "0" and said["hit rate"] == "0.0000"
        # and the grid of it holds the one block the program brought in
        drawn = made.pictures["cache"].picture
        assert [part.text for part in drawn.parts].count("0x10010000") == 1
        assert sum(1 for part in drawn.parts if part.fill == "dirty") == 1

        # the pipeline counted the time, and the guesser under it
        looking(made, "pipeline")
        assert turning(lambda: made.views_of["pipeline"].rows != [])
        counted = {row[0]: row[1] for row in made.views_of["pipeline"].rows}
        assert int(counted["cycles"]) > int(counted["instructions"]) == WHOLE
        assert counted["guesser"].startswith("a table of 16 entries")
        # a row of the diagram to every instruction, and five stages to a row;
        # "IF" is written once, over the column
        drawn = made.pictures["pipeline"].picture
        assert sum(1 for part in drawn.parts if part.text == "IF") == 1
        # the name of the column wears the colour too, so it is not a cell
        assert sum(1 for part in drawn.parts
                   if part.fill == "execute" and part.text != "EX") == WHOLE

        # the device has a page of its own, saying where a program finds it
        looking(made, "device:timer")
        panel = made.panels["device:timer"]
        assert turning(lambda: panel.table.rows != [])
        assert [row[0] for row in panel.table.rows][:2] == ["where", "size"]
        assert panel.table.rows[0][1] == "0xffff0018"
        assert "virtual" in dict(panel.table.rows)["clock"]
        assert panel.picture is None  # a timer is a time: there is nothing to draw

        # and what the run was made of, written out and drawn
        looking(made, "counted")
        assert turning(lambda: made.views_of["counted"].rows != [])
        made_of = {row[0]: row[1] for row in made.views_of["counted"].rows}
        assert made_of["instructions"] == str(WHOLE)
        assert int(made_of["branches that went"]) == 2  # the loop turns three times
        bars = made.pictures["counted"].picture
        assert [part.text for part in bars.parts if part.text].count("branch") == 1
    finally:
        made.close_up()


def test_the_cycle_of_the_pipeline_arrives_with_the_pipeline(window, turning):
    """The button is not there at all until a pipeline is being modelled: a cycle
    of a model nobody asked for is no cycle, and a button that can never be
    pressed is a button in the way (the architect, 2026-10-23)."""
    from pyrars.session import settings as runs

    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert not window.buttons["cycle"].get_visible()
    assert "cycle" not in window.allowed()  # and a key would reach nothing either
    window.the_run_is(runs.Settings(pipeline={}))
    assert window.buttons["cycle"].get_visible()
    assert "cycle" in window.allowed()
    assert "Pipeline" in _titles(window)


def test_the_cycles_of_the_pipeline_are_walked_in_the_window(gtk, tmp_path, turning):
    """Six steps of the machine and nine cycles of the model are the same five
    instructions; the frame of the cycle says which of them are in flight."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(
        ".globl main\n.text\nmain: li a1, 1\n      li a2, 2\n      li a3, 3\n"
        "      li a4, 4\n      add a5, a1, a2\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(pipeline={}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        assert made.buttons["cycle"].get_visible()
        looking(made, "pipeline")

        def said() -> str:
            """What the diagram says of the cycle it is showing."""
            return next((part.text for part in
                         made.pictures["pipeline"].picture.parts
                         if part.text.startswith("cycle ")), "")

        made.do("cycle")
        assert turning(lambda: said() == "cycle 0 of 5")
        framed = [part for part in made.pictures["pipeline"].picture.parts
                  if part.edge == "lit"]
        assert len(framed) == 1  # one instruction, in the fetch, and nothing else
        for expected in range(1, 5):
            made.do("cycle")
            assert turning(lambda: said().startswith(f"cycle {expected} "))
        # the pipeline is full: five instructions, each in a stage of its own
        assert said() == "cycle 4 of 9"
        assert len([part for part in made.pictures["pipeline"].picture.parts
                    if part.edge == "lit"]) == 5
        # and the machine was carried only as far as it had to be
        counted = {row[0]: row[1] for row in made.views_of["pipeline"].rows}
        assert counted["instructions"] == "5"
    finally:
        made.close_up()


def test_a_program_that_asks_for_its_numbers_by_the_keys_of_the_lab(gtk, tmp_path,
                                                                    turning):
    """A device may be TALKED TO and not only looked at.

    The whole way through, as the architect does it by hand: the lab attached in
    the run window, the program run, and the keys of the picture pressed - three
    of them, because a key of that lab stays down and the second press of the same
    key is what lets it go. Three plus five is eight, and eight is `0` on the left
    display and `8` on the right.
    """
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(LAB)
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(devices={"lab": {}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "device:lab")  # as somebody pressing its keys would
        made.do("continue")
        assert turning(lambda: made.state == "running")
        panel = made.panels["device:lab"]
        for key in (3, 3, 5):  # pressed, let go, and the second one pressed
            # as a click on the picture does it, by the name the picture gave it
            panel.picture.pressed(f"key:{key}")
            turning(lambda: False, 0.2)  # long enough for the program to poll
        assert turning(lambda: made.state == "ended", 10.0)
        assert turning(lambda: dict(panel.table.rows).get("left", "").startswith(
            "0x3f"))
        said = dict(panel.table.rows)
        assert said["left"].startswith("0x3f")  # the tens: a nought
        assert said["right"].startswith("0x7f")  # and the units: an eight
        # and the second key is still down, because nobody let it go: the program
        # did not need it let go, and a key of that lab stays where it is put
        assert said["key down"] == "5"
    finally:
        made.close_up()


def test_every_door_a_panel_asks_for_is_one_the_window_hands_over(window):
    """The panels name the doors they use and the window names the doors it gives.
    This reads the first list off the module itself, so neither can quietly grow
    past the other."""
    import inspect
    import re

    from pyrars.ui import devices

    asked = set(re.findall(r'door\("(\w+)"\)', inspect.getsource(devices)))
    assert asked == {"press", "typed", "fed", "put_on", "image_of", "ticking",
                     "said"}
    assert asked <= set(window._doors())


def test_a_line_typed_at_the_keyboard_can_be_lost_and_says_so(gtk, tmp_path,
                                                              turning):
    """The whole way, as somebody at the window does it - and the thing the device
    is FOR (the architect, 2026-10-26).

    The keyboard types the line out as a HAND does, a letter every so many
    instructions, and this program does a hundred instructions of work after every
    letter it reads. So the hand gets ahead of it: three letters pass unasked-for
    between one reading and the next, and the panel says how many went that way. A
    line that could not be lost would teach the opposite of what this device
    teaches.
    """
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    # reads keys and shows them until a newline, with work in between
    (tmp_path / "main.s").write_text(
        ".globl main\n.text\n"
        "main:  li      s0, 0xffff0000\n"
        "wait:  lw      t0, 0(s0)\n       andi    t0, t0, 1\n"
        "       beq     t0, zero, wait\n"
        "       lw      t1, 4(s0)\n       li      t2, 10\n"
        "       beq     t1, t2, done\n       sw      t1, 12(s0)\n"
        "       li      t3, 50\n"
        "work:  addi    t3, t3, -1\n       bne     t3, zero, work\n"
        "       j       wait\n"
        "done:  li      a7, 10\n       ecall\n")
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(devices={"keyboard": {"delay": 1}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "device:keyboard")
        made.do("continue")
        assert turning(lambda: made.state == "running")
        panel = made.panels["device:keyboard"]
        panel.typing.set_text("hi there")
        panel.typing.emit("activate")
        # the newline came last and is the one it read, so the program ends
        assert turning(lambda: made.state == "ended", 10.0)
        said = panel.picture.view.get_buffer()
        shown_now = said.get_text(said.get_start_iter(), said.get_end_iter(), False)
        assert "6 keys lost" in shown_now  # and the panel says where they went
        assert shown_now.startswith("hh")  # the two it did catch, and no more
        assert turning(lambda: dict(panel.table.rows).get("keys lost") == "6")
    finally:
        made.close_up()


def test_a_file_put_on_a_disk_and_written_back(gtk, tmp_path, turning):
    """What the command line does with `--device disk:file=...`, in a window: the
    file goes on by hand and comes off by hand. Nothing is written to anybody's
    disk unasked (the architect's decision, 2026-10-25)."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(SUM)
    (tmp_path / "image.img").write_bytes(bytes(range(16)))
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(devices={"disk": {"blocks": 2,
                                                           "block_size": 8}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        looking(made, "device:disk")
        panel = made.panels["device:disk"]
        made.control.put_on("disk", (tmp_path / "image.img").read_bytes())
        assert turning(lambda: True, 0.2)
        # and off it again, to where it was asked to go
        panel.writing = str(tmp_path / "back.img")
        made.control.image_of("disk")
        assert turning(lambda: (tmp_path / "back.img").exists())
        assert (tmp_path / "back.img").read_bytes() == bytes(range(16))
        assert "16 bytes written to back.img" in shown(made.messages)
    finally:
        made.close_up()


def test_an_image_the_disk_will_not_take(gtk, tmp_path, turning):
    """The size is the device's own, so the device is the one that says it - and
    the window says what the device said."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(SUM)
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(devices={"disk": {"blocks": 2,
                                                           "block_size": 8}}))
    try:
        made.do("assemble")
        assert turning(lambda: made.state == "standing")
        made.control.put_on("disk", b"too short")
        assert turning(lambda: "an image of 9 bytes for a disk of 16"
                       in shown(made.messages))
    finally:
        made.close_up()


def test_a_run_that_cannot_be_set_up_is_said_and_nothing_is_assembled(gtk, tmp_path,
                                                                      turning):
    """The settings are given to the machine at the Assemble, so this is where
    something impossible in them comes out."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    (tmp_path / "main.s").write_text(SUM)
    made = Window(files=(str(tmp_path / "main.s"),), cache=str(tmp_path / "cache"),
                  settings=runs.Settings(cache={"sets": 3}))
    try:
        made.do("assemble")
        assert turning(lambda: "cannot be set up" in shown(made.messages))
        assert "power of two" in shown(made.messages)
        assert made.state == "nothing"  # nothing was assembled
    finally:
        made.close_up()


def test_settings_of_a_run_that_cannot_be_read_are_said_and_not_thrown(gtk, tmp_path,
                                                                      turning):
    """A window must open whatever is in that file: a person who wrote one by hand
    is told what is wrong with it and given the settings as they come."""
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    Path(runs.path()).parent.mkdir(parents=True)
    Path(runs.path()).write_text('{"cache": "a big one"}')
    made = Window(cache=str(tmp_path / "cache"))
    try:
        assert "the settings of the run:" in shown(made.messages)
        assert "as they come" in shown(made.messages)
        assert made.settings == runs.Settings()
    finally:
        made.close_up()


def _titles(window) -> list[str]:
    """What the tabs of the lower views say, in order."""
    notebook = window.views
    return [notebook.get_tab_label(notebook.get_nth_page(index)).get_text()
            for index in range(notebook.get_n_pages())]


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
    looking(window, "frames")
    assert turning(lambda: True)
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
        looking(made, "frames")
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
