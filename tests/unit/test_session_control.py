"""Driving a run from a thread of its own: what comes back, and from where.

RARS has nothing to compare this with - its own window and its simulator thread
are one piece of Java - so every expected value here is worked out from what the
controller PROMISES: one thread carries everything out, what comes back is the
data of a session, a snapshot goes out no oftener than it was asked to, and the
two things that cannot wait for the queue (pause, stop) are the only ones that do
not.

No test here may hang, whatever goes wrong (the lesson of stage 24): every wait
has a timeout and every wait is asserted.
"""

import io
import threading
import time

import pytest

from pyrars.session import project as projects
from pyrars.devices import DeviceBus, make
from pyrars.session.control import (
    ASKING, DEVICE, ENDED, LOAD, NOTHING, RUNNING, STANDING, WAITING, Answer,
    Failed, RunController, Snapshot, Waiting)

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
        jal ra, keep
        li a7, 93
        li a0, 0
        ecall
keep:   la t0, total
        sw t1, 0(t0)
        ret
"""
FOREVER = """\
.globl main
.text
main:   li t0, 0
loop:   addi t0, t0, 1
        j loop
"""
ASKS = """\
.globl main
.data
buffer: .space 32
.text
main:   li a7, 8
        la a0, buffer
        li a1, 32
        ecall
        li a7, 93
        li a0, 0
        ecall
"""
BROKEN = ".text\nmain: nonsense t0, t1\n"

# Two to set up, three to a turn of the loop three times over, the call, the two
# halves of `la` with the store and the return, and two before the exit; the
# `ecall` that ends the run does not count.
WHOLE = 2 + 3 * 3 + 1 + 4 + 2


def project(tmp_path, source: str = SUM):
    (tmp_path / "main.s").write_text(source)
    return projects.of([str(tmp_path / "main.s")], folder=str(tmp_path))


def waited_for(whether, timeout: float = 5.0) -> bool:
    """Wait for something to become true, and say whether it did. Nothing here
    waits for ever, however badly the thing being tested behaves."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if whether():
            return True
        time.sleep(0.001)
    return False


class Told:
    """What the controller told us, in the order it told us."""

    def __init__(self) -> None:
        self.events: list[object] = []
        self.threads: set[int] = set()
        self._lock = threading.Lock()

    def __call__(self, event) -> None:
        with self._lock:
            self.events.append(event)
            self.threads.add(threading.get_ident())

    @property
    def snapshots(self) -> list[Snapshot]:
        return [one for one in self.events if isinstance(one, Snapshot)]

    @property
    def answers(self) -> list[Answer]:
        return [one for one in self.events if isinstance(one, Answer)]

    @property
    def failures(self) -> list[Failed]:
        return [one for one in self.events if isinstance(one, Failed)]

    @property
    def last(self) -> Snapshot:
        return self.snapshots[-1]


@pytest.fixture
def told():
    return Told()


@pytest.fixture
def control(told):
    """A controller over a world that writes into a string, closed afterwards
    however the test ends."""
    made = RunController(told, out=io.StringIO(), errors=io.StringIO())
    yield made
    made.close()


def opened(control, tmp_path, source: str = SUM, **kept) -> None:
    control.load(project(tmp_path, source), **kept)
    assert control.settled()


# -------------------------------------------------------------- opening a program


def test_nothing_is_open_to_begin_with(control, told):
    assert control.state == NOTHING
    assert told.events == []


def test_a_program_opened(control, told, tmp_path):
    opened(control, tmp_path)
    assert [one.what for one in told.answers] == [LOAD]
    assert told.answers[0].value.failed is False
    assert told.last.state == STANDING
    assert told.last.place.symbol == "main"
    assert (told.last.instructions, told.last.back) == (0, 0)


def test_a_program_that_cannot_be_assembled(control, told, tmp_path):
    opened(control, tmp_path, BROKEN)
    program = told.answers[0].value
    assert program.failed is True
    assert program.diagnostics  # and the window has them to show
    assert control.state == NOTHING
    assert told.snapshots == []  # there is nothing to take a picture of


def test_a_question_with_nothing_open(control, told):
    control.ask("where", lambda session: session.where())
    assert control.settled()
    assert told.failures == [Failed("where", "no program is open")]


# ---------------------------------------------------------------- the movement


def test_a_step(control, told, tmp_path):
    opened(control, tmp_path)
    control.step(3)
    assert control.settled()
    assert told.last.stopped.reason == "stepped"
    assert told.last.stopped.steps == 3
    assert (told.last.instructions, told.last.back) == (3, 3)
    assert told.last.state == STANDING


def test_every_movement_ends_in_a_snapshot_of_its_own(control, told, tmp_path):
    opened(control, tmp_path)
    control.step(2)
    control.over()
    control.back()
    control.until(0x00400018)
    control.restart()
    assert control.settled()
    assert [one.stopped.reason for one in told.snapshots if one.stopped] == [
        "stepped", "stepped", "stepped", "stepped", "nothing"]
    assert told.last.instructions == 0  # the restart put the run back to nothing


def test_a_run_to_its_end(control, told, tmp_path):
    opened(control, tmp_path)
    control.carry_on()
    assert control.settled()
    assert told.last.stopped.reason == "exited"
    assert told.last.stopped.steps == WHOLE
    assert told.last.state == ENDED


def test_a_movement_after_the_run_has_ended(control, told, tmp_path):
    opened(control, tmp_path)
    control.carry_on()
    control.step()
    assert control.settled()
    assert told.last.stopped.reason == "ended"


def test_the_order_asked_is_the_order_done(control, told, tmp_path):
    opened(control, tmp_path)
    control.step()
    control.ask("first", lambda session: session.count().instructions)
    control.step(4)
    control.ask("second", lambda session: session.count().instructions)
    assert control.settled()
    assert [(one.what, one.value) for one in told.answers[1:]] == [
        ("first", 1), ("second", 5)]


# ------------------------------------------------------------- what is asked for


def test_a_question_is_answered_with_the_data_of_a_session(control, told, tmp_path):
    opened(control, tmp_path)
    control.step(2)
    control.ask("registers", lambda session: session.registers(("t0", "t1")))
    assert control.settled()
    answer = told.answers[-1]
    assert answer.what == "registers"
    assert [(one.name, one.value) for one in answer.value] == [("t0", 3), ("t1", 0)]


def test_a_question_that_changes_something(control, told, tmp_path):
    """Everything a session can do is a question here, the changes among them: a
    window has no other way in, and this module grows no method for each."""
    opened(control, tmp_path)
    control.ask("break", lambda session: session.add_break(0x00400018))
    control.carry_on()
    assert control.settled()
    assert told.answers[-1].value.id == 1
    assert told.last.stopped.reason == "breakpoint"


def test_a_question_that_cannot_be_answered(control, told, tmp_path):
    opened(control, tmp_path)
    control.ask("nonsense", lambda session: session.registers(("t9",)))
    assert control.settled()
    assert told.failures == [Failed("nonsense", '"t9": no register of that name')]
    # and the controller lives on
    control.step()
    assert control.settled()
    assert told.last.stopped.reason == "stepped"


def test_a_question_that_fails_without_a_word_to_say(control, told, tmp_path):
    opened(control, tmp_path)
    control.ask("nothing", lambda session: 1 / 0)
    assert control.settled()
    assert told.failures[0].message  # the kind of it, where there is no message
    assert "zero" in told.failures[0].message


# --------------------------------------------------- what does not wait in line


def test_a_program_without_an_end_is_paused_from_outside(control, told, tmp_path):
    opened(control, tmp_path, FOREVER)
    control.carry_on()
    assert waited_for(lambda: any(one.state == RUNNING for one in told.snapshots))
    control.pause()
    assert control.settled()
    assert told.last.stopped.reason == "paused"
    assert told.last.state == STANDING  # it stands, and the run may go on
    assert told.last.instructions > 0


def test_a_paused_run_carries_on(control, told, tmp_path):
    opened(control, tmp_path, FOREVER)
    control.carry_on()
    assert waited_for(lambda: any(one.state == RUNNING for one in told.snapshots))
    control.pause()
    assert control.settled()
    far = told.last.instructions
    control.carry_on()
    assert waited_for(lambda: told.last.instructions > far)
    control.pause()
    assert control.settled()
    assert told.last.instructions > far


def test_a_run_told_to_stop_is_over(control, told, tmp_path):
    """`pause` lets the machine stand and the run go on; `stop` is the end of that
    run, as it is in RARS, and a restart is what follows."""
    opened(control, tmp_path, FOREVER)
    control.carry_on()
    assert waited_for(lambda: any(one.state == RUNNING for one in told.snapshots))
    control.stop()
    assert control.settled()
    assert told.last.state == ENDED
    control.step()
    assert control.settled()
    assert told.last.stopped.reason == "ended"
    control.restart()
    assert control.settled()
    assert told.last.state == STANDING  # and a restart brings it back


def test_a_step_back_reaches_over_a_run_that_was_stopped(control, told, tmp_path):
    opened(control, tmp_path)
    control.carry_on()
    control.back(2)
    control.step()
    assert control.settled()
    assert told.last.stopped.reason == "stepped"


# ------------------------------------------------------------ on to a place


def test_a_run_on_to_a_place_by_its_name(control, told, tmp_path):
    """A window has a line of a file and not an address, so a place may be said
    in words; the naming is done in the thread of the run, because that is where
    the program is."""
    opened(control, tmp_path)
    control.until("keep")
    assert control.settled()
    assert told.last.place.line == 14  # `keep:   la t0, total`
    assert told.last.instructions == 2 + 3 * 3 + 1


def test_a_run_on_to_a_line_of_a_file(control, told, tmp_path):
    opened(control, tmp_path)
    control.until(f"{tmp_path / 'main.s'}:9")  # the `bne` of the first turn
    assert control.settled()
    assert told.last.place.line == 9
    assert told.last.instructions == 4


def test_a_run_on_to_an_address(control, told, tmp_path):
    opened(control, tmp_path)
    control.until(control.program.symbols["keep"])
    assert control.settled()
    assert told.last.place.line == 14


def test_a_run_on_to_a_place_that_is_nowhere(control, told, tmp_path):
    """A line with no instruction on it cannot be run to, and nothing of the run
    changes because somebody asked."""
    opened(control, tmp_path)
    control.until(f"{tmp_path / 'main.s'}:2")  # `.data` is no instruction
    assert control.settled()
    assert told.failures[-1].what == "until"
    assert "no instruction of the program is there" in told.failures[-1].message
    assert told.last.instructions == 0


# --------------------------------------------------------- the speed of a run


def test_a_run_is_held_back_to_the_speed_it_was_given(told, tmp_path):
    """Fifty a second means fifty a second: the whole program is eighteen
    instructions, so it takes about a third of a second instead of no time at
    all."""
    with RunController(told, out=io.StringIO(), speed=50) as control:
        opened(control, tmp_path)
        began = time.monotonic()
        control.carry_on()
        assert control.settled(20)
        took = time.monotonic() - began
    assert told.last.instructions == WHOLE
    assert took >= (WHOLE - 2) / 50  # the ceiling is kept
    assert took < 4 * WHOLE / 50  # and nothing waits longer than it was told to


def test_the_pace_is_counted_from_when_each_instruction_was_due(told, tmp_path):
    """What a turn itself took is part of what that turn was given.

    Here half of every interval goes on answering a watched question. A pace
    counted from NOW instead of from when the last instruction was due would add
    that half to the whole of every interval and take half as long again - and
    would go on drifting with anything else the turn had to do.
    """
    def slowly(session):
        time.sleep(0.01)
        return session.count().instructions

    with RunController(told, out=io.StringIO(), every=0, speed=50) as control:
        opened(control, tmp_path)
        control.watching = {"slowly": slowly}
        began = time.monotonic()
        control.carry_on()
        assert control.settled(20)
        took = time.monotonic() - began
    assert told.last.instructions == WHOLE
    assert (WHOLE - 2) / 50 <= took < 1.25 * WHOLE / 50


def test_a_step_is_a_step_however_slow_the_run_is(told, tmp_path):
    """A speed holds a RUN back; it does not make somebody who presses Step wait a
    second to see what they did.

    The turn is told of an instruction once it has been carried out, so the first
    turn of every movement waits for nothing: five steps at twenty a second are
    five steps and no waiting at all.
    """
    with RunController(told, out=io.StringIO(), speed=20) as control:
        opened(control, tmp_path)
        began = time.monotonic()
        for _ in range(5):
            control.step()
        assert control.settled(20)
        took = time.monotonic() - began
    assert told.last.instructions == 5
    assert took < 5 * 0.05 / 2  # five intervals would be a quarter of a second


def test_a_run_at_no_speed_at_all_is_as_fast_as_it_can_be(control, told, tmp_path):
    """Nothing is held back unless somebody asks for it; the loop pays one
    comparison a turn for the asking."""
    opened(control, tmp_path)
    began = time.monotonic()
    control.carry_on()
    assert control.settled()
    assert time.monotonic() - began < WHOLE / 50
    assert told.last.instructions == WHOLE


def test_a_run_that_stood_still_does_not_race_to_make_up_for_it(told, tmp_path):
    """A slowed run that waited for a line owes nothing for the waiting.

    The pace is counted from when the last instruction was DUE, so that it does
    not drift; but a run that has fallen behind begins counting again from now.
    Otherwise half a second of standing in the input would be repaid at the top
    speed of the machine, which is the opposite of what a slow run is for.
    """
    with RunController(told, out=io.StringIO(), speed=10) as control:
        opened(control, tmp_path, ASKS)
        control.carry_on()
        assert waited_for(lambda: control.state == WAITING)
        time.sleep(0.5)  # half a second owed: five instructions at this speed
        answered = time.monotonic()
        control.answer("7")
        assert control.settled(20)
        after = time.monotonic() - answered
    assert told.last.state == ENDED
    assert after >= 0.15  # what was left was still carried out at ten a second


def test_a_speed_may_be_changed_while_the_run_goes_on(told, tmp_path):
    """It is read every turn, so a slider may be moved while a program runs."""
    with RunController(told, out=io.StringIO()) as control:
        opened(control, tmp_path, FOREVER)
        control.carry_on()
        assert waited_for(lambda: told.last.instructions > 1000)  # its own speed
        control.speed = 5
        time.sleep(0.2)  # whatever was in the air at the old speed
        counted = told.last.instructions
        time.sleep(0.6)
        crawled = told.last.instructions - counted
        control.stop()
        assert control.settled()
    # Three a second there or thereabouts, against the twenty thousand a second it
    # was going at: what this has to tell apart is a HANDFUL from a torrent. There
    # is no bound below, because the machine running the test may be busy with
    # something else and give the thread of the run no turn at all in half a second
    # (both bounds were tried and both flaked under the whole suite); that a slowed
    # run moves at all is what the two tests above this one are for.
    assert crawled <= 30


# ----------------------------------------------------------- what is watched


def test_what_is_watched_is_answered_with_every_snapshot(told, tmp_path):
    """A window that slows a run down wants to see the machine change, and cannot
    ask for it while the run goes on: a question would wait in the queue behind
    the movement. So it is answered by the thread of the run itself."""
    with RunController(told, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path)
        control.watching = {"counted": lambda session: session.count().instructions}
        control.step(5)
        assert control.settled()
    running = [one for one in told.snapshots if one.state == RUNNING]
    assert [one.value for one in told.answers if one.what == "counted"] \
        == [1, 2, 3, 4, 5]  # every turn, the instruction of that turn done
    assert len(running) == 5


def test_nothing_is_watched_unless_somebody_asks(control, told, tmp_path):
    opened(control, tmp_path)
    control.step(5)
    assert control.settled()
    assert control.watching == {}
    assert [one.what for one in told.answers] == [LOAD]


def test_a_watched_question_that_cannot_be_answered_is_let_go(told, tmp_path):
    """Thirty of the same complaint a second say nothing a window can use, and the
    run is none the worse for the asking."""
    def throws(session):
        raise ValueError("nothing like it")

    with RunController(told, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path)
        control.watching = {"broken": throws}
        control.step(5)
        assert control.settled()
        assert control.watching == {}
    assert [(one.what, one.message) for one in told.failures] \
        == [("broken", "nothing like it")]
    assert told.last.state == STANDING and told.last.instructions == 5


# ------------------------------------------------------- the world outside

# A program that waits for a key of the FIRST ROW of the digital lab (which is the
# keys 0 to 3, for the keyboard answers about one row at a time) and stops once it
# has one.
WAITS_FOR_A_KEY = """\
.globl main
.text
main:   li      s0, 0xffff0010
        li      t0, 1
look:   sb      t0, 2(s0)
        lbu     t1, 4(s0)
        beq     t1, zero, look
        li      a7, 10
        ecall
"""


def test_a_key_pressed_while_the_program_runs(told, tmp_path):
    """The one moment a key matters: a program is RUNNING and polling for it. So
    it does not wait in the queue of work - which is not looked at again until the
    movement ends - but in a queue of its own that the thread empties every turn.
    """
    with RunController(told, out=io.StringIO(), speed=500) as control:
        opened(control, tmp_path, WAITS_FOR_A_KEY, bus=DeviceBus([make("lab")]))
        control.carry_on()
        assert waited_for(lambda: control.state == RUNNING)
        control.press("lab", 1)
        assert control.settled(20)
    assert told.last.state == ENDED  # the program saw the key and ended
    answers = [one for one in told.answers if one.what == DEVICE]
    assert answers and answers[-1].value.looks["key"] == 1


def test_a_key_pressed_while_nothing_is_happening(control, told, tmp_path):
    """The thread may be sitting on the queue of work with nothing to do, so a
    nudge goes through that queue as well."""
    opened(control, tmp_path, bus=DeviceBus([make("lab")]))
    control.press("lab", 2)
    assert control.settled()
    answers = [one for one in told.answers if one.what == DEVICE]
    assert len(answers) == 1
    assert answers[0].value.state["key down"] == 2


def test_a_key_that_cannot_be_pressed_while_the_program_runs(told, tmp_path):
    """A press is done IN the loop of the run, so one that cannot be done must be
    caught there: an error let out of that would end the movement and take the run
    with it."""
    with RunController(told, out=io.StringIO(), speed=500) as control:
        opened(control, tmp_path, WAITS_FOR_A_KEY, bus=DeviceBus([make("lab")]))
        control.carry_on()
        assert waited_for(lambda: control.state == RUNNING)
        control.press("keyboard", 1)  # nothing of that name is attached
        assert waited_for(lambda: bool(told.failures))
        assert control.state == RUNNING  # and the run is none the worse
        control.press("lab", 1)
        assert control.settled(20)
    assert told.last.state == ENDED
    assert [one.what for one in told.failures] == [DEVICE]


def test_a_key_of_a_device_nobody_attached(control, told, tmp_path):
    """It comes back as a question that could not be answered, like any other, and
    the thread of the run is none the worse for it."""
    opened(control, tmp_path)
    control.press("lab", 0)
    assert control.settled()
    assert [one.what for one in told.failures] == [DEVICE]
    assert "no device of that name" in told.failures[0].message
    control.step()
    assert control.settled()
    assert told.last.instructions == 1


# ------------------------------------------------------------- the snapshots


def test_a_snapshot_goes_out_no_oftener_than_it_was_asked_to(told, tmp_path):
    """Thirty a second is what a window asks for; a test asks for one an hour and
    for one a turn, which is the same comparison answered both ways."""
    with RunController(told, out=io.StringIO(), every=3600) as control:
        opened(control, tmp_path)
        control.step(10)
        assert control.settled()
    while_running = [one for one in told.snapshots if one.state == RUNNING]
    assert len(while_running) == 1  # the first turn, and then not again for an hour

    often = Told()
    with RunController(often, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path)
        control.step(10)
        assert control.settled()
    assert len([one for one in often.snapshots if one.state == RUNNING]) == 10


def test_the_thread_gives_the_interpreter_up_with_every_snapshot(told, tmp_path):
    """And with every snapshot only, not with every instruction.

    A thousandth of a second given up is what lets whoever owns a main loop have
    the interpreter at all (see `YIELD`); given up per INSTRUCTION it would divide
    the speed of the machine by thirty. So: a run that sends a snapshot a turn
    takes at least a millisecond a turn, and a run that sends one an hour takes no
    time at all.
    """
    from pyrars.session.control import YIELD

    with RunController(told, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path)
        began = time.monotonic()
        control.carry_on()
        assert control.settled(20)
        often = time.monotonic() - began
    assert told.last.instructions == WHOLE
    assert often >= (WHOLE - 1) * YIELD

    with RunController(told, out=io.StringIO(), every=3600) as control:
        opened(control, tmp_path)
        began = time.monotonic()
        control.carry_on()
        assert control.settled(20)
        seldom = time.monotonic() - began
    assert seldom < WHOLE * YIELD  # one snapshot, one millisecond given up


def test_a_run_that_is_slowed_gives_way_by_being_slow(told, tmp_path):
    """A run held back to a speed sleeps between its instructions, so it is not
    made to give up anything besides: the pace it was asked for is the pace it
    keeps."""
    with RunController(told, out=io.StringIO(), every=0, speed=200) as control:
        opened(control, tmp_path)
        began = time.monotonic()
        control.carry_on()
        assert control.settled(20)
        took = time.monotonic() - began
    # eighteen instructions at two hundred a second is a tenth of a second; a
    # millisecond given up on top of each would be a fifth
    assert took < 1.5 * WHOLE / 200


def test_nothing_more_is_said_until_the_last_was_heard(told, tmp_path):
    """Whoever is told does work for every snapshot, and a machine at its own
    speed can say more than any window can answer for. So one who asks to be
    waited for is waited for."""
    with RunController(told, out=io.StringIO(), every=0, waits=True) as control:
        opened(control, tmp_path, FOREVER)
        control.carry_on()
        assert waited_for(lambda: len(told.snapshots) >= 2)
        held = len(told.snapshots)
        time.sleep(0.1)  # a tenth of a second of a run without an end
        assert len(told.snapshots) == held  # and not a word more
        control.heard()
        assert waited_for(lambda: len(told.snapshots) == held + 1)
        time.sleep(0.05)
        assert len(told.snapshots) == held + 1
        control.stop()
        assert control.settled()
    # the snapshot a movement ENDS on is not held back by anybody: a window must
    # be told that the machine has stopped
    assert told.last.state == ENDED


def test_the_snapshot_is_the_last_word_of_a_batch(told, tmp_path):
    """Whoever is told says it has HEARD when it has the snapshot, so by then it
    must have had everything that came with it: the answers of what is being
    watched go out first and the snapshot closes the batch."""
    with RunController(told, out=io.StringIO(), every=0, waits=True) as control:
        opened(control, tmp_path)
        control.watching = {"counted": lambda session: session.count().instructions}
        control.step(1)
        assert control.settled()
    kinds = [(type(one).__name__, getattr(one, "what", getattr(one, "state", "")))
             for one in told.events]
    answered = kinds.index(("Answer", "counted"))
    snapshot = next(index for index, one in enumerate(kinds)
                    if one == ("Snapshot", RUNNING))
    assert answered < snapshot


def test_whoever_does_not_ask_to_be_waited_for_is_told_as_often_as_ever(told,
                                                                       tmp_path):
    """A test, a script, anything that only keeps what it is told: the loop says
    what it has to say and does not wait for an answer."""
    with RunController(told, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path)
        control.step(5)
        assert control.settled()
    assert len([one for one in told.snapshots if one.state == RUNNING]) == 5


def test_every_movement_says_at_once_that_it_is_running(told, tmp_path):
    """However seldom snapshots go out, each movement says where it is as it
    begins: a window that was told to carry on must not look as if nothing
    happened until the next snapshot is due."""
    with RunController(told, out=io.StringIO(), every=3600) as control:
        opened(control, tmp_path)
        control.step(3)
        control.step(3)
        control.step(3)
        assert control.settled()
    assert len([one for one in told.snapshots if one.state == RUNNING]) == 3


def test_a_snapshot_asked_for(control, told, tmp_path):
    """A window that has just been opened asks where things are, and is told -
    whether anything is open or not."""
    control.look()
    assert control.settled()
    assert told.snapshots == [Snapshot(NOTHING)]
    opened(control, tmp_path)
    control.step(2)
    control.look()
    assert control.settled()
    assert told.last.state == STANDING
    assert told.last.instructions == 2
    assert told.last.stopped is None  # nothing moved: it is only a picture


def test_a_snapshot_holds_what_is_wanted_at_every_moment(control, told, tmp_path):
    opened(control, tmp_path)
    control.step(5)
    assert control.settled()
    shot = told.last
    assert shot.place.basic and shot.place.source  # where the machine stands
    assert (shot.instructions, shot.back) == (5, 5)
    assert shot.turns == 0  # no statistics were asked for
    assert shot.state == STANDING


def test_the_models_a_controller_was_asked_for(control, told, tmp_path):
    """What a session is built with is handed to it here, so a window asks for the
    models the same way the command line does."""
    opened(control, tmp_path, statistics=True)
    control.carry_on()
    control.ask("stats", lambda session: session.models.statistics.instructions)
    assert control.settled()
    # the turn that ended the run reached no model: it did nothing to count
    assert told.last.turns == WHOLE
    assert told.answers[-1].value == WHOLE


# ------------------------------------------------------------------ one thread


def test_everything_happens_in_one_thread_and_not_the_one_that_asked(control, told,
                                                                     tmp_path):
    """INV-T: nothing but the thread of the run touches the machine or the session
    around it. Every event comes from that thread, and so does every question."""
    opened(control, tmp_path)
    asking = threading.get_ident()
    seen: list[int] = []
    control.ask("thread", lambda session: seen.append(threading.get_ident()))
    control.step(3)
    control.carry_on()
    assert control.settled()
    assert len(told.threads) == 1  # one thread told us everything
    assert asking not in told.threads  # and it was not ours
    assert seen == list(told.threads)  # the question was answered in it too


def test_a_controller_closes_while_a_program_runs(told, tmp_path):
    """Closing must not wait for a program without an end: the run is told to stop
    and the thread ends."""
    control = RunController(told, out=io.StringIO())
    opened(control, tmp_path, FOREVER)
    control.carry_on()
    assert waited_for(lambda: any(one.state == RUNNING for one in told.snapshots))
    control.close()
    assert control._thread.is_alive() is False


def test_the_thread_ends_because_it_was_told_to(told, tmp_path):
    """Closing is not a thread falling over: nothing is raised in it, and it says
    that it ended on the word rather than on an accident. A window that closes must
    not spill a traceback down the terminal it was started from."""
    raised = []
    control = RunController(told, out=io.StringIO())
    before = threading.excepthook
    threading.excepthook = raised.append
    try:
        opened(control, tmp_path)
        control.step()
        assert control.settled()
        control.close()
    finally:
        threading.excepthook = before
    assert raised == []
    assert control.closed is True
    assert control._thread.is_alive() is False


def test_closing_a_controller_twice_is_no_trouble(control, told, tmp_path):
    opened(control, tmp_path)
    control.close()
    control.close()


# -------------------------------------------------- the program asks for a line


def test_a_program_waiting_for_a_line(control, told, tmp_path):
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: any(one.what == ASKING for one in told.answers))
    assert control.settled(0.2) is False  # it is waiting, and it waits
    control.answer("Ann")
    assert control.settled()
    assert told.last.stopped.reason == "exited"


def test_a_program_waiting_is_a_state_of_its_own(control, told, tmp_path):
    """Nothing of the machine goes on while a program waits for a line, and a
    window that said "running" would be offering to pause something that is not
    going anywhere."""
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    assert told.last.state == WAITING
    assert told.last.place is not None  # and it still says where the machine is
    control.answer("Ann")
    assert control.settled()
    assert WAITING not in [one.state for one in told.snapshots[-1:]]
    assert told.last.stopped.reason == "exited"


def test_a_line_given_puts_the_run_back_on_its_way(told, tmp_path):
    """The moment the line is taken, the run is going again - and every snapshot
    from then on says so. One that still said "waiting" would have a window
    offering to stop something that is already on its way."""
    with RunController(told, out=io.StringIO(), every=0) as control:
        opened(control, tmp_path, ASKS)
        control.carry_on()
        assert waited_for(lambda: control.state == WAITING)
        waiting = len(told.snapshots)
        control.answer("Ann")
        assert control.settled()
    after = [one.state for one in told.snapshots[waiting:]]
    assert after  # the run went on, and said so more than once
    assert WAITING not in after
    assert RUNNING in after


def test_a_run_stopped_while_it_waited_may_be_taken_back_and_gone_on_with(
        control, told, tmp_path):
    """Ending a run ends its input. A step back reaches over the end of a run, so
    what follows must be able to ask for a line again - otherwise the program
    would meet the end of its input the moment it asked."""
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.stop()
    assert control.settled()
    control.back(2)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.answer("Ann")
    assert control.settled()
    assert told.last.stopped.reason == "exited"


def test_a_run_waiting_for_a_line_can_still_be_stopped(control, told, tmp_path):
    """The flag that stops the loop would never be read: the thread is standing in
    the input, not in the machine. Ending the input is what wakes it."""
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.stop()
    assert control.settled()
    assert told.last.state == ENDED
    assert told.last.stopped.reason == "stopped"


def test_what_a_stopped_run_says_is_that_it_was_stopped(control, told, tmp_path):
    """The program is woken by its input ending, and what it makes of that - here,
    a number it cannot read - never reaches the person: the loop of the machine
    sees the flag before the next instruction and ends the run as a STOP."""
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.stop()
    assert control.settled()
    assert told.last.stopped.message == ""  # not what the program made of it


def test_a_run_that_begins_again_may_be_spoken_to_again(control, told, tmp_path):
    """Ending a run ends its input; the next one has an input of its own, or
    nothing could ever be typed after a stop."""
    opened(control, tmp_path, ASKS)
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.stop()
    assert control.settled()
    control.restart()
    control.carry_on()
    assert waited_for(lambda: control.state == WAITING)
    control.answer("Ann")
    assert control.settled()
    assert told.last.stopped.reason == "exited"


def test_a_program_asking_when_there_is_no_more_input(control, told, tmp_path):
    opened(control, tmp_path, ASKS)
    control.no_more_input()
    control.carry_on()
    assert control.settled()
    assert told.last.stopped.reason == "exited"
    assert not [one for one in told.answers if one.what == ASKING]


def test_what_the_program_was_given_is_what_it_read(told, tmp_path):
    """The program reads what was answered and writes to the streams the caller
    gave: a window shows the one and types the other."""
    out = io.StringIO()
    back = ASKS.replace("li a7, 93", "li a7, 4\n        la a0, buffer\n"
                        "        ecall\n        li a7, 93")
    with RunController(told, out=out) as inner:
        opened(inner, tmp_path, back)
        inner.carry_on()
        assert waited_for(lambda: any(one.what == ASKING for one in told.answers))
        inner.answer("Ann")
        assert inner.settled()
    assert "Ann" in out.getvalue()


# ------------------------------------------------------- waiting for an answer


def ended_with(*answers: str) -> Waiting:
    """Something to read, and nothing after it. The input is ended at once so that
    no test here can be made to wait for ever by a reader that is wrong: what is
    being tested is what it does with what it was given."""
    waiting = Waiting()
    for answer in answers:
        waiting.answer(answer)
    waiting.ended()
    return waiting


def test_a_line_answered_before_it_was_asked_for():
    waiting = ended_with("Ann")
    assert waiting.readline() == "Ann\n"


def test_an_answer_that_already_ends_its_line():
    waiting = ended_with("Ann\n")
    assert waiting.readline() == "Ann\n"


def test_two_lines_answered_at_once():
    waiting = ended_with("one\ntwo")
    assert waiting.readline() == "one\n"
    assert waiting.readline() == "two\n"


def test_characters_taken_from_what_was_answered():
    waiting = ended_with("Ann")
    assert waiting.read(2) == "An"
    assert waiting.read(2) == "n\n"


def test_the_end_of_the_input():
    waiting = Waiting()
    waiting.ended()
    assert waiting.readline() == ""
    assert waiting.read(4) == ""


def test_what_was_answered_outlives_the_end_of_the_input():
    """The input ending does not throw away what somebody had already typed: the
    program reads it, and sees the end after it."""
    waiting = Waiting()
    waiting.answer("one")
    waiting.answer("two")
    waiting.ended()
    assert waiting.readline() == "one\n"
    assert waiting.readline() == "two\n"
    assert waiting.readline() == ""


def test_the_input_may_end_while_the_program_waits():
    """A reader waiting for a line nobody is going to give it is woken by the end
    of the input - otherwise a window could not be closed while its program waits.
    """
    waiting = Waiting()
    read = []
    reader = threading.Thread(target=lambda: read.append(waiting.readline()),
                              daemon=True)
    reader.start()
    assert waited_for(lambda: waiting.lines.empty())  # it is waiting by now
    waiting.ended()
    reader.join(5)
    assert read == [""]


def test_whoever_waits_is_asked_only_while_there_is_something_to_wait_for():
    asked = []
    waiting = Waiting(asked=lambda: asked.append(1))
    waiting.answer("Ann")
    assert waiting.readline() == "Ann\n"
    assert asked == []  # the answer was already there: nobody was asked
    waiting.ended()
    assert waiting.readline() == ""
    assert asked == []
