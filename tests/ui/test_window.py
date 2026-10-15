"""The window itself: that it is built, and that it says what the run is doing.

There is nothing here to compare with RARS - its window is Swing and D4 chose GTK
4 - so what is tested is that the window shows what the controller tells it and
offers only what can be done. Everything these tests lean on about WHICH actions
are possible is tested without GTK in `tests/unit/test_ui_actions.py`.
"""

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
    made = Window(project=project, text=source)
    yield made
    made.close_up()


def sensible(window) -> set[str]:
    return {name for name, button in window.buttons.items() if button.get_sensitive()}


def shown(view) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


# ------------------------------------------------------------------ the shape


def test_a_window_is_built(window):
    assert window.get_title() == "pyRARS"
    assert window.get_content() is not None
    assert len(window.buttons) == 9


def test_the_program_is_shown_before_anything_is_assembled(window):
    assert "main:   li t0, 3" in shown(window.program)
    assert sensible(window) == {"assemble"}  # and nothing else can be done yet


# --------------------------------------------------------------- what it does


def test_a_program_assembled(window, turning):
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    assert "pc           0x00400000" in shown(window.standing)
    assert "instructions 0" in shown(window.standing)
    assert sensible(window) == {"assemble", "continue", "step", "over", "finish",
                                "restart"}


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
    assert sensible(window) == {"assemble", "restart", "back"}


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
