"""The journal of what a step changed, so that a step can be taken back.

A step back is not a step forward in reverse: nothing is worked out again. Every
place a step changed is written down together with the value it held BEFORE, and
taking the step back puts those values where they were, in reverse order of the
writing. The places that change on every step - the program counter, the counters
of `cycle` and `instret`, the top of the heap, the three slots of waiting events -
are not written down one by one: the step keeps what they were when it began.

What a step back restores (user decision 2026-10-04, variant b):
  - the integer registers, the floating point registers and the program counter;
  - the control and status registers, the counters among them, exactly as RARS
    does (it writes them "through the back door" and journals that too);
  - the memory, down to the mark that says a word of the text segment holds an
    instruction, which matters to a program that writes its own text: without it
    an undone write would leave a word of zeroes behind that reads as an illegal
    instruction instead of the end of the text;
  - the top of the heap that `sbrk` hands out and the state of the random streams,
    which RARS does not restore (DEV-51).

What a step back cannot restore by itself is the world outside the machine. Under
a debugger (`Options.debug`) the world is asked to go back with it: what was read
is handed out again, the files stand where they stood, and text the world owns is
taken back (`SystemIO.mark` and `SystemIO.rewind`). The world keeps its record
either way; the flag only decides whether a step back reads it or the program
reads the world anew (user decision 2026-10-04). Whatever has really left - a line
printed on a terminal, bytes written into a file - stays where it went.

A step is one turn of the loop of the simulator (R-SIM-LOOP): taking a waiting
event and carrying out one instruction belong to the same step, because entering a
handler is part of what that turn did. RARS instead groups the writes of a step by
the instruction that made them, which goes wrong when the program counter leaves
the text segment (DEV-52).

Sources: R-BACKSTEP in `rars-behavior.md`.
"""

from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto


class Kind(Enum):
    """What a written-down change is about."""

    X = auto()  # an integer register: `where` is its number
    F = auto()  # a floating point register: `where` is its number
    CSR = auto()  # a control register: `where` is its name, the value the whole of it
    MEMORY = auto()  # `where` is the address, the value the bytes and the text marks
    RANDOM = auto()  # a random stream: `where` is its index, the value stream and state


@dataclass(frozen=True, slots=True)
class Entry:
    """One place a step changed, and what it held before."""

    kind: Kind
    where: int | str
    value: object


@dataclass(slots=True)
class Step:
    """One step: what it started from, and every place it changed."""

    pc: int
    cycle: int
    instret: int
    heap: int
    pending: tuple[int | None, int | None, tuple[int, int, int, str] | None]
    world: object  # the mark of the world outside, read back only under a debugger
    entries: list[Entry] = field(default_factory=list)


class History:
    """The steps that can be taken back, the newest last.

    The journal holds at most `depth` steps; the oldest is dropped when another
    one begins. A machine built without a depth has no journal at all, and then a
    write records nothing (INV-Z).
    """

    def __init__(self, depth: int = 2000, rewind_world: bool = False) -> None:
        self.depth = depth
        self.rewind_world = rewind_world
        self.steps: deque[Step] = deque(maxlen=depth)
        self.open: Step | None = None  # the step being carried out

    def __len__(self) -> int:
        return len(self.steps)

    def clear(self) -> None:
        self.steps.clear()
        self.open = None

    # ------------------------------------------------------- while a step runs

    def begin(self, machine) -> None:
        """A step starts: keep what changes on every step anyway."""
        pending = machine.pending
        self.open = Step(
            pc=machine.x.pc,
            cycle=machine.csr.values["cycle"],
            instret=machine.csr.values["instret"],
            heap=machine.heap,
            pending=(pending.external, pending.timer, pending.trap),
            world=machine.io.mark(),
        )
        self.steps.append(self.open)

    def close(self) -> None:
        """The step is over. Whatever is written to a place from now on belongs to
        no step and so cannot be taken back - which is what a tool writing into a
        halted machine wants: a step back must not undo what a person asked for.
        """
        self.open = None

    def record(self, kind: Kind, where: int | str, value: object) -> None:
        """A place is about to change: this is what it holds now.

        Outside a step - while a program is loaded, or when a tool writes
        somewhere - nothing is written down: there is no step to take back.
        """
        if self.open is not None:
            self.open.entries.append(Entry(kind, where, value))

    # ------------------------------------------------------------ going back

    def back(self, machine) -> bool:
        """Take the last step back; False when there is nothing to take back.

        The step is taken off the journal and closed before anything is put
        back, so what putting it back writes is not written down again: there
        is no open step to write it into.
        """
        if not self.steps:
            return False
        step = self.steps.pop()
        self.open = None
        for entry in reversed(step.entries):
            self._put_back(machine, entry)
        machine.x.pc = step.pc
        machine.csr.poke("cycle", step.cycle)
        machine.csr.poke("instret", step.instret)
        machine.heap = step.heap
        (machine.pending.external, machine.pending.timer,
         machine.pending.trap) = step.pending
        if self.rewind_world:
            machine.io.rewind(step.world)
        return True

    def _put_back(self, machine, entry: Entry) -> None:
        match entry.kind:
            case Kind.X:
                machine.x.write(entry.where, entry.value)
            case Kind.F:
                machine.f.set_raw(entry.where, entry.value)
            case Kind.CSR:
                machine.csr.poke(entry.where, entry.value)
            case Kind.MEMORY:
                data, unfilled = entry.value
                machine.memory.restore(entry.where, data, unfilled)
            case Kind.RANDOM:
                stream, state = entry.value
                machine.generators[entry.where] = stream
                stream.setstate(state)
