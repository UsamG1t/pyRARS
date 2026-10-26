"""The console: what pyRARS says in a terminal, and the debugger that reads from one.

RARS has no console debugger at all - it debugs in its window only, and the
architect works over ssh, where there is no window to open (D21). So this is a
front-end of our own: it reads a command, asks the session of
`pyrars.session.debug` for data, and writes that data out. All the knowing is in
the session, all the writing is here, and the window of M8 will show the same
session its own way.

Every line has one shape: the pieces are separated by " | ", and inside a table the
columns are padded so that they stand under one another (user decision 2026-10-14).
It reads by eye on a slow link and still cuts by " | " in a script. The help of one
command is NOT a table and must not look like one: its first line is the command
itself, what it takes and what it is for, divided by " -- ", and the rows under
`Args:` are the arguments. The alternative FORMS of a command are divided by "||"
and the choices inside one slot by a bare "|" (`del N|all`), neither of which can
be taken for the " | " of a table. The text of a
program line is given as the file has it only in `source`, which is a view of the
file; everywhere else it is one field among several and its own indentation would
tear a line apart, so it is stripped.

One terminal serves both the debugger and the program it runs, and the prompt says
whose turn it is to type: "(pyrars) " for a command, "program> " when the program
itself is asking for something (`SystemIO._asked`). What the program writes is
written as it is, with nothing in front of it. An answer that says no - a name
nobody has, a model that was never asked for - is still an answer and goes where
the answers go; only the failures of the tool itself go to the error stream.

Three commands are a guess and say so in their help: `over`, `finish` and `frames`
read the return address the way the convention says (D21).
"""

import signal
import sys
from contextlib import contextmanager
from dataclasses import dataclass

from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES
from pyrars.values import VALUE_FORMATS, ascii_text, value_text  # noqa: F401

from pyrars.core.systemio import ConsoleIO
from pyrars.session.debug import (
    BREAKPOINT, ENDED, EXITED, NOTHING, STEPPED, WATCHPOINT, Session, Stopped)

PROMPT = "(pyrars) "
ASKING = "program> "
BAR = " | "
HERE = "->"
WORD = 4

class TerminalIO(ConsoleIO):
    """The world of a program being debugged: the terminal it shares with the
    debugger, and a prompt of its own when it asks for something.

    Nothing is said when the program reads again what it has read before, after a
    step back: nobody is being asked for anything then (`ConsoleIO._asked`).
    """

    def __init__(self, asking: str = ASKING, **kept) -> None:
        super().__init__(**kept)
        self.asking = asking

    def _asked(self) -> None:
        self.out.write(self.asking)
        self.out.flush()
        self.fresh = False  # the prompt is on the line the answer will share

    def mark(self) -> object:
        """Where the world stands: what the program has read, and where every open
        file is - but NOT how much has been written.

        This terminal is shared with the debugger, and what has been printed on it
        has been seen. A step back cannot take it off the glass of a real terminal
        (DEV-53), and it must not take the debugger's own lines off a buffer that
        only looks cuttable, so nothing written here is ever taken back.
        """
        return (self.cursor, None, None,
                {fd: file.tell() for fd, file in self.files.items()})


# --------------------------------------------------------------- the commands


# What the arguments of the commands are, written once each: several commands are
# given the same kind of thing, and it must be said the same way every time.
A_PLACE = "an address (0x400010 or 4194320), a name of the program, or file:line"
A_RANGE = ("ADDRESS, or LOW..HIGH (LOW-HIGH as well); one address alone means the "
           "word it lies in, and either end may be a name of the program")
A_VALUE = "a number (0x..., 0b..., decimal, or negative), or a name of the program"
A_NUMBER = 'the number a place was given when it was added; "all" for every one of them'


def a_count(default: int) -> str:
    return f"how many, {default} by default"


def a_register(example: str) -> str:
    return (f"registers by name, with a space between them ({example}); "
            "all of them when none is given")


@dataclass(frozen=True, slots=True)
class Command:
    """One command of the debugger, as `help` tells of it."""

    name: str
    group: str
    takes: str  # what it is given, for the help
    about: str
    aliases: tuple[str, ...] = ()
    # Each argument of `takes` and what it means, for `? COMMAND`.
    arguments: tuple[tuple[str, str], ...] = ()


COMMANDS = (
    # the movement
    Command("step", "movement", "[N]", "carry out N instructions, one at a time", ("s",),
            (("N", a_count(1)),)),
    Command("over", "movement", "[N]", "like step, but a call is passed over - a GUESS "
            "from the convention", ("o", "next", "n"), (("N", a_count(1)),)),
    Command("back", "movement", "[N]", "take N steps back", ("b",),
            (("N", a_count(1)),)),
    Command("finish", "movement", "", "carry on out of the call the run is inside - a "
            "GUESS from the convention", ("fin",)),
    Command("continue", "movement", "", "carry on to a breakpoint, a watchpoint or the "
            "end of the run", ("c",)),
    Command("until", "movement", "PLACE", "carry on to a place, exactly", ("u",),
            (("PLACE", A_PLACE),)),
    Command("restart", "movement", "", "the program from the beginning; the breakpoints "
            "and the watches stay"),
    # the places
    Command("break", "places", "add PLACE || del N|all || list", "stop before the "
            "instruction at a place", (),
            (("add PLACE", "stop before the instruction at this place"),
             ("del N|all", "take a breakpoint off: " + A_NUMBER),
             ("list", "the breakpoints there are, which is what it does on its own"),
             ("PLACE", A_PLACE))),
    Command("watch", "places", "add RANGE [read|write|both] || del N|all || list",
            "stop when the program touches a place in memory", (),
            (("add RANGE", "watch this range of memory"),
             ("read|write|both", "what to watch for, both by default"),
             ("del N|all", "stop watching: " + A_NUMBER),
             ("list", "what is watched, which is what it does on its own"),
             ("RANGE", A_RANGE))),
    # the views
    Command("where", "views", "", "where the machine stands", ("w",)),
    Command("list", "views", "[PLACE] [N]", "N instructions around a place", ("l",),
            (("PLACE", "where to look, or where the machine stands when it is left "
                       "out - " + A_PLACE),
             ("N", a_count(10)))),
    Command("source", "views", "[N]", "N lines of the program around the run", ("src",),
            (("N", a_count(5)),)),
    Command("regs", "views", "[NAMES...]", "the integer registers", ("r",),
            (("NAMES", a_register("t0 x5 sp")),)),
    Command("fregs", "views", "[NAMES...]", "the floating point registers", ("f",),
            (("NAMES", a_register("ft1 fa0 f3")),)),
    Command("csr", "views", "[NAMES...]", "the control and status registers", (),
            (("NAMES", a_register("fcsr ustatus uie")),)),
    Command("mem", "views", "RANGE", "words of memory", ("m",),
            (("RANGE", A_RANGE),)),
    Command("data", "views", "[RANGE]", "the data the program laid out, as it stands now",
            ("d",), (("RANGE", "the part to show, or all of it when left out - "
                              + A_RANGE),)),
    Command("stack", "views", "[N]", "words from where the stack pointer stands", (),
            (("N", a_count(8) + ", counted up from the stack pointer"),)),
    Command("symbols", "views", "[PATTERN]", "the names of the program", ("syms",),
            (("PATTERN", "a piece of a name; only the names holding it are shown"),)),
    Command("frames", "views", "", "the calls the run is inside - a GUESS from the "
            "convention", ("bt",)),
    Command("count", "views", "", "where the run is in time"),
    # the things around the machine
    Command("device", "elements", "list || NAME", "what is attached, and what one holds", (),
            (("list", "what is attached, which is what it does on its own"),
             ("NAME", "one device, as `device list` names it; it says what it holds "
                      "itself, so a device from outside shows itself too"))),
    Command("cache", "elements", "info || show", "the settings and counters of the "
            "caches, or the blocks they hold", (),
            (("info", "what the caches ARE: every setting, then the counters"),
             ("show", "what they HOLD: a row for every block, and whether it is dirty"))),
    Command("pipeline", "elements", "info || show", "the settings and counters of the "
            "pipeline, or its diagram of cycles", (),
            (("info", "what the pipeline IS: the settings, the cycles, the cpi, what "
                      "was lost and to which hazard"),
             ("show", "what it HOLDS: the cycle each stage of each instruction began "
                      "in, as far back as `diagram` keeps"))),
    Command("guesser", "elements", "info || show", "how the pipeline guesses at a "
            "branch, or its table of history", (),
            (("info", "what the guesser IS, and how often it has been right"),
             ("show", "what it HOLDS: a row for every entry of its table, which only "
                      "a guesser asked for with predictor=table has"))),
    Command("stats", "elements", "", "what the run was made of"),
    # the changes
    Command("set", "changes", "NAME VALUE", "put a value in a register; no step back "
            "undoes it", (),
            (("NAME", "a register of any file: t0, x5, ft1, fcsr"),
             ("VALUE", A_VALUE))),
    Command("poke", "changes", "ADDRESS VALUE [SIZE]", "put a value in memory; no step "
            "back undoes it", (),
            (("ADDRESS", A_PLACE),
             ("VALUE", A_VALUE),
             ("SIZE", "bytes to write: 1, 2, 4 or 8, four by default"))),
    # the session
    Command("format", "session", "[hex|dec|ascii]", "how values are written", (),
            (("hex", "as many hexadecimal digits as the thing is wide"),
             ("dec", "as a signed number"),
             ("ascii", "as the characters of its bytes, an unprintable one as a full stop"),
             ("", "the format it is now, when none is given"))),
    Command("help", "session", "[COMMAND]", "this, or one command in full", ("h", "?"),
            (("COMMAND", "a command by its name or by any of its aliases; what it is "
                         "given is explained argument by argument"),)),
    Command("quit", "session", "", "end the session", ("q",)),
)

BY_NAME = {}
for _command in COMMANDS:
    BY_NAME[_command.name] = _command
    for _alias in _command.aliases:
        BY_NAME[_alias] = _command

GROUPS = ("movement", "places", "views", "elements", "changes", "session")

# What may follow a command, which is what a completion offers (OPEN-5). The names
# of the program come from the program itself, and the registers from
# `pyrars.isa.registers` - the same tables the editor of M8 will complete from,
# because they are the only ones the two front-ends have in common.
FOLLOWS = {
    "break": ("add", "del", "list"),
    "watch": ("add", "del", "list"),
    "device": ("list",),
    "cache": ("info", "show"),
    "pipeline": ("info", "show"),
    "guesser": ("info", "show"),
    "format": VALUE_FORMATS,
    "help": tuple(name for name in BY_NAME),
}
# The commands whose first word is a verb of their own, after which what they are
# given begins: `break add main`, not `break main`.
TWO_LEVEL = frozenset({"break", "watch", "device", "cache", "pipeline", "guesser"})
TAKES_A_PLACE = frozenset({"until", "list", "break", "poke", "mem", "data", "watch"})
TAKES_A_REGISTER = frozenset({"regs", "set"})
TAKES_A_FLOAT = frozenset({"fregs"})
TAKES_A_CSR = frozenset({"csr", "set"})

# What a movement ended on, where the word is not the reason itself.
AFTER = {STEPPED: "stepped"}


class Debugger:
    """A session of debugging at a terminal."""

    def __init__(self, session: Session, out, errors, reader,
                 echo: bool = False) -> None:
        self.session = session
        self.out = out
        self.errors = errors
        self.reader = reader
        self.echo = echo  # a scripted session shows the commands it obeys
        self.format = "hex"
        self.last = ""  # what an empty line repeats
        self.going = True
        self.code = 0  # what the tool itself ends with
        self.names = sorted(session.program.symbols.items(), key=lambda one: one[1])

    # ------------------------------------------------------------- the session

    def obey(self, line: str) -> None:
        """One command."""
        text = line.split("#", 1)[0].strip()
        if not text:
            text = self.last  # an empty line repeats the last command
            if not text:
                return  # a comment, or a blank line with nothing to repeat
        if self.echo:
            print(PROMPT + text, file=self.out)
        self.last = text
        words = text.split()
        command = BY_NAME.get(words[0])
        if command is None:
            self._no(f'no command "{words[0]}": try help')
            return
        try:
            getattr(self, "_" + command.name)(words[1:])
        except ValueError as problem:
            self._no(str(problem))

    def script(self, lines) -> None:
        """Commands from a file or from the command line, in the order given."""
        for line in lines:
            if not self.going:
                return
            self.obey(line)

    def interact(self) -> None:
        """The prompt, until the input ends or the session is told to stop."""
        if self.reader is sys.stdin and sys.stdin.isatty():
            self._complete_at_a_terminal()
        while self.going:
            line = self._asked_for_a_command()
            if line is None:
                return
            self.obey(line)

    def _asked_for_a_command(self) -> str | None:
        """One line from whoever is driving; None when there is no more input.

        A real terminal is read through `input`, so that the line editing and the
        completions of `readline` work; anything else is read as a plain stream,
        which is what a script and a test are.
        """
        self._fresh()
        if self.reader is sys.stdin and sys.stdin.isatty():
            try:
                return input(PROMPT)
            except EOFError:
                print(file=self.out)
                return None
        self.out.write(PROMPT)
        line = self.reader.readline()
        if not line:
            print(file=self.out)
            return None
        self.out.write(line if line.endswith("\n") else line + "\n")
        return line

    # ------------------------------------------------------------ the movement

    def _moved(self, movement) -> None:
        """A movement of the machine, and what it ended on. While it runs, Ctrl-C
        pauses it rather than ending the session."""
        with self._stoppable():
            stopped = movement()
        self._told(stopped)

    @contextmanager
    def _stoppable(self):
        """Ctrl-C asks the machine to stop where it is.

        Only the main thread of a process may be given a signal, so where this is
        not it - a test, or a window driving a session - nothing is installed and
        Ctrl-C does whatever it did before.
        """
        def pause(number, frame) -> None:
            self.session.simulator.pause()

        try:
            before = signal.signal(signal.SIGINT, pause)
        except ValueError:
            yield
            return
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, before)

    def _step(self, words: list[str]) -> None:
        count = self._many(words)
        self._moved(lambda: self.session.step(count))

    def _over(self, words: list[str]) -> None:
        count = self._many(words)
        self._moved(lambda: self.session.over(count))

    def _back(self, words: list[str]) -> None:
        count = self._many(words)
        self._moved(lambda: self.session.back(count))

    def _finish(self, words: list[str]) -> None:
        self._moved(self.session.finish)

    def _continue(self, words: list[str]) -> None:
        self._moved(self.session.carry_on)

    def _until(self, words: list[str]) -> None:
        if not words:
            raise ValueError("until needs a place: an address, a name or file:line")
        place = self.session.address_of(words[0])
        self._moved(lambda: self.session.until(place))

    def _restart(self, words: list[str]) -> None:
        stopped = self.session.restart()
        self._rows([["restarted", *self._place_fields(stopped.place)]])

    # -------------------------------------------------------------- the places

    def _break(self, words: list[str]) -> None:
        what, rest = self._verb(words, ("add", "del", "list"))
        if what == "add":
            if not rest:
                raise ValueError("break add needs a place: an address, a name or file:line")
            broken = self.session.add_break(self.session.address_of(rest[0]))
            self._rows([self._break_row(broken)])
        elif what == "del":
            gone = self.session.remove_break(self._which(rest))
            self._rows([["gone", str(one.id), *self._place_fields(one.place)]
                        for one in gone] or [["nothing to take off"]])
        else:
            self._rows([self._break_row(one) for one in self.session.breaks()]
                       or [["no breakpoints"]])

    def _break_row(self, broken) -> list[str]:
        return [str(broken.id), *self._place_fields(broken.place)]

    def _watch(self, words: list[str]) -> None:
        what, rest = self._verb(words, ("add", "del", "list"))
        if what == "add":
            if not rest:
                raise ValueError("watch add needs a range: ADDRESS or LOW..HIGH")
            low, high = self._range(rest[0])
            kind = rest[1] if len(rest) > 1 else "both"
            self._rows([self._watch_row(self.session.add_watch(low, high, kind))])
        elif what == "del":
            gone = self.session.remove_watch(self._which(rest))
            self._rows([["gone", *self._watch_row(one)] for one in gone]
                       or [["nothing to take off"]])
        else:
            self._rows([self._watch_row(one) for one in self.session.watches()]
                       or [["nothing is watched"]])

    def _watch_row(self, watched) -> list[str]:
        return [str(watched.id), watched.kind,
                f"0x{watched.low:08x}..0x{watched.high:08x}", f"hits {watched.hits}"]

    # --------------------------------------------------------------- the views

    def _where(self, words: list[str]) -> None:
        self._rows([self._place_fields(self.session.where())])

    def _list(self, words: list[str]) -> None:
        place = self.session.address_of(words[0]) if words else None
        count = self._many(words[1:], 10)
        rows = []
        for row in self.session.listing(place, count):
            rows.append([HERE if row.at else "",
                         str(row.breakpoint) if row.breakpoint else "",
                         *self._place_fields(row.place)])
        self._rows(rows or [["nothing of the program is there"]])

    def _source(self, words: list[str]) -> None:
        lines = self.session.source(self._many(words, 5))
        self._rows([[HERE if line.at else "", str(line.line), line.text]
                    for line in lines] or [["the place the machine stands at is in no "
                                            "file of the program"]])

    def _regs(self, words: list[str]) -> None:
        self._values(self.session.registers(tuple(words)))

    def _fregs(self, words: list[str]) -> None:
        self._values(self.session.floats(tuple(words)))

    def _csr(self, words: list[str]) -> None:
        self._values(self.session.csr(tuple(words)))

    def _values(self, values) -> None:
        """Registers, whatever file they come from: the name the convention gives
        them, the number the machine gives them, the value, and what it means."""
        rows = []
        for value in values:
            number = (f"0x{value.number:03x}" if value.file == "csr"
                      else f"{value.file}{value.number}")
            row = [value.name, number,
                   value_text(value.value, value.bits, self.format)]
            if value.about:
                row.append(value.about)
            rows.append(row)
        self._rows(rows)

    def _mem(self, words: list[str]) -> None:
        if not words:
            raise ValueError("mem needs a range: ADDRESS or LOW..HIGH")
        low, high = self._range(words[0])
        rows = [[f"0x{row.address:08x}",
                 *(value_text(value, 32, self.format) for value in row.values)]
                for row in self.session.memory(low, high)]
        self._rows(rows)

    def _data(self, words: list[str]) -> None:
        low, high = self._range(words[0]) if words else (None, None)
        rows = []
        for item in self.session.data(low, high):
            row = [f"0x{item.address:08x}", item.directive, str(item.size),
                   " ".join(value_text(value, min(item.size, WORD) * 8, self.format)
                            for value in item.values)]
            if item.text:
                row.append(f'"{item.text}"')
            rows.append(row)
        self._rows(rows or [["the program laid out no data there"]])

    def _stack(self, words: list[str]) -> None:
        frames = self.session.frames()
        rows = []
        for word in self.session.stack(self._many(words, 8)):
            row = [f"0x{word.address:08x}", value_text(word.value, 32, self.format)]
            if word.frame is not None and word.frame < len(frames):
                row.append(f"frame {word.frame + 1} "
                           f"{frames[word.frame].called.symbol or ''}".strip())
            rows.append(row)
        self._rows(rows)

    def _symbols(self, words: list[str]) -> None:
        found = self.session.symbols(words[0] if words else "")
        self._rows([[one.name, f"0x{one.address:08x}",
                     "global" if one.public else "local"] for one in found]
                   or [["no name of the program matches"]])

    def _frames(self, words: list[str]) -> None:
        rows = [[str(frame.depth), *self._place_fields(frame.called),
                 f"from {self._at(frame.called_from.address)}",
                 "sp ?" if frame.sp is None else f"sp 0x{frame.sp:08x}"]
                for frame in self.session.frames()]
        self._rows(rows or [["the run is inside no call"]])

    def _count(self, words: list[str]) -> None:
        counted = self.session.count()
        self._rows([["instructions", str(counted.instructions)],
                    ["turns", str(counted.turns)],
                    ["back", str(counted.back)]])

    # ------------------------------------------- the things around the machine

    def _device(self, words: list[str]) -> None:
        attached = self.session.devices()
        if not attached:
            raise ValueError("no device is attached: run with --device")
        if not words or words[0] == "list":
            base = self.session.options.config.mmio_base
            self._rows([[one.name,
                         "?" if one.offset is None else f"0x{base + one.offset:08x}",
                         "?" if one.size is None else f"{one.size} bytes"]
                        for one in attached])
            return
        seen = self.session.device(words[0])
        self._rows([[name, _cell(value)] for name, value in seen.state.items()]
                   or [[seen.name, "says nothing of itself"]])

    def _cache(self, words: list[str]) -> None:
        caches = self.session.caches()
        if not caches:
            raise ValueError("no cache was asked for: run with --cache")
        if self._shown(words):
            rows = [[line.side, f"set {line.set}", f"place {line.place}",
                     f"0x{line.low:08x}..0x{line.high:08x}",
                     "dirty" if line.dirty else "clean"]
                    for line in self.session.cache_lines()]
            self._rows(rows or [["the caches hold nothing yet"]])
            return
        rows = []
        for cache in caches:
            rows += [[cache.side, one.name, str(one.value)]
                     for one in cache.settings]
            rows += [[cache.side, name, str(value)] for name, value in
                     (("accesses", cache.accesses), ("hits", cache.hits),
                      ("misses", cache.misses), ("rate", round(cache.rate, 4)),
                      ("writebacks", cache.writebacks), ("through", cache.through))]
        self._rows(rows)

    def _pipeline(self, words: list[str]) -> None:
        pipeline = self.session.pipeline()
        if pipeline is None:
            raise ValueError("no pipeline was asked for: run with --pipeline")
        if self._shown(words):
            rows = [[f"0x{row.address:08x}", row.mnemonic,
                     " ".join(str(cycle) for cycle in row.starts)]
                    for row in self.session.diagram()]
            self._rows(rows or [["the pipeline kept no diagram"]])
            return
        rows = [[one.name, _settled(one.value)] for one in pipeline.settings]
        rows += [["cycles", str(pipeline.cycles)],
                 ["instructions", str(pipeline.instructions)],
                 ["cpi", str(round(pipeline.cpi, 4))],
                 ["lost", str(pipeline.lost)]]
        rows += [[f"lost.{one.name}", str(one.value)] for one in pipeline.stalls]
        rows += [["branches", str(pipeline.branches)],
                 ["wrong", str(pipeline.wrong)]]
        self._rows(rows)

    def _guesser(self, words: list[str]) -> None:
        guesser = self.session.guesser()
        if guesser is None:
            raise ValueError("no guesser was asked for: run with --pipeline")
        if self._shown(words):
            rows = [[str(entry.entry), str(entry.counter),
                     "taken" if entry.taken else "not taken",
                     f"right {entry.right}", f"wrong {entry.wrong}"]
                    for entry in self.session.guesser_entries()]
            if not rows:
                raise ValueError("no table of history was asked for: run with "
                                 "--pipeline predictor=table")
            self._rows(rows)
            return
        rows = [["guesser", guesser.name]]
        rows += [[one.name, str(one.value)] for one in guesser.settings]
        rows += [["guesses", str(guesser.guesses)], ["right", str(guesser.right)],
                 ["wrong", str(guesser.wrong)],
                 ["accuracy", str(round(guesser.accuracy, 4))]]
        self._rows(rows)

    def _stats(self, words: list[str]) -> None:
        statistics = self.session.statistics()
        if statistics is None:
            raise ValueError("no statistics were asked for: run with --stats")
        rows = [["instructions", str(statistics.instructions)],
                ["turns", str(statistics.turns)],
                ["traps", str(statistics.traps)],
                ["unknown", str(statistics.unknown)]]
        rows += [[f"kind.{one.name}", str(one.value)] for one in statistics.kinds]
        rows += [[f"category.{one.name.lower()}", str(one.value)]
                 for one in statistics.categories]
        rows += [["branches.taken", str(statistics.taken)],
                 ["branches.not-taken", str(statistics.not_taken)]]
        self._rows(rows)

    # ------------------------------------------------------------- the changes

    def _set(self, words: list[str]) -> None:
        if len(words) < 2:
            raise ValueError("set needs a register and a value")
        self._values([self.session.set_register(words[0], self._number(words[1]))])

    def _poke(self, words: list[str]) -> None:
        if len(words) < 2:
            raise ValueError("poke needs an address and a value")
        size = self._many(words[2:], WORD)
        if size not in (1, 2, 4, 8):
            raise ValueError(f"{size}: a value in memory is 1, 2, 4 or 8 bytes wide")
        put = self.session.poke(self.session.address_of(words[0]),
                                self._number(words[1]), size)
        self._rows([[f"0x{put.address:08x}",
                     value_text(put.values[0], size * 8, self.format)]])

    # ------------------------------------------------------------- the session

    def _format(self, words: list[str]) -> None:
        if not words:
            self._rows([["format", self.format]])
            return
        if words[0] not in VALUE_FORMATS:
            raise ValueError(f'"{words[0]}": values are written as '
                             f'{", ".join(VALUE_FORMATS)}')
        self.format = words[0]
        self._rows([["format", self.format]])

    def _help(self, words: list[str]) -> None:
        """Every command and what it is for, or one command argument by argument."""
        if words:
            command = BY_NAME.get(words[0])
            if command is None:
                raise ValueError(f'no command "{words[0]}": try help')
            self._line(_synopsis(command))
            # And what each of those arguments is, which is the whole point of
            # asking about one command rather than reading the list.
            if command.arguments:
                self._line("Args:")
                self._rows([[name or "nothing", about]
                            for name, about in command.arguments])
            return
        rows = []
        for group in GROUPS:
            for command in COMMANDS:
                if command.group == group:
                    rows.append([group, command.name, command.takes, command.about])
        self._rows(rows)
        self._rows([['"? COMMAND" says what that one is given, argument by argument, '
                     'and what else it may be called']])

    def _quit(self, words: list[str]) -> None:
        self.going = False

    # ------------------------------------------------------------ the printing

    def _told(self, stopped: Stopped) -> None:
        """What a movement ended on: a line for every touch, the message of a trap,
        and one line that says where the machine stands (user decision 2026-10-14)."""
        self._rows([[f"touched {touch.id}", touch.kind, f"0x{touch.address:08x}",
                     f"{touch.size} bytes",
                     value_text(touch.value, touch.size * 8, self.format),
                     f"by {self._at(touch.by)}"] for touch in stopped.touched])
        if stopped.message:
            self._rows([["trap", stopped.message]])
        self._rows([[self._what(stopped), *self._place_fields(stopped.place)]])
        if stopped.reason == ENDED:
            self._rows([["the run is over: restart it, or take a step back"]])
        if stopped.reason == EXITED:
            self.code = stopped.code

    def _what(self, stopped: Stopped) -> str:
        """The first field of a movement: what happened, and how far it went."""
        if stopped.reason == STEPPED:
            return f"stepped {stopped.steps}"
        if stopped.reason == NOTHING:
            return "nothing"
        if stopped.reason == ENDED:
            return "ended"
        if stopped.reason == BREAKPOINT:
            return f"breakpoint {stopped.breakpoint} after {stopped.steps}"
        if stopped.reason == WATCHPOINT:
            return f"watchpoint {stopped.touched[0].id} after {stopped.steps}"
        if stopped.reason == EXITED:
            return f"exited {stopped.code} after {stopped.steps}"
        return f"{stopped.reason} after {stopped.steps}"

    def _place_fields(self, place) -> list[str]:
        """A place as the fields of a line, the empty ones left out."""
        fields = [self._at(place.address)]
        if place.basic:
            fields.append(place.basic)
        if place.source:
            fields.append(place.source.strip())
        if place.file:
            fields.append(f"{_short(place.file)}:{place.line}")
        return fields

    def _at(self, address: int) -> str:
        """An address, with the name of the program it falls under.

        The nearest name AT or BELOW the address, inside the same segment: the
        labels of a program divide its text and its data between them, so the one
        before an address is the one the address belongs to. Where a segment holds
        no name at all, the address stands by itself.
        """
        found = ""
        offset = 0
        for name, place in self.names:
            if place <= address and self._segment(place) == self._segment(address):
                found, offset = name, address - place
        if not found:
            return f"0x{address:08x}"
        return f"0x{address:08x} <{found}{f'+{offset}' if offset else ''}>"

    def _segment(self, address: int) -> str:
        config = self.session.options.config
        if config.text_base <= address <= config.text_limit:
            return "text"
        if config.data_segment_base <= address <= config.data_segment_limit:
            return "data"
        return ""

    def _rows(self, rows) -> None:
        """Rows of a table: the pieces separated by " | ", the columns padded so
        that they stand under one another."""
        if not rows:
            return
        self._fresh()
        width = max(len(row) for row in rows)
        full = [list(row) + [""] * (width - len(row)) for row in rows]
        widths = [max(len(row[index]) for row in full) for index in range(width)]
        for row in full:
            while row and not row[-1]:
                row.pop()  # a row says nothing where it has nothing to say
            line = BAR.join(cell.ljust(widths[index])
                            for index, cell in enumerate(row))
            print(line.rstrip(), file=self.out)

    def _line(self, text: str) -> None:
        """One line that is no row of a table."""
        self._fresh()
        print(text, file=self.out)

    def _no(self, why: str) -> None:
        """An answer that says no. It is still an answer, so it goes to the output
        with everything else; only the failures of the tool go to the errors."""
        self._rows([["error", why]])

    def _fresh(self) -> None:
        """A program that wrote no newline keeps its own line."""
        world = self.session.io
        if getattr(world, "fresh", True) is False:
            print(file=self.out)
            world.fresh = True

    # ----------------------------------------------------------- the completions

    def completions(self, line: str, word: str) -> list[str]:
        """What a word at the end of a line could be meant to be (OPEN-5).

        The first word of a line is a command; after that it is whatever the
        command is given - the verb of a two-level command, a name of the program,
        a register, a device, a format.
        """
        words = line.split()
        where = len(words) - (0 if line.endswith(" ") else 1)  # the word being typed
        if where <= 0:
            return sorted(name for name in BY_NAME if name.startswith(word))
        command = BY_NAME.get(words[0])
        if command is None:
            return []
        offered = set()
        if where == 1:
            offered |= set(FOLLOWS.get(command.name, ()))
        # What a command is GIVEN begins after its own verb, where it has one.
        given = where >= (2 if command.name in TWO_LEVEL else 1)
        if given:
            if command.name in TAKES_A_PLACE:
                offered |= set(self.session.program.symbols)
            if command.name in TAKES_A_REGISTER:
                offered |= set(X_NAMES) | set(X_ALIASES)
            if command.name in TAKES_A_FLOAT:
                offered |= set(F_NAMES)
            if command.name in TAKES_A_CSR:
                offered |= set(CSRS)
            if command.name == "device":
                offered |= {one.name for one in self.session.devices()}
        if command.name == "watch" and where >= 3:
            offered |= {"read", "write", "both"}
        return sorted(one for one in offered if one.startswith(word))

    def _completing(self, word: str, state: int) -> str | None:
        """What `readline` asks for: one answer at a time."""
        import readline

        if state == 0:
            self._offered = self.completions(readline.get_line_buffer(), word)
        return self._offered[state] if state < len(self._offered) else None

    def _complete_at_a_terminal(self) -> None:
        """Let the terminal complete a word with the tab key, where it can."""
        try:
            import readline
        except ImportError:  # a platform without it; the session works all the same
            return
        readline.set_completer(self._completing)
        readline.set_completer_delims(" \t\n")
        readline.parse_and_bind("tab: complete")

    # -------------------------------------------------------- reading a command

    def _verb(self, words: list[str], verbs: tuple[str, ...]) -> tuple[str, list[str]]:
        """The second level of a command: `break add`, `watch list`. A command
        without one is the last of the verbs, which is always the asking one."""
        if not words:
            return verbs[-1], []
        if words[0] not in verbs:
            raise ValueError(f'"{words[0]}": the word after it is '
                             f'{", ".join(verbs)}')
        return words[0], words[1:]

    def _shown(self, words: list[str]) -> bool:
        """Whether an element was asked to show what it holds rather than what it
        is: `cache show` against `cache info`."""
        what, _ = self._verb(words, ("show", "info"))
        return what == "show"

    def _which(self, words: list[str]) -> int | None:
        """The number of one breakpoint or watch, or None for all of them."""
        if not words or words[0] == "all":
            return None
        return self._number(words[0])

    def _range(self, text: str) -> tuple[int, int]:
        """A range of memory: LOW..HIGH, LOW-HIGH, or one place, which is one word.
        The ends are places, so a name of the program serves for either."""
        for mark in ("..", "-"):
            low, sign, high = text.partition(mark)
            if sign and low:
                return self._number(low), self._number(high)
        place = self._number(text)
        return place, place + WORD - 1

    def _many(self, words: list[str], default: int = 1) -> int:
        """How many times a command was asked for."""
        if not words:
            return default
        count = self._number(words[0])
        if count < 0:
            raise ValueError(f"{count}: a count is never below nothing")
        return count

    def _number(self, text: str) -> int:
        """A number as a person writes it: decimal, 0x..., 0b..., or a name of the
        program."""
        try:
            return int(text, 0)
        except ValueError:
            return self.session.address_of(text)


def _synopsis(command: Command) -> str:
    """The first line of the help of one command: what it is called, what it takes
    and what it is for. The forms of a command that holds several are kept together
    in brackets, so that what follows " -- " is plainly the one thing it is for."""
    names = ", ".join((command.name,) + command.aliases)
    takes = f"[{command.takes}]" if "||" in command.takes else command.takes
    return f"{names} {takes} -- {command.about}".replace("  ", " ")


def _cell(value) -> str:
    """One thing a device says of itself, as a cell of a table. A row stays one
    row, so the newlines of a text are shown instead of printed, and a cell with
    nothing in it says so rather than looking like a heading."""
    text = str(value)
    if not text:
        return "-"
    return text.replace("\n", "\\n").replace("\t", "\\t")


def _settled(value) -> str:
    """One setting of a model, as a line of a table shows it."""
    if isinstance(value, dict):
        return " ".join(f"{_named(name)}={many}" for name, many in value.items()) or "-"
    return str(value)


def _named(what) -> str:
    return what.name.lower() if hasattr(what, "name") else str(what)


def _short(path: str) -> str:
    """The name of a file without the way to it: a transcript must not depend on
    where the program happens to live."""
    return path.rsplit("/", 1)[-1]
