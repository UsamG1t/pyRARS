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


def session(source: str, tmp_path, **kept) -> Session:
    """A session over an assembled program, writing into a string."""
    path = tmp_path / "p.s"
    path.write_text(source)
    program = assemble([str(path)], AsmOptions())
    assert program.diagnostics == (), program.diagnostics
    return Session(program, io=ConsoleIO(out=io.StringIO(), errors=io.StringIO(),
                                        reader=io.StringIO()), **kept)


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
    assert everything[0].about == "x0"
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
    assert single.about == "f1: 3.0 (single)"  # boxed, so read as a single
    assert single.value >> 32 == 0xFFFFFFFF  # the box itself
    assert double.about == "f2: 3.0"
    assert len(s.floats()) == 32


def test_the_control_registers(sum_session):
    everything = sum_session.csr()
    assert len(everything) == 17  # the whole set of them
    named = {one.name: one for one in sum_session.csr(("fcsr", "ustatus", "uie"))}
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


def test_the_devices_show_themselves(tmp_path):
    s = session(SUM, tmp_path, bus=DeviceBus([make("keyboard"), make("timer")]))
    attached = s.devices()
    assert [one.name for one in attached] == ["keyboard", "timer"]
    assert (attached[0].offset, attached[0].size) == (0, 16)
    # a session knows no device type: what each holds is what the device says
    assert isinstance(attached[0].state, dict) and attached[0].state
    assert s.device("timer").name == "timer"


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
    assert put.about == "f1: 1.0"


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
