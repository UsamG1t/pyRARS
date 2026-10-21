"""A session of debugging: what a run looks like when someone is watching it.

The session holds the machine, the program it runs, the places to stop at, the
things to watch, and the models that count - and it offers one method per command
of a debugger. Every one of them answers in DATA: a place, a list of values, what
a movement ended on. Nothing here renders anything, because a terminal and a
window must be able to show the same session each in its own way.

What it is made of is all of M4 and M6: the simulator steps, runs to a breakpoint
and steps back; the journal of the machine is what makes `back` possible at all,
so a session always keeps one; `Memory.subscribe` is what a thing to watch is; the
models of `pyrars.analysis` are fed every turn, and a stack of calls among them
always, because stepping OVER a call has to know where the call ends.

Three of the commands are a guess, and must be offered as one (D21): stepping over
a call, finishing one, and the frames themselves all read `ra` the way the
convention says, so a program that keeps its return address elsewhere will send
them astray. `until` is the exact one.

A change made by `set` or `poke` is not a step of the machine, so a step back does
not undo it; the answer of the command says so (the rule of the journal, stage 21).
"""

from dataclasses import dataclass, field, fields, replace

from pyrars.analysis.cache import Caches
from pyrars.analysis.callstack import CallStack, Frame
from pyrars.analysis.pipeline import Pipeline
from pyrars.analysis.stats import Statistics
from pyrars.analysis.watchers import Watchers
from pyrars.asm import disasm
from pyrars.core.machine import Machine
from pyrars.core.memory import Access, MemAccess
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop, StopReason, Stepped
from pyrars.core.systemio import ConsoleIO, SystemIO
from pyrars.isa.classes import Kind, kind
from pyrars.isa.program import AssembledProgram
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES
from pyrars.softfloat.formats import BINARY32, BINARY64
from pyrars.softfloat.text import to_text

SP = 2  # the register the convention keeps a stack pointer in
WORD = 4
ROWS = 4  # words of memory to a row

# What a movement ended on, as a session says it.
STEPPED = "stepped"
BREAKPOINT = "breakpoint"
WATCHPOINT = "watchpoint"
EXITED = "exited"
CLIFF = "cliff"
LIMIT = "limit"
WAITING = "waiting"
TRAPPED = "trapped"
PAUSED = "paused"  # the machine stands, and the run may go on from there
STOPPED = "stopped"  # the run was told to end where it was
NOTHING = "nothing"  # there was nothing to do
ENDED = "ended"  # the run is over, and nothing but a restart or a step back follows

REASONS = {
    StopReason.NORMAL_TERMINATION: EXITED,
    StopReason.CLIFF_TERMINATION: CLIFF,
    StopReason.MAX_STEPS: LIMIT,
    StopReason.WAITING: WAITING,
    StopReason.EXCEPTION: TRAPPED,
    StopReason.BREAKPOINT: BREAKPOINT,
    StopReason.PAUSE: PAUSED,
    StopReason.STOP: STOPPED,
}


@dataclass(frozen=True, slots=True)
class Place:
    """An address, and everything the program says about it."""

    address: int
    word: int = 0
    basic: str = ""  # the instruction as text
    symbol: str = ""  # the name of the address, where it has one
    file: str = ""
    line: int = 0
    source: str = ""  # the line of the program it came from


@dataclass(frozen=True, slots=True)
class Touched:
    """A thing being watched was touched."""

    id: int
    kind: str  # "read" or "write"
    address: int
    size: int
    value: int
    by: int  # the address of the instruction that did it


@dataclass(frozen=True, slots=True)
class Stopped:
    """What a movement ended on."""

    reason: str
    place: Place
    steps: int = 0  # instructions carried out by this movement
    message: str = ""  # what a trap said
    code: int = 0  # what the program exited with
    touched: tuple[Touched, ...] = ()
    breakpoint: int | None = None  # which breakpoint it was, where it was one


@dataclass(frozen=True, slots=True)
class Value:
    """One register, as a view of registers gives it."""

    name: str
    number: int
    value: int
    bits: int
    about: str = ""  # what the value means, where that is worth saying
    file: str = "x"  # which file it belongs to: "x", "f" or "csr"


@dataclass(frozen=True, slots=True)
class Row:
    """One row of the text segment."""

    place: Place
    at: bool = False  # whether the machine stands here
    breakpoint: int | None = None


@dataclass(frozen=True, slots=True)
class SourceLine:
    """One line of a program."""

    file: str
    line: int
    text: str
    at: bool = False


@dataclass(frozen=True, slots=True)
class Words:
    """A row of memory."""

    address: int
    values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Item:
    """One thing a data directive put in memory, as it stands now."""

    address: int
    directive: str
    size: int
    values: tuple[int, ...]
    text: str = ""  # the bytes as characters, for the directives that hold text


@dataclass(frozen=True, slots=True)
class StackWord:
    """One word of the stack."""

    address: int
    value: int
    frame: int | None = None  # the call whose frame begins here


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    address: int
    public: bool


@dataclass(frozen=True, slots=True)
class Breakpoint:
    id: int
    place: Place


@dataclass(frozen=True, slots=True)
class Watchpoint:
    id: int
    low: int
    high: int
    kind: str  # "read", "write" or "both"
    hits: int = 0


@dataclass(frozen=True, slots=True)
class FrameSeen:
    """One call the run is inside - a guess from the convention."""

    depth: int
    called: Place
    called_from: Place
    sp: int | None


@dataclass(frozen=True, slots=True)
class DeviceSeen:
    name: str
    offset: int | None
    size: int | None
    state: dict[str, object]  # what to READ about it, in its own words
    looks: dict[str, object] = field(default_factory=dict)  # and what to DRAW it by


@dataclass(frozen=True, slots=True)
class CacheLine:
    """One block a cache holds.

    `place` is where in the set it sits, and that is also its age: a cache that
    replaces by lru or fifo makes room by throwing out the one at place 0. A set
    holds fewer blocks than it has ways until a run has filled it.
    """

    side: str
    set: int
    place: int
    tag: int
    low: int  # the addresses the block covers
    high: int
    dirty: bool


@dataclass(frozen=True, slots=True)
class GuesserEntry:
    """One entry of a table of history."""

    entry: int
    counter: int
    taken: bool
    right: int
    wrong: int


@dataclass(frozen=True, slots=True)
class Setting:
    """One thing a model was built with, or one thing it counted, by name.

    A model is built from a dataclass of its own and counts whatever it counts;
    what every front end does with it is the same - puts the name beside the value
    - so the session hands it over in that shape and neither of them has to know
    the fields of a model by heart.
    """

    name: str
    value: object


@dataclass(frozen=True, slots=True)
class CacheSeen:
    """One cache of a run: how it was built, and how it has fared."""

    side: str  # "cache" where there is one for everything, else "data"/"instructions"
    fetches: bool  # whether the addresses of the instructions reach this one
    settings: tuple[Setting, ...]
    accesses: int
    hits: int
    misses: int
    rate: float
    writebacks: int
    through: int


@dataclass(frozen=True, slots=True)
class PipelineSeen:
    """The time a run would have taken, as the model of it counted."""

    settings: tuple[Setting, ...]
    cycles: int
    instructions: int
    cpi: float
    lost: int  # cycles nothing was carried out in
    stalls: tuple[Setting, ...]  # by what caused them
    branches: int
    wrong: int  # branches guessed wrongly


@dataclass(frozen=True, slots=True)
class StageSeen:
    """Where one instruction was in which cycle, as a diagram shows it."""

    address: int
    mnemonic: str
    starts: tuple[int, ...]  # the cycle each of the five stages began in
    ex_cycles: int
    waited: int


@dataclass(frozen=True, slots=True)
class GuesserSeen:
    """How the machine of the model guessed where the branches went."""

    name: str
    settings: tuple[Setting, ...]  # the entries and the bits, where it has them
    guesses: int
    right: int
    wrong: int
    accuracy: float


@dataclass(frozen=True, slots=True)
class StatisticsSeen:
    """What a run was made of."""

    turns: int
    instructions: int
    traps: int
    unknown: int
    taken: int  # branches that went
    not_taken: int
    kinds: tuple[Setting, ...]  # by the kind of instruction, the unmet left out
    categories: tuple[Setting, ...]  # and by the five RARS counts by


@dataclass(frozen=True, slots=True)
class Counted:
    """Where the run is in time."""

    instructions: int
    turns: int
    back: int  # steps that can still be taken back


class Session:
    """One run being debugged."""

    def __init__(self, program: AssembledProgram, options: Options | None = None,
                 io: SystemIO | None = None, bus=None, arguments: tuple[str, ...] = (),
                 statistics: bool = False, caches: Caches | None = None,
                 pipeline: Pipeline | None = None, fetches: bool = False,
                 limit: int | None = None, watch=None) -> None:
        self.program = program
        # A session keeps a journal, for `back` is the point of one, and takes the
        # world back with a step (the decision of stage 21).
        given = options or Options(xlen=program.xlen)
        self.options = replace(given, debug=True,
                               history_depth=given.history_depth or 2000)
        self.io = io if io is not None else ConsoleIO()
        self.bus = bus
        self.arguments = arguments
        # No movement of the session runs longer than this, so that a session
        # driven by a script cannot be caught for ever by a program without an end.
        self.limit = limit
        # Whoever drives the session may hear every turn of the loop: a window
        # makes its snapshots from this instead of cutting a run into pieces
        # (stage 39). A session driven by hand sets nothing and pays a comparison.
        self.watch = watch
        # Whether the addresses of the instructions reach a cache is the caller's
        # to say: a cache FOR EVERYTHING and a cache of the data alone are the
        # same object, and only whoever asked for it knows which was meant.
        self.wanted = (statistics, caches, pipeline, fetches)
        self.format = "hex"

        self._places = {entry.address: entry for entry in program.text}
        self._names = {address: name for name, address in program.symbols.items()}
        self._breaks: dict[int, int] = {}
        self._watches: dict[int, Watchpoint] = {}
        self._ends: dict[int, object] = {}  # how to end a watch
        self._next_id = 1
        self._pending: list[tuple[int, MemAccess]] = []
        self._touched: list[Touched] = []
        # Whether the run is over. A program that has exited, run off the end of
        # its text or trapped with nowhere to go does not go on, and a movement
        # says so instead of wandering: the way back is a restart - or a step
        # back, for the journal reaches over the end of a run like anywhere else.
        self.ended = False
        self._build()

    # ------------------------------------------------------------- the machine

    def _build(self) -> None:
        """A machine, a simulator and the models, as at the start of a run."""
        self.machine = Machine(self.options, bus=self.bus, io=self.io)
        if self.bus is not None:
            self.bus.reset()  # a restart puts a device back where it began too
            self.bus.connect(self.machine)
        self.simulator = Simulator(self.machine)
        statistics, caches, pipeline, fetches = self.wanted
        self.models = Watchers(
            statistics=Statistics() if statistics else None,
            caches=caches, pipeline=pipeline, callstack=CallStack(),
            fetches=caches is not None and (fetches or caches.split),
            machine=self.machine)
        self.models.listen()  # the accesses of memory, which do not come with a turn
        self.simulator.load(self.program, self.arguments)
        for watch in self._watches.values():
            self._listen(watch)

    def restart(self) -> Stopped:
        """The program from the beginning. What was asked to be watched stays; what
        the models counted is forgotten.

        The world outside is NOT put back with it (user decision 2026-10-21): a
        restart is a fresh run, and a program that asks for a line asks again. It
        was the other way at first - a restart put back what had been read, by the
        same reasoning as a step back - and it read as the program silently not
        asking, which is no use to anybody watching. A step back is unchanged:
        stepping back and forward again must give the same thing twice.
        """
        for end in self._ends.values():
            end()
        self._ends.clear()
        self._touched.clear()
        self._pending.clear()
        self._watches = {number: replace(watch, hits=0)
                         for number, watch in self._watches.items()}
        self.ended = False
        self._build()
        return Stopped(NOTHING, self.where())

    # --------------------------------------------------------------- movement

    def step(self, count: int = 1) -> Stopped:
        """One instruction at a time, `count` of them."""
        if self.ended:
            return Stopped(ENDED, self.where())
        done = 0
        for _ in range(max(count, 1)):
            turn = self.simulator.step()
            if isinstance(turn, Stop):
                return self._ended(turn, done)
            self._saw(turn)
            done += turn.retired
            if self._touched:
                return self._answer(WATCHPOINT, done)
            if self.machine.x.pc in self.addresses and done < count:
                return self._answer(BREAKPOINT, done)
        return self._answer(STEPPED, done)

    def back(self, count: int = 1) -> Stopped:
        """A step back, `count` of them; the answer says how many it managed."""
        done = 0
        for _ in range(max(count, 1)):
            if not self.simulator.back_step():
                break
            done += 1
        if done:
            self.ended = False  # a step back reaches over the end of a run
        return self._answer(STEPPED if done else NOTHING, done)

    def over(self, count: int = 1) -> Stopped:
        """Like `step`, but a call is passed over - which is a guess (D21)."""
        if self.ended:
            return Stopped(ENDED, self.where())
        answer, done = self._answer(STEPPED, 0), 0
        for _ in range(max(count, 1)):
            answer = self._over_one()
            done += answer.steps
            if answer.reason != STEPPED:
                return replace(answer, steps=done)
        return replace(answer, steps=done)

    def _over_one(self) -> Stopped:
        turn = self._coming()
        if turn is None or not self._calls(turn):
            return self.step()
        return self._carry_on(until=turn.pc + WORD, depth=self.calls.depth)

    def finish(self) -> Stopped:
        """Out of the call the run is inside - a guess (D21)."""
        if self.ended:
            return Stopped(ENDED, self.where())
        frames = self.calls.frames
        if not frames:
            return self._answer(NOTHING, 0)
        return self._carry_on(until=frames[-1].comes_back_to, depth=len(frames) - 1)

    def carry_on(self) -> Stopped:
        """On to a breakpoint, a watchpoint or the end of the run."""
        return self._carry_on()

    def until(self, address: int) -> Stopped:
        """On to an address, exactly - no guess in this one."""
        return self._carry_on(until=address)

    def _carry_on(self, until: int | None = None, depth: int | None = None) -> Stopped:
        """The loop of a session: run until something it cares about happens."""
        if self.ended:
            return Stopped(ENDED, self.where())
        before = self.simulator.count
        places = self.addresses | ({until} if until is not None else set())
        while True:
            stop = self.simulator.run(max_steps=self.limit,
                                      breakpoints=frozenset(places), watch=self._saw)
            done = self.simulator.count - before
            if self._touched:
                return self._answer(WATCHPOINT, done)
            if stop.reason is not StopReason.BREAKPOINT:
                return self._ended(stop, done)
            if stop.address != until or depth is None or self.calls.depth <= depth:
                if stop.address == until and until not in self.addresses:
                    return self._answer(STEPPED, done)
                return self._answer(BREAKPOINT, done)
            # the same place at a deeper call: a recursion, so on we go

    # ------------------------------------------------------------ the answers

    def _answer(self, reason: str, steps: int) -> Stopped:
        touched = tuple(self._touched)
        self._touched.clear()
        at = self.machine.x.pc
        return Stopped(reason, self.where(), steps, touched=touched,
                       breakpoint=self._break_at(at) if reason == BREAKPOINT else None)

    def _ended(self, stop: Stop, steps: int) -> Stopped:
        reason = REASONS.get(stop.reason, PAUSED)
        # A run that has exited, fallen off the end of its text or trapped with
        # nowhere to go is over; one that waits, was paused or met its limit is not.
        self.ended = reason in (EXITED, CLIFF, TRAPPED)
        touched = tuple(self._touched)
        self._touched.clear()
        return Stopped(reason, self.place_of(stop.address), steps, stop.message,
                       stop.code, touched,
                       self._break_at(stop.address) if reason == BREAKPOINT else None)

    def _saw(self, turn: Stepped) -> None:
        """Every turn of the loop: the models hear of it, and so does whatever was
        touched while it ran."""
        self.models.saw(turn)
        if self.watch is not None:
            self.watch(turn)
        for number, access in self._pending:
            self._touched.append(Touched(
                number, "read" if access.kind is Access.READ else "write",
                access.address, access.size, access.value, turn.pc))
            watch = self._watches[number]
            self._watches[number] = replace(watch, hits=watch.hits + 1)
        self._pending.clear()
        if self._touched:
            self.simulator.pause()

    def _coming(self) -> Stepped | None:
        """What the machine is about to carry out, without carrying it out."""
        try:
            fetched = self.machine.fetch()
        except Exception:  # a place it cannot even read
            return None
        if fetched is None or fetched.instr is None:
            return None
        return Stepped(fetched.address, fetched.word, fetched.instr, fetched.address)

    def _calls(self, turn: Stepped) -> bool:
        """Whether the instruction is what the convention calls a call."""
        return (kind(turn.instr.instr) is Kind.JUMP
                and turn.instr.operands.get("rd") == 1)

    # -------------------------------------------------------------- the places

    @property
    def addresses(self) -> set[int]:
        return set(self._breaks.values())

    @property
    def calls(self) -> CallStack:
        return self.models.callstack

    def _break_at(self, address: int) -> int | None:
        for number, place in self._breaks.items():
            if place == address:
                return number
        return None

    def add_break(self, address: int) -> Breakpoint:
        number = self._take_a_number()
        self._breaks[number] = address
        return Breakpoint(number, self.place_of(address))

    def remove_break(self, which: int | None = None) -> list[Breakpoint]:
        """A breakpoint by its number, or every one of them."""
        gone = []
        for number in sorted(self._breaks) if which is None else [which]:
            if number not in self._breaks:
                raise ValueError(f"there is no breakpoint {number}")
            gone.append(Breakpoint(number, self.place_of(self._breaks.pop(number))))
        return gone

    def breaks(self) -> list[Breakpoint]:
        return [Breakpoint(number, self.place_of(address))
                for number, address in sorted(self._breaks.items())]

    def add_watch(self, low: int, high: int, kind: str = "both") -> Watchpoint:
        if kind not in ("read", "write", "both"):
            raise ValueError(f'"{kind}": a thing is watched for read, write or both')
        if high < low:
            raise ValueError("the first address of a range is the lower one")
        watch = Watchpoint(self._take_a_number(), low, high, kind)
        self._watches[watch.id] = watch
        self._listen(watch)
        return watch

    def remove_watch(self, which: int | None = None) -> list[Watchpoint]:
        gone = []
        for number in sorted(self._watches) if which is None else [which]:
            if number not in self._watches:
                raise ValueError(f"there is nothing watched under {number}")
            gone.append(self._watches.pop(number))
            self._ends.pop(number)()
        return gone

    def watches(self) -> list[Watchpoint]:
        return [self._watches[number] for number in sorted(self._watches)]

    def _listen(self, watch: Watchpoint) -> None:
        """Watch a range of memory for a session."""
        kinds = ((Access.READ,) if watch.kind == "read"
                 else (Access.WRITE,) if watch.kind == "write"
                 else (Access.READ, Access.WRITE))
        ends = []
        for which in kinds:
            ends.append(self.machine.memory.subscribe(
                which, lambda access, number=watch.id: self._pending.append((number, access)),
                watch.low, watch.high))

        def end() -> None:
            for one in ends:
                one()

        self._ends[watch.id] = end

    def _take_a_number(self) -> int:
        number = self._next_id
        self._next_id += 1
        return number

    # --------------------------------------------------------------- the views

    def place_of(self, address: int) -> Place:
        """Everything the program says about an address."""
        entry = self._places.get(address)
        word = entry.word if entry else self.machine.memory.peek(address, WORD)
        basic = entry.basic if entry else (disasm.text(word, self.options.xlen) or "")
        loc = entry.loc if entry else None
        return Place(address, word, basic, self._names.get(address, ""),
                     loc.file if loc else "", loc.line if loc else 0,
                     entry.source if entry else "")

    def where(self) -> Place:
        """Where the machine stands."""
        return self.place_of(self.machine.x.pc)

    def listing(self, address: int | None = None, count: int = 10) -> list[Row]:
        """The text segment around a place: where the machine stands, or where it
        was asked about. A row is marked only where the machine itself stands."""
        at = self.machine.x.pc
        centre = at if address is None else address
        first = max(centre - WORD * (count // 3), self.options.config.text_base)
        rows = []
        for index in range(count):
            place = first + WORD * index
            if place not in self._places and place != at:
                continue
            rows.append(Row(self.place_of(place), place == at, self._break_at(place)))
        return rows

    def source(self, count: int = 5) -> list[SourceLine]:
        """The lines of the program around the place the machine stands at."""
        here = self.where()
        if not here.file:
            return []
        lines = [line for line in self._lines() if line.file == here.file]
        middle = next((index for index, line in enumerate(lines)
                       if line.line == here.line), 0)
        first = max(middle - count // 2, 0)
        return [replace(line, at=line.line == here.line)
                for line in lines[first:first + count]]

    def _lines(self) -> list[SourceLine]:
        """Every line of the program that carries an instruction, in order."""
        seen = {}
        for entry in self.program.text:
            if entry.loc is not None:
                seen[(entry.loc.file, entry.loc.line)] = entry.source
        return [SourceLine(file, line, text) for (file, line), text in sorted(seen.items())]

    def registers(self, names: tuple[str, ...] = ()) -> list[Value]:
        """The integer registers: all of them, or the ones named."""
        numbers = (range(32) if not names
                   else [self._register_number(name) for name in names])
        return [Value(X_NAMES[number], number, self.machine.x.read(number),
                      self.options.xlen) for number in numbers]

    def floats(self, names: tuple[str, ...] = ()) -> list[Value]:
        """The floating point registers, with what the bits mean read both ways."""
        numbers = (range(32) if not names
                   else [self._float_number(name) for name in names])
        found = []
        for number in numbers:
            raw = self.machine.f.raw(number)
            about = to_text(raw, BINARY64)
            if raw >> 32 == 0xFFFFFFFF:  # a single lies boxed in a register
                about = f"{to_text(raw & 0xFFFFFFFF, BINARY32)} (single)"
            found.append(Value(F_NAMES[number], number, raw, 64, about, "f"))
        return found

    def csr(self, names: tuple[str, ...] = ()) -> list[Value]:
        """The control and status registers, with their fields spelled out."""
        wanted = names or tuple(CSRS)
        found = []
        for name in wanted:
            if name not in CSRS:
                raise ValueError(f'"{name}": no control register of that name')
            value = self.machine.csr.read(CSRS[name])
            found.append(Value(name, CSRS[name], value, self.options.xlen,
                               _fields(name, value), "csr"))
        return found

    def memory(self, low: int, high: int) -> list[Words]:
        """Words of memory, four to a row."""
        if high < low:
            raise ValueError("the first address of a range is the lower one")
        first = low - low % WORD
        places = list(range(first, high + 1, WORD))
        return [Words(places[start], tuple(self.machine.memory.peek(place, WORD)
                                           for place in places[start:start + ROWS]))
                for start in range(0, len(places), ROWS)]

    def data(self, low: int | None = None, high: int | None = None) -> list[Item]:
        """The data segment as the program laid it out, with what stands there now."""
        found = []
        for item in self.program.data_layout:
            if low is not None and item.address < low:
                continue
            if high is not None and item.address > high:
                continue
            values = tuple(self.machine.memory.peek(item.address + offset, min(WORD, item.size))
                           for offset in range(0, item.size, WORD))
            text = ""
            if item.directive in (".ascii", ".asciz", ".string"):
                raw = self.machine.memory.read_bytes(item.address, item.size)
                text = raw.rstrip(b"\0").decode("utf-8", "replace")
            found.append(Item(item.address, item.directive, item.size, values, text))
        return found

    def stack(self, count: int = 8) -> list[StackWord]:
        """Words from where the stack pointer stands, up towards its base."""
        sp = self.machine.x.read(SP)
        corners = {frame.sp: index for index, frame in enumerate(self.calls.frames)
                   if frame.sp is not None}
        return [StackWord(sp + WORD * index,
                          self.machine.memory.peek(sp + WORD * index, WORD),
                          corners.get(sp + WORD * index))
                for index in range(max(count, 0))]

    def symbols(self, pattern: str = "") -> list[Symbol]:
        return [Symbol(name, address, name in self.program.globals)
                for name, address in sorted(self.program.symbols.items())
                if pattern in name]

    def frames(self) -> list[FrameSeen]:
        """The calls the run is inside - a guess from the convention (D21)."""
        return [FrameSeen(index + 1, self.place_of(frame.called),
                          self.place_of(frame.called_from), frame.sp)
                for index, frame in enumerate(self.calls.frames)]

    def count(self) -> Counted:
        journal = self.machine.history
        return Counted(self.simulator.count,
                       self.models.statistics.turns if self.models.statistics else 0,
                       len(journal) if journal is not None else 0)

    # ------------------------------------------------- the things around the machine

    def devices(self) -> list[DeviceSeen]:
        """What is attached, and what each one holds."""
        if self.bus is None:
            return []
        return [DeviceSeen(part.name, getattr(part, "offset", None),
                           getattr(part, "size", None), part.state(),
                           part.looks() if hasattr(part, "looks") else {})
                for part in self.bus.parts]

    def device(self, name: str) -> DeviceSeen:
        for seen in self.devices():
            if seen.name == name:
                return seen
        raise ValueError(f'"{name}": no device of that name is attached')

    def cache_lines(self) -> list[CacheLine]:
        """The blocks the caches hold."""
        if self.models.caches is None:
            return []
        found = []
        for side, cache in self.models.caches.each().items():
            bytes_of = cache.settings.block_bytes
            for index, lines in sorted(cache.lines.items()):
                for place, line in enumerate(lines):
                    block = line.tag * cache.settings.sets + index
                    low = block * bytes_of
                    found.append(CacheLine(side, index, place, line.tag, low,
                                           low + bytes_of - 1, line.dirty))
        return found

    def caches(self) -> list[CacheSeen]:
        """The caches of the run, as they were built and as they have fared."""
        caches = self.models.caches
        if caches is None:
            return []
        return [CacheSeen(side, self.models.fetches if side != "data" else False,
                          _settings(cache.settings), cache.accesses, cache.hits,
                          cache.misses, cache.hit_rate, cache.writebacks,
                          cache.through)
                for side, cache in caches.each().items()]

    def pipeline(self) -> PipelineSeen | None:
        """What the model of the time counted, where a run was watched by one."""
        model = self.models.pipeline
        if model is None:
            return None
        return PipelineSeen(_settings(model.settings), model.cycles,
                            model.instructions, model.cpi, model.lost,
                            tuple(Setting(cause, many)
                                  for cause, many in sorted(model.stalls.items())),
                            model.branches, model.mispredictions)

    def diagram(self) -> list[StageSeen]:
        """The diagram the model kept, as far back as it was told to keep it."""
        model = self.models.pipeline
        if model is None:
            return []
        return [StageSeen(row.pc, row.mnemonic, tuple(row.starts), row.ex_cycles,
                          row.waited) for row in model.diagram]

    def guesser(self) -> GuesserSeen | None:
        model = self.models.pipeline
        if model is None:
            return None
        guesser = model.predictor
        return GuesserSeen(guesser.name,
                           tuple(Setting(name, getattr(guesser, name))
                                 for name in ("entries", "bits")
                                 if hasattr(guesser, name)),
                           guesser.guesses, guesser.right, guesser.wrong,
                           guesser.accuracy)

    def statistics(self) -> StatisticsSeen | None:
        """What the run was made of, where a run was counted at all."""
        counted = self.models.statistics
        if counted is None:
            return None
        return StatisticsSeen(
            counted.turns, counted.instructions, counted.traps, counted.unknown,
            counted.taken, counted.not_taken,
            tuple(Setting(name, many) for name, many in counted.kinds().items()),
            tuple(Setting(name, many) for name, many in counted.categories().items()))

    def guesser_entries(self) -> list[GuesserEntry]:
        """The entries of a table of history, where the pipeline guesses with one."""
        guesser = self.models.pipeline.predictor if self.models.pipeline else None
        table = getattr(guesser, "table", None)
        if table is None:
            return []
        return [GuesserEntry(index, entry.counter, entry.taken, entry.right, entry.wrong)
                for index, entry in enumerate(table)]

    # -------------------------------------------------------------- the changes

    def set_register(self, name: str, value: int) -> Value:
        """Put a value in a register. This is no step of the machine, so a step
        back does not undo it (the rule of the journal)."""
        if name in CSRS:
            self.machine.csr.poke(name, value)
            return self.csr((name,))[0]
        number = self._float_number(name, quiet=True)
        if number is not None:
            self.machine.f.set_raw(number, value)
            return self.floats((name,))[0]
        number = self._register_number(name)
        self.machine.x.write(number, value)
        return self.registers((name,))[0]

    def poke(self, address: int, value: int, size: int = WORD) -> Words:
        """Put a value in memory, by the right of a tool: no step, no undoing."""
        self.machine.memory.poke(address, size, value)
        return Words(address, (self.machine.memory.peek(address, size),))

    # ---------------------------------------------------------------- the names

    def address_of(self, text: str) -> int:
        """A place: a number, the name of something, or `file:line`."""
        text = text.strip()
        if text in self.program.symbols:
            return self.program.symbols[text]
        if ":" in text:
            file, _, line = text.rpartition(":")
            if line.isdigit():
                return self._at_line(file, int(line))
        try:
            return int(text, 0)
        except ValueError:
            raise ValueError(f'"{text}": no such place in the program') from None

    def _at_line(self, file: str, line: int) -> int:
        for entry in self.program.text:
            if entry.loc is not None and entry.loc.line == line and (
                    not file or entry.loc.file.endswith(file)):
                return entry.address
        raise ValueError(f'"{file}:{line}": no instruction of the program is there')

    def _register_number(self, name: str) -> int:
        if name in X_ALIASES:
            return X_ALIASES[name]
        if name in X_NAMES:
            return X_NAMES.index(name)
        if name.startswith("x") and name[1:].isdigit() and int(name[1:]) < 32:
            return int(name[1:])
        raise ValueError(f'"{name}": no register of that name')

    def _float_number(self, name: str, quiet: bool = False) -> int | None:
        if name in F_NAMES:
            return F_NAMES.index(name)
        if name.startswith("f") and name[1:].isdigit() and int(name[1:]) < 32:
            return int(name[1:])
        if quiet:
            return None
        raise ValueError(f'"{name}": no floating point register of that name')


def _settings(settings) -> tuple[Setting, ...]:
    """What a model was built with, in the order its own dataclass declares it."""
    return tuple(Setting(one.name, getattr(settings, one.name))
                 for one in fields(settings))


def _fields(name: str, value: int) -> str:
    """What the bits of a control register mean, where they mean something."""
    if name == "fcsr":
        return f"flags 0x{value & 0x1f:02x}, rounding {value >> 5 & 0x7}"
    if name == "ustatus":
        said = [word for bit, word in ((0x1, "UIE"), (0x10, "UPIE")) if value & bit]
        return " ".join(said) or "nothing set"
    if name in ("uie", "uip"):
        said = [word for bit, word in ((0x1, "software"), (0x10, "timer"),
                                       (0x100, "external")) if value & bit]
        return " ".join(said) or "nothing set"
    return ""
