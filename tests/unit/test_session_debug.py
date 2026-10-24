"""A session of debugging: the commands, and the data they answer with.

Nothing here is compared with RARS, and nothing can be: RARS debugs in its window
only, so its back step is all we could borrow and that was borrowed at stage 21.
Every expected value is worked out by hand from the program - its addresses from
the text base and four bytes to an instruction, its counts from what each turn of
its loop carries out - and written into the test beside the value.

The three commands that guess are tested as guesses (D21): `over` and `finish` and
the frames read the return address the way the convention says, and the test of
the recursion is what shows why a depth is checked at all.
"""

import io

import pytest

from pyrars.analysis.cache import Caches, Settings as CacheSettings
from pyrars.analysis.pipeline import Pipeline, Settings as PipelineSettings
from pyrars.analysis.predictors import History as Table
from pyrars.asm.assembler import Options as AsmOptions, assemble
from pyrars.core.systemio import ConsoleIO
from pyrars.devices import DeviceBus, make
from pyrars.isa.memory import DEFAULT
from pyrars.session.debug import (
    BREAKPOINT, EXITED, NOTHING, STEPPED, WATCHPOINT, Session)

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base

# Four words summed in a loop, kept by a subroutine. `la` is two instructions, so
# the addresses run: main 0x400000, loop 0x400010, the call 0x400024, keep 0x400034.
SUM = """\
.globl main
.data
table:  .word 1, 2, 3, 4
total:  .word 0
msg:    .asciz "hi"
.text
main:   la t0, table
        li t1, 4
        li t2, 0
loop:   lw t3, 0(t0)
        add t2, t2, t3
        addi t0, t0, 4
        addi t1, t1, -1
        bne t1, x0, loop
        jal ra, keep
        li a7, 93
        li a0, 0
        ecall
keep:   la t0, total
        sw t2, 0(t0)
        ret
"""
MAIN, LOOP, CALL, AFTER, KEEP = TEXT, TEXT + 0x10, TEXT + 0x24, TEXT + 0x28, TEXT + 0x34
SW, RET = TEXT + 0x3C, TEXT + 0x40
TABLE, TOTAL, MSG = DATA, DATA + 16, DATA + 20
SETUP = 4  # la (two) and two li
TURN = 5  # lw, add, addi, addi, bne
WHOLE = SETUP + 4 * TURN + 1 + 4 + 2  # the loop four times, the call, keep, the exit

# A subroutine that calls itself, so that a depth can be looked at.
DOWN = """\
.globl main
.text
main:   li a0, 2
        jal ra, down
        li a7, 93
        li a0, 0
        ecall
down:   addi sp, sp, -8
        sw ra, 0(sp)
        sw a0, 4(sp)
        beq a0, x0, up
        addi a0, a0, -1
        jal ra, down
up:     lw ra, 0(sp)
        lw a0, 4(sp)
        addi sp, sp, 8
        ret
"""
CALLS_ITSELF, UP, GOES_BACK = TEXT + 0x28, TEXT + 0x2C, TEXT + 0x14


def session(source: str, tmp_path, io_=None, **kept) -> Session:
    """A session over an assembled program, writing into a string."""
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions())
    assert program.diagnostics == (), program.diagnostics
    world = io_ if io_ is not None else ConsoleIO(
        out=io.StringIO(), errors=io.StringIO(), reader=io.StringIO())
    return Session(program, io=world, **kept)


@pytest.fixture
def sum_session(tmp_path):
    return session(SUM, tmp_path)


# ---------------------------------------------------------------- the movement


def test_a_session_begins_where_the_program_does(sum_session):
    here = sum_session.where()
    assert here.address == MAIN
    assert here.symbol == "main"
    assert here.source == "main:   la t0, table"
    assert here.line == 7  # the seventh line of the program text
    assert sum_session.count().instructions == 0


def test_one_step_at_a_time(sum_session):
    stopped = sum_session.step()
    assert (stopped.reason, stopped.steps) == (STEPPED, 1)
    assert stopped.place.address == MAIN + 4  # the second half of the `la`


def test_many_steps_at_once(sum_session):
    stopped = sum_session.step(SETUP)
    assert (stopped.reason, stopped.steps) == (STEPPED, SETUP)
    assert stopped.place.address == LOOP
    assert stopped.place.symbol == "loop"


def test_a_breakpoint_cuts_a_walk_short(sum_session):
    sum_session.add_break(LOOP)
    stopped = sum_session.step(100)
    assert stopped.reason == BREAKPOINT
    assert stopped.steps == SETUP  # it stopped before the instruction at the place
    assert stopped.place.address == LOOP
    assert stopped.breakpoint == 1


def test_a_walk_that_ends_on_a_breakpoint_of_its_own_accord(sum_session):
    """A movement that carried out everything it was asked for answers with what it
    did, not with the place it happens to have arrived at: the breakpoint is the
    reason a movement was CUT SHORT, and this one was not."""
    sum_session.add_break(LOOP)
    stopped = sum_session.step(SETUP)
    assert (stopped.reason, stopped.breakpoint) == (STEPPED, None)
    assert stopped.place.address == LOOP


def test_over_a_return_which_is_no_call(sum_session):
    """`over` passes over a call, and a return is not one however alike they look:
    both are jumps, and only the one that keeps a return address is a call."""
    sum_session.add_break(RET)
    sum_session.carry_on()
    stopped = sum_session.over()
    assert (stopped.reason, stopped.steps) == (STEPPED, 1)
    assert stopped.place.address == AFTER  # out of the subroutine, one step


def test_a_run_to_the_end(sum_session):
    stopped = sum_session.carry_on()
    assert (stopped.reason, stopped.code) == (EXITED, 0)
    # every instruction but the `ecall` that ended the run
    assert stopped.steps == WHOLE
    assert sum_session.machine.memory.peek(TOTAL, 4) == 1 + 2 + 3 + 4


def test_a_run_to_a_breakpoint(sum_session):
    broken = sum_session.add_break(KEEP)
    assert broken.place.symbol == "keep"
    stopped = sum_session.carry_on()
    assert stopped.reason == BREAKPOINT
    assert stopped.breakpoint == broken.id
    assert stopped.steps == SETUP + 4 * TURN + 1  # the loop, then the call itself
    assert stopped.place.address == KEEP


def test_a_run_carries_on_from_where_it_stopped(sum_session):
    sum_session.add_break(LOOP)
    assert sum_session.carry_on().steps == SETUP
    # standing on the breakpoint, a run does not stop on it again at once
    assert sum_session.carry_on().steps == TURN
    assert sum_session.where().address == LOOP


def test_a_step_back(sum_session):
    sum_session.step(SETUP)
    stopped = sum_session.back()
    assert (stopped.reason, stopped.steps) == (STEPPED, 1)
    assert stopped.place.address == LOOP - 4
    assert sum_session.count().instructions == SETUP - 1


def test_many_steps_back_and_the_beginning(sum_session):
    sum_session.step(SETUP)
    assert sum_session.back(100).steps == SETUP  # as many as it had
    assert sum_session.where().address == MAIN
    assert sum_session.back().reason == NOTHING  # and nothing left to take back


def test_until_a_place_exactly(sum_session):
    stopped = sum_session.until(LOOP)
    assert (stopped.reason, stopped.steps) == (STEPPED, SETUP)
    assert stopped.place.address == LOOP
    assert sum_session.breaks() == []  # the place it was asked to reach is not one


def test_over_a_call(sum_session):
    sum_session.until(CALL)
    stopped = sum_session.over()
    # the call, the two halves of `la`, the `sw` and the `ret`
    assert (stopped.reason, stopped.steps) == (STEPPED, 5)
    assert stopped.place.address == AFTER
    assert sum_session.frames() == []  # it came back out


def test_over_what_is_not_a_call(sum_session):
    stopped = sum_session.over(2)
    assert (stopped.reason, stopped.steps) == (STEPPED, 2)
    assert stopped.place.address == MAIN + 8  # exactly as stepping would


def test_finish_the_call_the_run_is_inside(sum_session):
    sum_session.add_break(SW)
    sum_session.carry_on()
    assert [frame.called.symbol for frame in sum_session.frames()] == ["keep"]
    stopped = sum_session.finish()
    assert (stopped.reason, stopped.steps) == (STEPPED, 2)  # the `sw` and the `ret`
    assert stopped.place.address == AFTER


def test_finish_outside_any_call(sum_session):
    assert sum_session.finish().reason == NOTHING


def test_a_run_that_was_stopped_is_told_from_one_that_was_paused(sum_session):
    """Two different things happened, and a front end has to be able to say which:
    a paused run goes on from where it stands, a stopped one does not."""
    from pyrars.core.simulator import Stop, StopReason
    from pyrars.session.debug import PAUSED, REASONS, STOPPED

    assert REASONS[StopReason.PAUSE] == PAUSED
    assert REASONS[StopReason.STOP] == STOPPED
    # Neither can be asked for from here: the loop clears both flags as it begins,
    # so only another thread can pause or stop a run that is already going. What
    # the two REASONS come to is held in the tests of the controller.
    assert sum_session._ended(Stop(StopReason.STOP, 0), 3).reason == STOPPED
    assert sum_session._ended(Stop(StopReason.PAUSE, 0), 3).reason == PAUSED


def test_a_movement_knows_a_run_that_ended(sum_session):
    sum_session.until(TEXT + 0x30)  # standing on the `ecall` that exits
    stopped = sum_session.step()
    assert (stopped.reason, stopped.code, stopped.steps) == (EXITED, 0, 0)


# ------------------------------------------------- the guesses, and a recursion


def test_over_a_call_that_calls_itself(tmp_path):
    """The one place a depth has to be looked at: `up` is where a recursive call
    comes back to, so the run reaches the place the movement waits for once for
    every call still open. Only the one at the depth it started from ends it.
    """
    s = session(DOWN, tmp_path)
    s.until(CALLS_ITSELF)  # inside the first call, about to make the second
    assert len(s.frames()) == 1
    stopped = s.over()
    assert stopped.place.address == UP
    assert len(s.frames()) == 1  # back at the depth it started from
    assert s.machine.x.read(10) == 1  # a0: the value this call was given


def test_finish_out_of_a_recursion(tmp_path):
    s = session(DOWN, tmp_path)
    s.add_break(GOES_BACK)
    s.carry_on()  # the first call
    s.remove_break()
    stopped = s.finish()
    assert stopped.place.address == TEXT + 8  # the instruction after the call
    assert s.frames() == []
    assert s.machine.x.read(10) == 2  # a0 put back by every epilogue on the way out


def test_the_frames_are_a_guess_from_the_convention(sum_session):
    sum_session.add_break(KEEP)
    sum_session.carry_on()
    frames = sum_session.frames()
    assert len(frames) == 1
    assert frames[0].depth == 1
    assert frames[0].called.address == KEEP
    assert frames[0].called_from.address == CALL
    assert frames[0].called_from.source == "        jal ra, keep"
    assert frames[0].sp == sum_session.machine.x.read(2)


# -------------------------------------------------------------- the breakpoints


def test_breakpoints_come_and_go(sum_session):
    first = sum_session.add_break(LOOP)
    second = sum_session.add_break(KEEP)
    assert (first.id, second.id) == (1, 2)
    assert [one.place.address for one in sum_session.breaks()] == [LOOP, KEEP]
    assert [one.id for one in sum_session.remove_break(1)] == [1]
    assert [one.place.address for one in sum_session.breaks()] == [KEEP]
    assert [one.id for one in sum_session.remove_break()] == [2]
    assert sum_session.breaks() == []


def test_a_breakpoint_that_is_not_there(sum_session):
    sum_session.add_break(LOOP)
    with pytest.raises(ValueError, match="there is no breakpoint 7"):
        sum_session.remove_break(7)
    assert len(sum_session.breaks()) == 1  # and the one that is there stands


def test_a_breakpoint_carries_everything_about_its_place(sum_session):
    broken = sum_session.add_break(LOOP)
    assert broken.place.symbol == "loop"
    assert broken.place.basic == "lw x28,0(x5)"
    assert broken.place.source == "loop:   lw t3, 0(t0)"


# ------------------------------------------------------------- what is watched


def test_a_watched_word_that_is_written(sum_session):
    watched = sum_session.add_watch(TOTAL, TOTAL + 3, "write")
    stopped = sum_session.carry_on()
    assert stopped.reason == WATCHPOINT
    assert len(stopped.touched) == 1
    touched = stopped.touched[0]
    assert (touched.id, touched.kind) == (watched.id, "write")
    assert (touched.address, touched.size, touched.value) == (TOTAL, 4, 10)
    assert touched.by == SW  # the instruction that did it
    assert sum_session.where().address == RET  # which was carried out
    assert sum_session.watches()[0].hits == 1


def test_a_watched_word_that_is_read(sum_session):
    sum_session.add_watch(TABLE, TABLE + 3, "read")
    stopped = sum_session.carry_on()
    assert stopped.reason == WATCHPOINT
    assert stopped.touched[0].kind == "read"
    assert stopped.touched[0].value == 1  # the first word of the table
    assert stopped.touched[0].by == LOOP  # the `lw`
    assert stopped.steps == SETUP + 1


def test_a_watched_word_is_not_watched_for_the_other_thing(sum_session):
    sum_session.add_watch(TABLE, TABLE + 3, "write")  # nothing ever writes there
    assert sum_session.carry_on().reason == EXITED


def test_a_watch_that_is_taken_off(sum_session):
    watched = sum_session.add_watch(TOTAL, TOTAL + 3, "both")
    assert [one.id for one in sum_session.remove_watch(watched.id)] == [watched.id]
    assert sum_session.watches() == []
    assert sum_session.carry_on().reason == EXITED  # and nothing stops the run


def test_a_watch_of_a_whole_range_counts_every_touch(sum_session):
    sum_session.add_watch(TABLE, TABLE + 15, "read")
    for expected in (1, 2, 3, 4):
        stopped = sum_session.carry_on()
        assert stopped.touched[0].value == expected
    assert sum_session.watches()[0].hits == 4


def test_a_watch_asked_for_wrongly(sum_session):
    with pytest.raises(ValueError, match="read, write or both"):
        sum_session.add_watch(TOTAL, TOTAL + 3, "both ways")
    with pytest.raises(ValueError, match="the lower one"):
        sum_session.add_watch(TOTAL + 4, TOTAL)
    with pytest.raises(ValueError, match="nothing watched under 3"):
        sum_session.remove_watch(3)


# ------------------------------------------------------------------- the views


def test_a_place_outside_the_program(sum_session):
    """An address the program put nothing at is still a place: the word that lies
    there, read as an instruction, and no line of any file."""
    place = sum_session.place_of(TABLE)
    assert place.address == TABLE
    assert place.word == 1
    assert place.symbol == "table"
    assert (place.file, place.line, place.source) == ("", 0, "")


def test_the_listing_marks_where_the_machine_stands(sum_session):
    sum_session.until(LOOP)
    rows = sum_session.listing(count=6)
    standing = [row for row in rows if row.at]
    assert len(standing) == 1 and standing[0].place.address == LOOP
    assert [row.place.address for row in rows] == [LOOP - 8 + 4 * i for i in range(6)]


def test_the_listing_marks_the_breakpoints(sum_session):
    sum_session.add_break(LOOP)
    rows = sum_session.listing(LOOP, count=2)
    assert [row.breakpoint for row in rows] == [1, None]


def test_the_listing_of_a_place_asked_for(sum_session):
    rows = sum_session.listing(KEEP, count=3)
    assert rows[0].place.address == KEEP - 4  # a third of the rows lie behind it
    assert any(row.at for row in rows) is False  # the machine stands elsewhere


def test_the_lines_of_the_program_around_the_run(sum_session):
    sum_session.until(LOOP)
    lines = sum_session.source(3)
    # three lines centred on the one the machine stands on
    assert [line.text for line in lines] == [
        "        li t2, 0", "loop:   lw t3, 0(t0)", "        add t2, t2, t3"]
    assert [line.at for line in lines] == [False, True, False]


def test_the_registers(sum_session):
    sum_session.step(SETUP)
    everything = sum_session.registers()
    assert len(everything) == 32
    assert (everything[0].name, everything[0].value) == ("zero", 0)
    assert (everything[0].about, everything[0].file) == ("", "x")
    assert everything[2].name == "sp" and everything[2].value != 0
    few = sum_session.registers(("t1", "t2"))
    assert [(one.name, one.value) for one in few] == [("t1", 4), ("t2", 0)]
    assert few[0].bits == 32


def test_a_register_by_any_of_its_names(sum_session):
    sum_session.step(SETUP)
    assert sum_session.registers(("x6",))[0].value == 4  # t1 is x6
    assert sum_session.registers(("fp",))[0].name == "s0"  # the alias of x8
    with pytest.raises(ValueError, match="no register of that name"):
        sum_session.registers(("t9",))


def test_the_floating_point_registers(tmp_path):
    s = session("""\
.globl main
.text
main:   li t0, 3
        fcvt.s.w f1, t0, dyn
        fcvt.d.w f2, t0, dyn
        li a7, 93
        ecall
""", tmp_path)
    s.step(3)
    single, double = s.floats(("f1",))[0], s.floats(("f2",))[0]
    assert single.name == "ft1" and single.bits == 64
    assert single.about == "3.0 (single)"  # boxed, so read as a single
    assert single.file == "f"
    assert single.value >> 32 == 0xFFFFFFFF  # the box itself
    assert double.about == "3.0"
    assert len(s.floats()) == 32


def test_the_control_registers(sum_session):
    everything = sum_session.csr()
    assert len(everything) == 17  # the whole set of them
    named = {one.name: one for one in sum_session.csr(("fcsr", "ustatus", "uie"))}
    assert named["fcsr"].file == "csr"
    assert named["fcsr"].about == "flags 0x00, rounding 0"
    assert named["ustatus"].about == "nothing set"
    sum_session.set_register("ustatus", 0x11)
    assert sum_session.csr(("ustatus",))[0].about == "UIE UPIE"
    sum_session.set_register("uie", 0x110)
    assert sum_session.csr(("uie",))[0].about == "timer external"
    with pytest.raises(ValueError, match="no control register of that name"):
        sum_session.csr(("ufcsr",))


def test_the_words_of_memory_four_to_a_row(sum_session):
    rows = sum_session.memory(TABLE, TABLE + 19)  # twenty bytes: five words
    assert len(rows) == 2
    assert (rows[0].address, rows[0].values) == (TABLE, (1, 2, 3, 4))
    assert (rows[1].address, rows[1].values) == (TOTAL, (0,))
    # the row the string lies in: "hi" and the zero that ends it, as a word
    assert sum_session.memory(TABLE, MSG + 3)[1].values == (0, 26984)
    with pytest.raises(ValueError, match="the lower one"):
        sum_session.memory(TABLE + 4, TABLE)


def test_a_range_of_memory_is_taken_from_the_word_it_begins_in(sum_session):
    rows = sum_session.memory(TABLE + 2, TABLE + 5)
    assert rows[0].address == TABLE  # down to the word the first address lies in
    assert rows[0].values == (1, 2)


def test_the_data_the_program_laid_out(sum_session):
    items = sum_session.data()
    assert [(one.address, one.directive) for one in items[:5]] == [
        (TABLE, ".word"), (TABLE + 4, ".word"), (TABLE + 8, ".word"),
        (TABLE + 12, ".word"), (TOTAL, ".word")]
    text = [one for one in items if one.directive == ".asciz"][0]
    assert text.address == MSG
    assert text.size == 3  # "hi" and the zero that ends it
    assert text.text == "hi"
    assert sum_session.data(low=MSG) == [text]


def test_the_data_shows_what_stands_there_now(sum_session):
    sum_session.carry_on()
    kept = [one for one in sum_session.data() if one.address == TOTAL][0]
    assert kept.values == (10,)


def test_the_stack(sum_session):
    sum_session.add_break(KEEP)
    sum_session.carry_on()
    sp = sum_session.machine.x.read(2)
    words = sum_session.stack(3)
    assert [one.address for one in words] == [sp, sp + 4, sp + 8]
    assert words[0].frame == 0  # the call whose frame begins at this word
    assert [one.frame for one in words[1:]] == [None, None]


def test_the_symbols(sum_session):
    everything = sum_session.symbols()
    assert [one.name for one in everything] == [
        "keep", "loop", "main", "msg", "table", "total"]
    assert [one.public for one in everything] == [False, False, True, False, False,
                                                 False]
    assert [one.name for one in sum_session.symbols("tab")] == ["table"]
    assert [one.name for one in sum_session.symbols("ta")] == ["table", "total"]


def test_where_the_run_is_in_time(sum_session):
    sum_session.step(3)
    counted = sum_session.count()
    assert counted.instructions == 3
    assert counted.turns == 0  # no statistics were asked for
    assert counted.back == 3  # a session keeps a journal, which is what back needs


def test_the_journal_of_a_session_is_kept_without_being_asked_for(sum_session):
    assert sum_session.options.debug is True  # so the world is taken back too
    assert sum_session.options.history_depth == 2000
    assert sum_session.machine.history is not None


# ------------------------------------------------- the things around the machine


def test_without_anything_attached_there_is_nothing_to_show(sum_session):
    assert sum_session.devices() == []
    assert sum_session.cache_lines() == []
    assert sum_session.guesser_entries() == []
    with pytest.raises(ValueError, match="no device of that name"):
        sum_session.device("keyboard")


class Watching:
    """A part of the bus that is reset only when it is TOLD to be.

    Our own devices put themselves back when they are connected, so a session
    that leaned on that would be resetting them by luck; a device from outside
    implements the protocol as it likes, and the promise of `restart` must hold
    for it too.
    """

    name = "watching"
    counts = False

    def __init__(self) -> None:
        self.resets = 0
        self.connection = None

    def connect(self, connection) -> None:
        self.connection = connection  # and NOT a reset

    def on_retire(self, count: int) -> None:
        pass

    def reset(self) -> None:
        self.resets += 1

    def state(self) -> dict[str, object]:
        return {"resets": self.resets}


def test_a_restart_puts_a_device_back_itself(tmp_path):
    watching = Watching()
    s = session(SUM, tmp_path, bus=DeviceBus([watching]))
    assert watching.resets == 1  # once as the session was built
    s.carry_on()
    s.restart()
    assert watching.resets == 2  # and once more for the restart
    assert s.device("watching").state == {"resets": 2}


def test_the_devices_show_themselves(tmp_path):
    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard"), make("timer")]))
    attached = s.devices()
    assert [one.name for one in attached] == ["keyboard", "timer"]
    assert (attached[0].offset, attached[0].size) == (0, 16)
    # a session knows no device type: what each holds is what the device says
    assert isinstance(attached[0].state, dict) and attached[0].state
    assert s.device("timer").name == "timer"


def test_a_key_of_a_device_pressed_from_outside(tmp_path):
    """The world outside reaching IN, which is the other way from everything else
    a session answers: a program that asks for a number by the sixteen buttons of
    the lab needs somebody to press them."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("lab")]))
    seen = s.press("lab", 6)
    assert seen.name == "lab" and seen.looks["key"] == 6
    assert seen.state["key down"] == 6
    # a key of that lab that is already down goes up again, because its keys are
    # buttons that stay down - the device's own doing, not the session's
    assert s.press("lab", 6).looks["key"] == -1


def test_a_text_typed_at_a_device_is_taken_a_letter_at_a_time(tmp_path):
    """A LINE typed into a window, and not a key pushed at the device: a keyboard
    that holds one key would lose all of a line but its last letter if they were
    pushed at it together. Fed, it takes a letter whenever the program has read
    the one before."""
    from pyrars.devices.keyboard import RECEIVER_DATA
    from pyrars.isa.memory import DEFAULT

    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard")]))
    seen = s.fed("keyboard", "hi")
    assert seen.name == "keyboard"
    where = DEFAULT.mmio_base + RECEIVER_DATA
    s.step(1)  # the keyboard takes a key when it has room, on any instruction
    assert s.device("keyboard").state["key waiting"] is True
    assert s.machine.memory.read(where, 4) == ord("h")  # as a program reads it
    s.step(1)
    assert s.machine.memory.read(where, 4) == ord("i")


def test_a_line_typed_at_a_device_is_typed_out_as_a_hand_would(tmp_path):
    """A letter every so many instructions, and not all at once: so a line typed
    while the machine stands still waits, and arrives as the program runs (the
    architect, 2026-10-26)."""
    from pyrars.devices.keyboard import RECEIVER_DATA
    from pyrars.isa.memory import DEFAULT

    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard", typing=4)]))
    seen = s.typed("keyboard", "abc")
    assert seen.state["being typed"] == 3  # a hand with three letters still to go
    where = DEFAULT.mmio_base + RECEIVER_DATA
    s.step(3)
    assert s.device("keyboard").state["key waiting"] is False  # not yet
    s.step(1)  # the fourth instruction: the first letter
    assert s.machine.memory.read(where, 4) == ord("a")
    s.step(4)
    assert s.machine.memory.read(where, 4) == ord("b")
    assert s.device("keyboard").state["being typed"] == 1
    assert s.device("keyboard").looks["lost"] == 0  # it was read in time, each one


def test_a_program_that_asks_too_seldom_loses_the_letters_between(tmp_path):
    """The whole lesson of the device: a hand goes on typing whether anybody is
    asking or not, and what nobody asked for in time is gone - and counted."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard", typing=1)]))
    s.typed("keyboard", "abcd")
    s.step(4)  # four letters typed and not one of them read
    assert s.device("keyboard").looks["lost"] == 3
    assert s.device("keyboard").state["being typed"] == 0


def test_a_hand_that_was_typing_is_not_still_typing_after_a_restart(tmp_path):
    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard", typing=100)]))
    s.typed("keyboard", "abc")
    s.restart()
    assert s.device("keyboard").state["being typed"] == 0


def test_what_is_typed_waits_its_turn_behind_what_was_typed_before(tmp_path):
    """A second line typed while the program is still reading the first does not
    take its place: what is owed is kept by the session, because the device takes
    one letter at a time and whoever types does not."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard")]))
    s.fed("keyboard", "a")
    s.fed("keyboard", "b")  # the second behind the first, not in its place
    from pyrars.devices.keyboard import RECEIVER_DATA
    from pyrars.isa.memory import DEFAULT

    where = DEFAULT.mmio_base + RECEIVER_DATA
    s.step(1)
    assert s.machine.memory.read(where, 4) == ord("a")
    s.step(1)
    assert s.machine.memory.read(where, 4) == ord("b")


def test_a_run_that_begins_again_owes_nothing_that_was_typed(tmp_path):
    """A restart is a fresh run (the decision of 2026-10-21), and a program that
    asks for a letter asks the person again."""
    from pyrars.devices.keyboard import RECEIVER_DATA
    from pyrars.isa.memory import DEFAULT

    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard")]))
    s.fed("keyboard", "abc")
    s.restart()
    s.step(2)
    assert s.device("keyboard").state["key waiting"] is False
    assert s.machine.memory.read(DEFAULT.mmio_base + RECEIVER_DATA, 4) == 0


def test_an_image_put_on_a_disk_and_taken_off_it(tmp_path):
    s = session(SUM, tmp_path,
                bus=DeviceBus([make("disk", blocks=2, block_size=8)]))
    held = bytes(range(16))
    seen = s.put_on("disk", held)
    assert seen.name == "disk"
    kept = s.image_of("disk")
    assert (kept.name, kept.data) == ("disk", held)


def test_an_image_of_the_wrong_size_says_what_the_device_says(tmp_path):
    """The size is the device's own, so the device is the one that says it."""
    s = session(SUM, tmp_path,
                bus=DeviceBus([make("disk", blocks=2, block_size=8)]))
    with pytest.raises(ValueError, match="an image of 3 bytes for a disk of 16"):
        s.put_on("disk", b"abc")


def test_the_clock_of_a_device_started_and_stopped_by_hand(tmp_path):
    """Which is what the timer of RARS lets one do, and what shows a program
    reading a time that does not move."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("timer")]))
    assert s.device("timer").state["running"] is True
    assert s.ticking("timer", False).state["running"] is False
    assert s.ticking("timer", True).state["running"] is True


def test_what_a_device_will_not_be_asked_to_do(tmp_path):
    """Every one of them says what it is in the same shape."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("timer"), make("lab")]))
    with pytest.raises(ValueError, match="takes no text to type"):
        s.fed("timer", "hi")
    with pytest.raises(ValueError, match="holds no image"):
        s.put_on("lab", b"")
    with pytest.raises(ValueError, match="holds no image"):
        s.image_of("timer")
    with pytest.raises(ValueError, match="no clock to start or stop"):
        s.ticking("lab", True)
    with pytest.raises(ValueError, match="no keys to press"):
        s.press("timer", 0)


def test_pressing_a_key_is_no_step_of_the_machine(tmp_path):
    """The journal knows nothing of it, exactly as `set` and `poke` are not steps
    either (the rule of the journal)."""
    s = session(SUM, tmp_path, bus=DeviceBus([make("lab")]))
    s.step(3)
    before = s.count()
    s.press("lab", 1)
    assert s.count() == before


def test_a_device_with_no_keys_to_press(tmp_path):
    s = session(SUM, tmp_path, bus=DeviceBus([make("timer")]))
    with pytest.raises(ValueError, match="no keys to press"):
        s.press("timer", 0)
    with pytest.raises(ValueError, match="no device of that name is attached"):
        s.press("lab", 0)


def test_a_key_pressed_with_nothing_attached(sum_session):
    with pytest.raises(ValueError, match="no device of that name is attached"):
        sum_session.press("lab", 0)


def test_the_blocks_a_cache_holds(tmp_path):
    s = session(SUM, tmp_path, caches=Caches(CacheSettings(block_bytes=16, sets=4)))
    s.carry_on()
    lines = s.cache_lines()
    assert lines  # the run read the table, so the cache has something
    first = [one for one in lines if one.low <= TABLE <= one.high][0]
    assert first.side == "cache"  # one cache for everything
    assert first.high - first.low == 15
    assert first.set == (TABLE // 16) % 4
    assert first.place == 0  # one way, so the only block of its set
    assert first.dirty is False  # the whole table was read and nothing written
    # `total` lies in the next block, and that one the subroutine wrote
    kept = [one for one in lines if one.low <= TOTAL <= one.high][0]
    assert kept.set == (TOTAL // 16) % 4 and kept.dirty is True


def test_the_entries_of_a_table_of_history(tmp_path):
    s = session(SUM, tmp_path,
                pipeline=Pipeline(PipelineSettings(), Table(entries=4, bits=2)))
    s.carry_on()
    entries = s.guesser_entries()
    assert len(entries) == 4
    # the one branch of the program falls into the entry its address gives it
    mine = entries[(TEXT + 0x20) >> 2 & 3]
    assert mine.right + mine.wrong == 4  # the branch was met four times
    assert mine.taken is True  # three turns of four went back to the loop
    assert sum(one.right + one.wrong for one in entries) == 4


def test_a_guesser_without_a_table_shows_none(tmp_path):
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.carry_on()
    assert s.guesser_entries() == []


def test_what_a_cache_was_built_with_and_what_it_counted(tmp_path):
    """Both in one answer, because a hit rate means nothing without the cache that
    gave it: the comparison anybody is making is the same program through a cache
    of two ways and through one of eight."""
    s = session(SUM, tmp_path, caches=Caches(CacheSettings(sets=4, ways=2)))
    s.carry_on()
    seen = s.caches()
    assert [one.side for one in seen] == ["cache"]  # one cache for everything
    built = {one.name: one.value for one in seen[0].settings}
    assert (built["sets"], built["ways"]) == (4, 2)
    assert "seed" in built  # everything it was built with, not only what is offered
    assert seen[0].accesses == seen[0].hits + seen[0].misses > 0
    assert seen[0].rate == seen[0].hits / seen[0].accesses
    assert seen[0].fetches is False  # nobody asked for the instructions to reach it


def test_a_cache_of_the_instructions_says_that_they_reach_it(tmp_path):
    s = session(SUM, tmp_path, fetches=True,
                caches=Caches(CacheSettings(), instructions=CacheSettings()))
    s.carry_on()
    seen = {one.side: one for one in s.caches()}
    assert set(seen) == {"data", "instructions"}
    assert seen["instructions"].fetches is True
    assert seen["data"].fetches is False
    # one fetch per instruction carried out; the ecall that ended the run is the
    # one turn that never reached a model
    assert seen["instructions"].accesses == WHOLE
    assert seen["instructions"].hits > seen["instructions"].misses  # a loop


def test_what_the_pipeline_counted(tmp_path):
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.carry_on()
    seen = s.pipeline()
    assert seen.instructions == WHOLE
    assert seen.cycles > seen.instructions  # five stages, and what was waited for
    assert seen.cpi == seen.cycles / seen.instructions
    assert seen.lost == sum(one.value for one in seen.stalls)  # what it waited for
    assert {one.name for one in seen.settings} >= {"forwarding", "penalty"}
    assert all(isinstance(one.value, int) for one in seen.stalls)
    # four branches, and not every one of them was guessed wrongly: a machine
    # that never expects a branch to be taken is right the once it is not
    assert seen.branches == 4 and 0 < seen.wrong < seen.branches


def test_the_cycles_of_the_model_are_walked_one_at_a_time(tmp_path):
    """A cycle is no step of the machine: the model times a run that has already
    happened, so walking it on means carrying the machine as far as it must go to
    know what is in flight - and no further."""
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    assert s.cycle_now == -1  # nobody has looked at a cycle yet
    first = s.cycle_on()
    assert first.now == 0
    assert first.stepped == 1  # one instruction to know the first cycle
    assert first.cycles == 5 and not first.ended
    # the pipeline fills: a cycle, an instruction, and the diagonal grows
    for expected in range(1, 5):
        on = s.cycle_on()
        assert on.now == expected
        assert on.stepped == 1
        assert s.count().instructions == expected + 1
    assert s.pipeline().cycle == 4  # and the views are told which cycle it is


def test_the_cycles_run_out_where_the_run_does(tmp_path):
    """The diagram ends with the run, and the cycle sticks to the last of them
    rather than walking off into cycles nobody will ever time."""
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.carry_on()
    last = s.cycle_on(10_000)
    assert last.ended and last.now == last.cycles - 1
    again = s.cycle_on()
    assert again.now == last.now and again.stepped == 0


def test_a_machine_that_cannot_go_on_stops_the_walk_of_the_cycles(tmp_path):
    """A `wfi` with nothing to wait for is a machine that is not over and will not
    move either (DEV-46). The walk must stop where the machine does rather than
    asking it for another instruction for ever."""
    s = session(".text\nmain: wfi\n", tmp_path,
                pipeline=Pipeline(PipelineSettings()))
    on = s.cycle_on(50)
    assert not on.ended  # the run is not over: it is waiting for what cannot come
    assert on.stepped <= 2  # it asked, was given nothing, and let it be
    # and nothing was timed at all, so there is no cycle to look at
    assert (on.now, on.cycles) == (-1, 0)
    assert s.count().instructions == 0


def test_a_restart_is_at_no_cycle_of_the_model_either(tmp_path):
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.cycle_on(4)
    assert s.cycle_now == 3  # four cycles on from no cycle at all is the fourth
    s.restart()
    assert s.cycle_now == -1
    assert s.pipeline().cycle == -1


def test_there_are_no_cycles_to_walk_without_a_pipeline(sum_session):
    with pytest.raises(ValueError, match="no pipeline was asked for"):
        sum_session.cycle_on()


def test_the_diagram_the_pipeline_kept(tmp_path):
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.carry_on()
    drawn = s.diagram()
    assert len(drawn) == WHOLE
    assert drawn[0].address == TEXT and drawn[0].starts == (0, 1, 2, 3, 4)
    assert len(drawn[0].starts) == 5  # the five stages
    assert all(one.ex_cycles >= 1 for one in drawn)
    # every instruction begins to be fetched after the one before it
    assert all(later.starts[0] > earlier.starts[0]
               for earlier, later in zip(drawn, drawn[1:]))


def test_what_the_guesser_counted(tmp_path):
    s = session(SUM, tmp_path,
                pipeline=Pipeline(PipelineSettings(), Table(entries=4, bits=2)))
    s.carry_on()
    seen = s.guesser()
    assert "4 entries" in seen.name and "2 bits" in seen.name
    assert {one.name: one.value for one in seen.settings} == {"entries": 4,
                                                             "bits": 2}
    assert seen.guesses == seen.right + seen.wrong == 4  # the one branch, four times
    assert seen.accuracy == seen.right / seen.guesses


def test_a_guesser_that_keeps_no_table_says_what_it_is_all_the_same(tmp_path):
    s = session(SUM, tmp_path, pipeline=Pipeline(PipelineSettings()))
    s.carry_on()
    assert s.guesser().settings == ()  # it has nothing to be built with
    assert s.guesser().name


def test_what_the_run_was_made_of(tmp_path):
    s = session(SUM, tmp_path, statistics=True)
    s.carry_on()
    seen = s.statistics()
    assert seen.instructions == WHOLE and seen.turns == WHOLE
    assert (seen.traps, seen.unknown) == (0, 0)
    assert (seen.taken, seen.not_taken) == (3, 1)
    kinds = {one.name: one.value for one in seen.kinds}
    assert kinds["branch"] == 4 and kinds["store"] == 1
    assert sum(one.value for one in seen.kinds) == WHOLE
    assert "jal" not in kinds  # by the KIND of instruction, not by its name
    assert [one.name for one in seen.categories] == ["ALU", "Jump", "Branch",
                                                     "Memory", "Other"]


def test_a_run_nobody_asked_to_watch_says_so_and_does_not_fall_over(sum_session):
    """A window shows what it is given; what it is NOT given it says nothing
    about, and must not be made to guess."""
    assert sum_session.caches() == []
    assert sum_session.pipeline() is None
    assert sum_session.diagram() == []
    assert sum_session.guesser() is None
    assert sum_session.statistics() is None


def test_the_models_a_session_was_asked_for(tmp_path):
    s = session(SUM, tmp_path, statistics=True)
    s.carry_on()
    # the turn that ended the run never reached a model: it did nothing to count
    assert s.count().turns == WHOLE
    assert s.models.statistics.instructions == WHOLE
    assert s.models.callstack is not None  # always, for `over` and `finish`


# ----------------------------------------------------------------- the changes


def test_a_value_put_in_a_register(sum_session):
    put = sum_session.set_register("t0", 0x1234)
    assert (put.name, put.value) == ("t0", 0x1234)
    assert sum_session.machine.x.read(5) == 0x1234


def test_a_value_put_in_the_register_that_is_always_zero(sum_session):
    assert sum_session.set_register("zero", 7).value == 0


def test_a_value_put_in_a_floating_point_register(sum_session):
    put = sum_session.set_register("ft1", 0x3FF0000000000000)
    assert put.name == "ft1"
    assert put.about == "1.0"


def test_a_value_put_in_a_control_register(sum_session):
    put = sum_session.set_register("fcsr", 0xE0)
    assert (put.name, put.value) == ("fcsr", 0xE0)
    assert put.about == "flags 0x00, rounding 7"


def test_a_value_put_in_memory(sum_session):
    assert sum_session.poke(TOTAL, 0x11223344).values == (0x11223344,)
    assert sum_session.machine.memory.peek(TOTAL, 4) == 0x11223344
    assert sum_session.poke(TOTAL, 0xFF, size=1).values == (0xFF,)


def test_what_a_person_put_there_is_not_taken_back(sum_session):
    """`set` and `poke` are no steps of the machine, so a step back does not undo
    them (the rule of the journal, the decision of 2026-10-06)."""
    sum_session.step(SETUP)
    sum_session.set_register("s1", 0x99)  # a register no step of the run touches
    sum_session.poke(TOTAL, 0x11223344)  # and a word none of these steps wrote
    sum_session.back(2)
    assert sum_session.machine.x.read(9) == 0x99  # s1 as the person left it
    assert sum_session.machine.memory.peek(TOTAL, 4) == 0x11223344
    assert sum_session.where().address == LOOP - 8  # and the steps themselves back


def test_a_step_back_still_puts_back_what_that_step_changed(sum_session):
    """The other side of the same rule: taking a step back means putting back what
    the step found, so a value put in a place that the step itself wrote goes with
    it. The journal wins there, because that is what taking a step back is.
    """
    sum_session.step(SETUP)  # the last of these steps is `li t2, 0`
    sum_session.set_register("t2", 0x99)
    sum_session.back()
    assert sum_session.machine.x.read(7) == 0  # what `li t2, 0` found there


# ------------------------------------------------------------------- the names


def test_a_place_by_its_name(sum_session):
    assert sum_session.address_of("loop") == LOOP
    assert sum_session.address_of("table") == TABLE


def test_a_place_by_its_number(sum_session):
    assert sum_session.address_of("0x400010") == LOOP
    assert sum_session.address_of(str(LOOP)) == LOOP
    assert sum_session.address_of(" 0b10000 ") == 16


def test_a_place_by_the_line_it_is_on(sum_session):
    assert sum_session.address_of("p.s:10") == LOOP  # the tenth line is the `lw`
    assert sum_session.address_of(":10") == LOOP  # the file may be left out


def test_a_place_that_is_nowhere(sum_session):
    with pytest.raises(ValueError, match="no such place in the program"):
        sum_session.address_of("elsewhere")
    with pytest.raises(ValueError, match="no instruction of the program is there"):
        sum_session.address_of("p.s:3")  # a line of the data segment


# ----------------------------------------------------------------- the restart


def test_the_program_from_the_beginning(sum_session):
    sum_session.add_break(KEEP)
    watched = sum_session.add_watch(TOTAL, TOTAL + 3, "write")
    sum_session.carry_on()
    assert sum_session.watches()[0].hits == 0  # it stopped on the breakpoint first

    stopped = sum_session.restart()
    assert stopped.place.address == MAIN
    assert sum_session.count().instructions == 0
    assert sum_session.machine.memory.peek(TOTAL, 4) == 0  # the world as it was
    # what was asked for stands; what the models counted does not
    assert [one.place.address for one in sum_session.breaks()] == [KEEP]
    assert sum_session.watches() == [watched]
    assert sum_session.frames() == []


def test_a_restart_does_not_put_the_world_back(tmp_path):
    """A restart is a FRESH run (user decision 2026-10-21): a program that asks for
    a line asks again, rather than silently reading what it was given before.

    A step back is unchanged - stepping back and forward again must give the same
    thing twice - and that is tested with the journal, where it belongs.
    """
    asking = """\
.globl main
.data
buffer: .space 32
.text
main:   li a7, 8
        la a0, buffer
        li a1, 32
        ecall
        li a7, 4
        la a0, buffer
        ecall
        li a7, 93
        li a0, 0
        ecall
"""
    out, reader = io.StringIO(), io.StringIO("Ann\nBob\n")
    s = session(asking, tmp_path,
                io_=ConsoleIO(out=out, errors=io.StringIO(), reader=reader))
    s.carry_on()
    assert "Ann" in out.getvalue()
    s.restart()
    s.carry_on()
    assert "Bob" in out.getvalue()  # the next line, because it asked again


def test_a_restart_forgets_what_the_watches_counted(sum_session):
    sum_session.add_watch(TABLE, TABLE + 15, "read")
    sum_session.carry_on()
    sum_session.carry_on()
    assert sum_session.watches()[0].hits == 2  # two words of the table read
    sum_session.restart()
    assert sum_session.watches()[0].hits == 0


def test_what_is_watched_is_watched_again_after_a_restart(sum_session):
    sum_session.add_watch(TOTAL, TOTAL + 3, "write")
    sum_session.restart()
    stopped = sum_session.carry_on()
    assert stopped.reason == WATCHPOINT
    assert stopped.touched[0].by == SW
