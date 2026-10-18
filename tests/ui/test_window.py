"""The window itself: that it is built, and that it says what the run is doing.

There is nothing here to compare with RARS - its window is Swing and D4 chose GTK
4 - so what is tested is that the window shows what the controller tells it and
offers only what can be done. Everything these tests lean on about WHICH actions
are possible is tested without GTK in `tests/unit/test_ui_actions.py`.
"""

from pathlib import Path

import pytest

from pyrars.session import project as projects

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
    assert "pc           0x00400000" in shown(window.standing)
    assert "instructions 0" in shown(window.standing)
    assert sensible(window) >= {"assemble", "continue", "step", "over", "finish",
                                "restart"}
    assert not sensible(window) & {"pause", "stop", "back"}


def test_a_step_and_what_the_window_says_of_it(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("step")
    assert turning(lambda: "instructions 1" in shown(window.standing))
    assert "stopped      stepped" in shown(window.standing)
    assert "back" in sensible(window)  # there is something to take back now


def test_a_step_back(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("step")
    assert turning(lambda: window.journal == 1)
    window.do("back")
    assert turning(lambda: window.journal == 0)
    assert "instructions 0" in shown(window.standing)
    assert "back" not in sensible(window)  # and nothing left to take back


def test_a_run_to_its_end(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    assert f"instructions {WHOLE}" in shown(window.standing)
    assert "stopped      exited" in shown(window.standing)
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
    assert turning(lambda: "instructions 1" in shown(window.standing))
    assert window.state == "standing"


def test_a_restart(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    window.do("restart")
    assert turning(lambda: window.state == "standing")
    assert "instructions 0" in shown(window.standing)


# ------------------------------------------------ the program asks for a line


@pytest.mark.parametrize("window", [ASKS], indirect=True)
def test_a_program_waiting_says_so_and_can_only_be_stopped(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.state == "waiting")
    assert "waiting" in shown(window.standing)
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
    window.views.set_current_page(1)  # looking at the messages
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.do("continue")
    assert turning(lambda: window.views.get_current_page() == 0)


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
    assert turning(lambda: "instructions 1" in shown(window.standing))
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
    window.do("assemble")
    assert turning(lambda: "load:" in shown(window.messages))


def test_a_question_that_failed_is_said_in_the_messages(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    window.control.ask("nonsense", lambda session: session.registers(("t9",)))
    assert turning(lambda: "nonsense failed:" in shown(window.messages))
    assert "no register of that name" in shown(window.messages)


def test_a_question_asked_before_a_program_is_open(window, turning):
    window.control.ask("where", lambda session: session.where())
    assert turning(lambda: "where failed: no program is open" in shown(window.messages))
