"""The whole of M7, from end to end: a project, a session, two front ends.

Every other test of the block tries one piece. These try the pieces TOGETHER, and
the one that matters most is the last kind: the console debugger and a window
driving the same program must agree about everything, because they are two faces
of one session and there is no second implementation anywhere for them to differ
over.

Nothing here is compared with RARS; what can be is in `tests/devel/`.
"""

import io
import json

import pytest

from pyrars.cli import main
from pyrars.session.control import LOAD, Answer, RunController, Snapshot
from pyrars.session import project as projects

LIB = """\
.globl double
.text
double: add a0, a0, a0
        ret
"""
MAIN = """\
.globl main
.data
kept:   .word 0
.text
main:   li a0, 7
        jal ra, double
        la t0, kept
        sw a0, 0(t0)
        li a7, 93
        li a0, 0
        ecall
"""
# Seven in `main` - li, jal, the two halves of `la`, sw, li, li - and the `ecall`
# that exits does not count; the two of `double` are carried out in the middle.
WHOLE = 7 + 2


def written(tmp_path, held: dict | None = None):
    (tmp_path / "main.s").write_text(MAIN)
    (tmp_path / "lib.s").write_text(LIB)
    path = tmp_path / "thing.pyrars.json"
    path.write_text(json.dumps(held or {"files": ["lib.s", "main.s"],
                                        "main": "main.s"}))
    return str(path)


def console(tmp_path, *commands, flags=(), given=""):
    """A session of the console debugger over the project."""
    out, errors = io.StringIO(), io.StringIO()
    asked = []
    for command in commands:
        asked += ["-e", command]
    code = main(["run", "--project", written(tmp_path), "--debug-mode", *flags,
                 *asked, "--steps", "5000"],
                out=out, errors=errors, reader=io.StringIO(given))
    return code, out.getvalue(), errors.getvalue()


def rows(out: str, after: str) -> list[list[str]]:
    """The pieces of every line a command answered with."""
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


class Told:
    def __init__(self) -> None:
        self.events: list[object] = []

    def __call__(self, event) -> None:
        self.events.append(event)

    @property
    def snapshots(self):
        return [one for one in self.events if isinstance(one, Snapshot)]

    @property
    def answers(self):
        return [one for one in self.events if isinstance(one, Answer)]


# ------------------------------------------------- a project debugged by hand


def test_a_place_in_the_other_file_of_the_project(tmp_path):
    """A project of two files, a breakpoint by the line of the second one, and the
    name of the first: every piece of the block at once."""
    code, out, _ = console(tmp_path, "break add lib.s:3", "continue", "frames",
                           "regs a0", "finish", "regs a0")
    assert rows(out, "break add lib.s:3")[0][:2] == ["1", "0x00400020 <double>"]
    assert rows(out, "continue")[0][0] == "breakpoint 1 after 2"
    assert rows(out, "frames")[0][1] == "0x00400020 <double>"
    assert rows(out, "regs a0")[0] == ["a0", "x10", "0x00000007"]  # not yet doubled
    assert rows(out, "finish")[0][1] == "0x00400008 <main+8>"


def test_a_session_of_everything_at_once(tmp_path):
    """A project, a device, two models and a watch, all in one session."""
    code, out, _ = console(
        tmp_path, "watch add kept write", "continue", "cache show", "guesser info",
        "device list", "stats", "count",
        flags=("--cache", "sets=4", "--pipeline", "predictor=table,entries=4",
               "--stats", "--device", "halt"))
    touched = rows(out, "continue")[0]
    assert touched[0] == "touched 1" and touched[1] == "write"
    assert touched[4] == "0x0000000e"  # seven doubled
    assert rows(out, "cache show")[0][0] == "cache"
    assert rows(out, "guesser info")[0] == ["guesser", "a table of 4 entries of 1 bits"]
    assert rows(out, "device list")[0][0] == "halt"
    assert ["instructions", str(WHOLE - 2)] in rows(out, "stats")  # it stopped early
    assert rows(out, "count")[0] == ["instructions", str(WHOLE - 2)]


def test_a_run_taken_back_to_where_it_began(tmp_path):
    """The journal over the whole of a run: every step back, and the machine stands
    where a session that had done nothing would stand."""
    code, out, _ = console(tmp_path, "continue", "count", "back 100", "count",
                           "where", "regs a0")
    assert rows(out, "count")[0] == ["instructions", str(WHOLE)]
    # One step more than the instructions: the turn that ENDED the run opened a
    # step of the journal too, and taking that one back is what puts the machine
    # before the `ecall` again.
    assert rows(out, "count")[2] == ["back", str(WHOLE + 1)]
    assert rows(out, "back 100")[0][0] == f"stepped {WHOLE + 1}"
    assert rows(out, "where")[0] == ["0x00400000 <main>", "addi x10,x0,7",
                                     "main:   li a0, 7", "main.s:5"]
    assert rows(out, "regs a0")[0] == ["a0", "x10", "0x00000000"]


# --------------------------------------------------- the same program, a window


def test_a_window_drives_the_same_program(tmp_path):
    told = Told()
    with RunController(told, out=io.StringIO()) as control:
        control.load(projects.read(written(tmp_path)))
        control.ask("break", lambda session: session.add_break(0x00400020))
        control.carry_on()
        control.finish()
        control.ask("registers", lambda session: session.registers(("a0",)))
        assert control.settled()
    assert [one.what for one in told.answers] == [LOAD, "break", "registers"]
    assert [one.value for one in told.answers[-1].value] == [14]
    assert told.snapshots[-1].place.address == 0x00400008
    assert told.snapshots[-1].instructions == 4  # li, jal, and the two of `double`


def test_the_console_and_a_window_agree_about_everything(tmp_path):
    """Two front ends, one session underneath: the same movements must leave the
    machine in the same state, or one of them is lying about the other."""
    code, out, _ = console(tmp_path, "step 4", "regs", "count")
    by_hand = {row[0]: row[2] for row in rows(out, "regs")}
    counted = {row[0]: row[1] for row in rows(out, "count")}

    told = Told()
    with RunController(told, out=io.StringIO()) as control:
        control.load(projects.read(written(tmp_path)))
        control.step(4)
        control.ask("registers", lambda session: session.registers())
        control.ask("count", lambda session: session.count())
        assert control.settled()
    by_window = {one.name: f"0x{one.value:08x}"
                 for one in told.answers[-2].value}
    assert by_window == by_hand
    assert str(told.answers[-1].value.instructions) == counted["instructions"]
    assert told.snapshots[-1].place.address == int(rows(out, "step 4")[0][1][:10], 16)


def test_a_window_over_a_run_being_watched_by_the_models(tmp_path):
    """What the command line asks for with flags, a window asks for here - and then
    shows it with the same questions the console answers with."""
    from pyrars.analysis.cache import Caches, Settings

    told = Told()
    with RunController(told, out=io.StringIO()) as control:
        control.load(projects.read(written(tmp_path)),
                     statistics=True, caches=Caches(Settings(sets=4)))
        control.carry_on()
        control.ask("lines", lambda session: session.cache_lines())
        control.ask("made of", lambda session: session.models.statistics.kinds())
        assert control.settled()
    lines = told.answers[-2].value
    assert [one.dirty for one in lines] == [True]  # the one block the program wrote
    assert told.answers[-1].value["store"] == 1
    assert told.snapshots[-1].turns == WHOLE  # the statistics counted the turns


def test_a_window_hears_of_a_watched_place(tmp_path):
    told = Told()
    with RunController(told, out=io.StringIO()) as control:
        control.load(projects.read(written(tmp_path)))
        control.ask("watch", lambda session: session.add_watch(
            session.address_of("kept"), session.address_of("kept") + 3, "write"))
        control.carry_on()
        assert control.settled()
    stopped = told.snapshots[-1].stopped
    assert stopped.reason == "watchpoint"
    assert stopped.touched[0].value == 14
    assert stopped.touched[0].by == 0x00400010  # the `sw` of the program


def test_a_window_over_a_project_that_cannot_be_assembled(tmp_path):
    told = Told()
    (tmp_path / "main.s").write_text(MAIN)
    (tmp_path / "lib.s").write_text("nonsense t0, t1\n")
    path = tmp_path / "thing.pyrars.json"
    path.write_text(json.dumps({"files": ["lib.s", "main.s"], "main": "main.s"}))
    with RunController(told, out=io.StringIO()) as control:
        control.load(projects.read(str(path)))
        control.step()
        assert control.settled()
    assert told.answers[0].value.failed is True
    assert told.snapshots == []
    assert [one.message for one in told.events if hasattr(one, "message")] == [
        "no program is open"]
