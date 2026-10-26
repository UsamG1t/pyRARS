"""The whole of M8, from end to end: a program worked on in a window.

Every other test of the block tries one piece - the editor, a mark in the margin,
one view, one panel of a device. These try the pieces TOGETHER, in the order a
person meets them: a program assembled, refused, mended and debugged; a project of
two files opened the way the command line opens one and stopped in the second of
them; a run set up in the run window, kept, and found again by the window after
it; two devices talked to while the program is going.

The one that matters most is the third: the window and the console debugger told
to do the SAME thing must agree about every number they show, because they are two
faces of one session and there is no second implementation anywhere for them to
differ over. `tests/unit/test_session_whole.py` does that for the session alone;
here the numbers come the whole way - through the thread of the run, into the
tables of a window that is really built.

Nothing here is compared with RARS: its window is Swing and D4 chose GTK 4.
"""

import argparse
import io
import json
from pathlib import Path

import pytest

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
LIB = """\
.globl double
.text
double: add a0, a0, a0
        ret
"""
USES = """\
.globl main
.text
main:   li a0, 7
        jal ra, double
        li a7, 93
        li a0, 0
        ecall
"""
# Reads a key whenever one is there, shows it, does a hundred instructions' worth
# of work with it and ends on a newline. The work is what makes the way the letters
# arrive matter: a hand typing at its own speed gets ahead of a program like this
# and letters go unread, while a file is taken a letter at a time, whenever there
# is room for one.
KEYS = """\
.globl main
.text
main:   li      s0, 0xffff0000
wait:   lw      t0, 0(s0)
        andi    t0, t0, 1
        beq     t0, zero, wait
        lw      t1, 4(s0)
        li      t2, 10
        beq     t1, t2, done
        sw      t1, 12(s0)
        li      t3, 50
work:   addi    t3, t3, -1
        bne     t3, zero, work
        j       wait
done:   li      a7, 10
        ecall
"""


@pytest.fixture
def a_window(gtk, tmp_path):
    """A window over a program written for the journey, closed however it ends."""
    from pyrars.ui.window import Window

    opened = []

    def open_one(source: str = SUM, name: str = "main.s", **kept):
        (tmp_path / name).write_text(source)
        made = Window(files=(str(tmp_path / name),),
                      cache=str(tmp_path / "cache"), **kept)
        opened.append(made)
        return made

    yield open_one
    for made in opened:
        made.close_up()


def looking(window, page: str) -> None:
    """Open a page of the lower views, as a person does before reading it: the
    window asks the session for the page that is open and for nothing else."""
    window.views.set_current_page(window.pages().index(page))


def said(view) -> str:
    buffer = view.get_buffer()
    return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)


def row(window, which: str, name: str):
    for cells in window.views_of[which].rows:
        if cells[0] == name:
            return cells
    return None


def console(path: str, *commands, flags=()):
    """The same program under the console debugger: the other face of the same
    session, and the only thing a window can be held against."""
    from pyrars.cli import main

    out, errors = io.StringIO(), io.StringIO()
    asked = []
    for command in commands:
        asked += ["-e", command]
    main(["run", path, "--debug-mode", *flags, *asked, "--steps", "5000"],
         out=out, errors=errors, reader=io.StringIO(""))
    return out.getvalue()


def answered(out: str, after: str) -> list[list[str]]:
    """The pieces of every line one command of a console session answered with."""
    found, taking = [], False
    for line in out.splitlines():
        if line.startswith("(pyrars) "):
            if taking:
                break
            taking = line == f"(pyrars) {after}"
            continue
        if taking:
            found.append([piece.strip() for piece in line.split(" | ")])
    return found


# --------------------------------------------- a program mended and then debugged


def test_a_program_refused_mended_and_then_debugged(a_window, turning):
    """The whole of an ordinary hour: a program that will not assemble, the line it
    is wrong on marked where the mistake is, the file mended on the screen, a
    breakpoint put in the margin, the loop watched going round, two steps taken
    back and the run let go to its end.
    """
    window = a_window(SUM.replace("add t1, t1, t0", "add t1, t1, t9"))
    page = window.editor.page
    window.do("assemble")
    assert turning(lambda: page.marked("error") == [7])
    assert window.state == "nothing"  # and there is nothing at all to run
    assert not window.allowed() & {"step", "continue", "restart"}

    page.buffer.set_text(SUM)  # mended on the screen
    window.do("assemble")      # and written to the disk on the way to the assembler
    assert turning(lambda: window.state == "standing")
    assert page.marked("error") == [] and Path(page.path).read_text() == SUM
    assert "assembled: " in said(window.messages)

    window.editor.toggle_breakpoint(page, 7)  # the `add` of the loop
    window.do("continue")
    assert turning(lambda: "breakpoint" in window.standing.get_text())
    assert row(window, "registers", "t0")[2] == "0x00000003"
    assert row(window, "registers", "t1")[2] == "0x00000000"
    window.do("continue")  # round the loop once more
    assert turning(lambda: row(window, "registers", "t1")[2] == "0x00000003")
    assert row(window, "registers", "t0")[2] == "0x00000002"

    window.do("back")
    window.do("back")
    # the `bne` and the `addi` are undone, and the margin says where it stands
    assert turning(lambda: page.marked("here") == [8])
    assert row(window, "registers", "t0")[2] == "0x00000003"

    window.editor.toggle_breakpoint(page, 7)  # the breakpoint off again
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    looking(window, "data")
    # three, two and one, however many times the loop was gone round by hand
    assert turning(lambda: ["0x10010000", ".word", "4", "0x00000006", ""]
                   in [list(cells) for cells in window.views_of["data"].rows])


# ------------------------------------------- a project of two files, from the line


def test_a_project_opened_as_the_command_line_opens_one_and_stopped_in_its_other_file(
        gtk, tmp_path, turning):
    """`python -m pyrars.ui --project ...`, and then the thing a project is FOR: a
    name in one file reached from another, stopped in, and come back out of."""
    from pyrars.ui.__main__ import _opened
    from pyrars.ui.window import Window

    (tmp_path / "lib.s").write_text(LIB)
    (tmp_path / "uses.s").write_text(USES)
    (tmp_path / "thing.pyrars.json").write_text(
        json.dumps({"files": ["lib.s", "uses.s"], "main": "uses.s"}))
    where = str(tmp_path / "thing.pyrars.json")
    project, files = _opened(argparse.Namespace(project=where, files=[]))
    window = Window(project=project, files=files, where=where,
                    cache=str(tmp_path / "cache"))
    try:
        # the main file first, as a project orders them: it is assembled first
        assert [Path(path).name for path in window.editor.paths] == ["uses.s",
                                                                     "lib.s"]
        window.do("assemble")
        assert turning(lambda: window.state == "standing")
        # the main file is assembled first, so the program begins in uses.s
        assert window.views_of["text"].rows[0][4].startswith("main:")

        library = [one for one in window.editor.pages
                   if one.path.endswith("lib.s")][0]
        window.editor.toggle_breakpoint(library, 3)  # `add a0, a0, a0`
        window.do("continue")
        assert turning(lambda: "breakpoint" in window.standing.get_text())
        # the editor is in the other file now, at the line the machine stands on
        assert window.editor.page is library
        assert library.marked("here") == [3]
        assert row(window, "registers", "a0")[2] == "0x00000007"  # not yet doubled
        looking(window, "frames")
        assert turning(lambda: window.views_of["frames"].rows != [])
        inside = window.views_of["frames"].rows[0]
        assert inside[0] == "1" and "<double>" in inside[1]
        assert inside[2] == "0x00400004"  # the `jal` of uses.s it was called from

        window.do("finish")
        assert turning(lambda: row(window, "registers", "a0")[2] == "0x0000000e")
        assert window.editor.page.path.endswith("uses.s")  # back where it was called
    finally:
        window.close_up()


# ----------------------------------- the window and the console, over the same run


def test_the_window_and_the_console_agree_about_the_same_run(a_window, tmp_path,
                                                             turning):
    """Two front ends, one session: the same six steps must leave the same numbers
    on the screen, whatever words each of them writes around them.

    The window's numbers come through the thread of the run, a snapshot, a watched
    question and a table of GTK; the console's come from a call and a print. Where
    they differ, one of them is lying about the machine.
    """
    from pyrars.session import settings as runs

    window = a_window(SUM, settings=runs.Settings(statistics=True,
                                                  cache={"sets": 4}))
    out = console(str(tmp_path / "main.s"), "step 6", "regs", "continue", "count",
                  "stats", "cache info", flags=("--stats", "--cache", "sets=4"))

    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    for _ in range(6):
        window.do("step")
    assert turning(lambda: "6 carried out" in window.standing.get_text())

    # every register of the machine, by name, written the same way
    by_hand = {cells[0]: cells[2] for cells in answered(out, "regs")}
    in_the_window = {cells[0]: cells[2]
                     for cells in window.views_of["registers"].rows}
    assert in_the_window == by_hand
    assert by_hand["t0"] == "0x00000002"  # and it really got somewhere

    # where the run stands, which each of them says in one line of its own
    stepped = answered(out, "step 6")[0]
    standing = window.standing.get_text()
    assert stepped[1].split()[0] in standing  # the address
    assert stepped[2] in standing             # and the instruction there

    # and then both of them are let go to the end
    window.do("continue")
    assert turning(lambda: window.state == "ended")
    assert answered(out, "continue")[0][0].startswith("exited 0")
    looking(window, "cache")
    assert turning(lambda: window.views_of["cache"].rows != [])
    looking(window, "counted")
    assert turning(lambda: window.views_of["counted"].rows != [])

    # what the run was made of. The names are each front end's own - a window
    # writes out what the console abbreviates - so the numbers are matched up by
    # what they are OF.
    counted = {cells[0]: cells[1] for cells in answered(out, "stats")}
    shown_now = {cells[0]: cells[1] for cells in window.views_of["counted"].rows}
    assert shown_now["instructions"] == counted["instructions"] == "16"
    assert shown_now["turns"] == counted["turns"]
    assert shown_now["traps"] == counted["traps"]
    assert shown_now["branches that went"] == counted["branches.taken"]
    for kind in ("alu", "branch"):
        assert shown_now[f"of kind {kind}"] == counted[f"kind.{kind}"]

    # the cache: how it was built, and how it fared
    built = {cells[1]: cells[2] for cells in answered(out, "cache info")}
    held = {cells[1]: cells[2] for cells in window.views_of["cache"].rows}
    for name in ("block_bytes", "sets", "ways", "accesses", "hits", "misses"):
        assert held[name] == built[name]
    # the one word the program keeps, and the first touch of a block is a miss
    assert held["accesses"] == "1" and held["misses"] == "1" and held["hits"] == "0"
    assert held["replacement"] == built["replacement"] == "lru"
    # and a yes is the one thing they spell differently, because a yes is a WORD
    # and every word on a screen belongs to the front end that wrote it
    assert (held["write_back"], built["write_back"]) == ("yes", "True")


# ------------------------------------------------- a run set up, kept, found again


def test_a_run_set_up_in_the_window_is_kept_and_found_by_the_next_window(
        a_window, gtk, tmp_path, turning):
    """What the command line is told in flags, a window is told once: the models
    and the devices are chosen in the run window, kept where they will be found,
    and the window opened after it comes up with the same world and fills it.
    """
    from pyrars.session import settings as runs
    from pyrars.ui.window import Window

    window = a_window(SUM)
    asking = window.ask_how_it_is_run()
    try:
        asking.wanted["cache"].set_enable_expansion(True)
        asking.rows["cache"]["sets"].widget.set_value(4)
        asking.wanted["pipeline"].set_enable_expansion(True)
        asking.wanted["timer"].set_enable_expansion(True)
        asking._use()
    finally:
        asking.destroy()
    assert window.pages_wanted() == ["cache", "pipeline", "counted",
                                     "device:timer"]
    kept = runs.read()  # and on the disk, where they will be found again
    assert kept.cache["sets"] == 4 and kept.pipeline is not None
    assert list(kept.devices) == ["timer"]

    again = Window(files=(str(tmp_path / "main.s"),),
                   cache=str(tmp_path / "cache"))
    try:
        assert again.settings == window.settings  # it was never told; it read it
        assert again.pages_wanted() == window.pages_wanted()
        assert again.buttons["cycle"].get_visible()  # there is a pipeline to cycle
        again.do("assemble")
        assert turning(lambda: again.state == "standing")
        again.do("continue")
        assert turning(lambda: again.state == "ended")

        looking(again, "cache")
        assert turning(lambda: again.views_of["cache"].rows != [])
        held = {cells[1]: cells[2] for cells in again.views_of["cache"].rows}
        assert held["sets"] == "4" and held["accesses"] == "1"
        assert [part.text for part in again.pictures["cache"].picture.parts
                ].count("0x10010000") == 1

        looking(again, "pipeline")
        assert turning(lambda: again.views_of["pipeline"].rows != [])
        timed = {cells[0]: cells[1] for cells in again.views_of["pipeline"].rows}
        assert int(timed["cycles"]) > int(timed["instructions"]) > 0
        # and the model may be walked a cycle at a time, which the machine is not:
        # the diagram says which cycle it is showing and frames what is in flight
        again.do("cycle")
        assert turning(lambda: any(part.text.startswith("cycle 0 of")
                                   for part in
                                   again.pictures["pipeline"].picture.parts))
        assert len([part for part in again.pictures["pipeline"].picture.parts
                    if part.edge == "lit"]) == 1  # the first fetch, and nothing else

        looking(again, "device:timer")
        panel = again.panels["device:timer"]
        assert turning(lambda: panel.table.rows != [])
        assert panel.table.rows[0][:2] == ("where", "0xffff0018")
    finally:
        again.close_up()


# --------------------------------------------- the devices, while the program goes


def test_two_devices_talked_to_while_the_program_is_going(a_window, tmp_path,
                                                          turning):
    """A program spinning on a keyboard that has nothing in it yet - which is where
    a window has to be able to do something, or the devices are ornaments.

    The disk is given its image while the machine is RUNNING, the keyboard is
    poured a file and reads every letter of it, and the image comes off the disk
    again afterwards because somebody asked for it and said where.
    """
    from pyrars.session import settings as runs
    from pyrars.ui import devices

    window = a_window(KEYS, settings=runs.Settings(
        statistics=False, devices={"keyboard": {"delay": 1},
                                   "disk": {"blocks": 2, "block_size": 8}}))
    (tmp_path / "image.img").write_bytes(bytes(range(16)))
    (tmp_path / "keys.txt").write_text("abc\n")
    window.do("assemble")
    assert turning(lambda: window.state == "standing")
    looking(window, "device:keyboard")
    window.do("continue")
    assert turning(lambda: window.state == "running")

    disk, keyboard = window.panels["device:disk"], window.panels["device:keyboard"]
    devices.put_on(disk, str(tmp_path / "image.img"))
    devices.poured(keyboard, str(tmp_path / "keys.txt"))
    assert turning(lambda: window.state == "ended", 10.0)

    # a file is taken a letter at a time, whenever there is room for one, so
    # nothing of it can be lost - which is what makes it the way to prepare input
    assert turning(lambda: dict(keyboard.table.rows).get("keys lost") == "0")
    shown_now = said(keyboard.picture.view)
    assert shown_now.startswith("abc") and "lost" not in shown_now

    # the image reached the disk while the machine was going, and comes off it
    # again where it was asked to go - and nowhere else, unasked
    disk.writing = str(tmp_path / "back.img")
    disk.door("image_of")(disk.device)
    assert turning(lambda: (tmp_path / "back.img").exists())
    assert (tmp_path / "back.img").read_bytes() == bytes(range(16))
    assert "16 bytes written to back.img" in said(window.messages)
