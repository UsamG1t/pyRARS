"""The loop of the simulator, written out for the differential tests.

The simulator itself is stage 22. Until then the tests drive the machine the way
it will be driven, in the order of R-SIM-LOOP: take whatever is waiting, fetch the
instruction, carry it out, count it. A trap of an instruction goes into its slot
and is taken before the next one, which is what RARS does too.

A program that asks to exit ends the run, and so does one that runs off its text,
waits for an interrupt that cannot come, or meets an event with nowhere to go.

Every turn opens a step of the journal (`core/history.py`), so that a test can
take steps back afterwards; a machine built without a depth has no journal and
nothing is written down.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pyrars.core import traps
from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.syscalls import Exited
from pyrars.core.systemio import SystemIO
from pyrars.core.traps import Taken, Trap, Waiting
from pyrars.isa.program import AssembledProgram

STEPS = 100_000


@dataclass
class Outcome:
    """What a run left behind."""

    machine: Machine
    reason: str  # "exit", "waiting", "cliff", "steps", or the message of a trap
    code: int = 0  # what the program exited with
    taken: list[Taken] = field(default_factory=list)  # what the machine did with events
    steps: int = 0
    breakpoints: int = 0  # how often `ebreak` was met

    @property
    def registers(self) -> dict[int, int]:
        return {number: self.machine.x.read(number) for number in range(1, 32)}

    def words(self, address: int, count: int) -> list[int]:
        return [self.machine.memory.peek(address + 4 * index, 4) for index in range(count)]


@dataclass
class Turn:
    """What one turn of the loop did."""

    reason: str | None = None  # why the machine stopped, where it did
    code: int = 0  # what the program exited with
    event: Taken | None = None  # what the machine did with a waiting event
    retired: bool = False  # whether an instruction was carried out and counted
    breakpoint: bool = False  # whether `ebreak` was met


def step(machine: Machine) -> Turn:
    """One turn of the loop of R-SIM-LOOP: open a step of the journal, take
    whatever is waiting, fetch, carry out, count."""
    if machine.history is not None:
        machine.history.begin(machine)
    event = traps.take(machine)
    if event is not None and not event.handled:  # nowhere to go: the machine stops
        return Turn(reason=event.message, event=event)
    fetched = machine.fetch()
    if fetched is None:  # the program ran off the end of its text
        return Turn(reason="cliff", event=event)
    try:
        execute(machine, fetched)
    except Waiting:
        return Turn(reason="waiting", event=event)
    except Exited as done:
        return Turn(reason="exit", code=done.code, event=event)
    except Trap as trap:
        if not traps.register(machine, trap, fetched.address):
            # a breakpoint: RARS carries on in a run without a debugger, and so
            # does the command line of pyRARS (user decision 2026-10-03)
            machine.csr.retire()
            return Turn(event=event, retired=True, breakpoint=True)
        return Turn(event=event)  # a faulting instruction does not count as retired
    machine.csr.retire()
    return Turn(event=event, retired=True)


def run(program: AssembledProgram, options: Options = Options(), steps: int = STEPS,
        io: SystemIO | None = None, arguments: Sequence[str] = ()) -> Outcome:
    machine = Machine(options, io=io)
    machine.load(program, arguments)
    outcome = Outcome(machine, "steps")
    for _ in range(steps):
        turn = step(machine)
        if turn.event is not None:
            outcome.taken.append(turn.event)
        outcome.breakpoints += turn.breakpoint
        outcome.steps += turn.retired
        if turn.reason is not None:
            outcome.reason, outcome.code = turn.reason, turn.code
            return outcome
    return outcome
