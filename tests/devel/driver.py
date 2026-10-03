"""The loop of the simulator, written out for the differential tests.

The simulator itself is stage 22. Until then the tests drive the machine the way
it will be driven, in the order of R-SIM-LOOP: take whatever is waiting, fetch the
instruction, carry it out, count it. A trap of an instruction goes into its slot
and is taken before the next one, which is what RARS does too.

A program that asks to exit ends the run, and so does one that runs off its text,
waits for an interrupt that cannot come, or meets an event with nowhere to go.
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


def run(program: AssembledProgram, options: Options = Options(), steps: int = STEPS,
        io: SystemIO | None = None, arguments: Sequence[str] = ()) -> Outcome:
    machine = Machine(options, io=io)
    machine.load(program, arguments)
    outcome = Outcome(machine, "steps")
    for _ in range(steps):
        event = traps.take(machine)
        if event is not None:
            outcome.taken.append(event)
            if not event.handled:  # nowhere to go: the machine stops
                outcome.reason = event.message
                return outcome
        fetched = machine.fetch()
        if fetched is None:  # the program ran off the end of its text
            outcome.reason = "cliff"
            return outcome
        try:
            execute(machine, fetched)
        except Waiting:
            outcome.reason = "waiting"
            return outcome
        except Exited as done:
            outcome.reason, outcome.code = "exit", done.code
            return outcome
        except Trap as trap:
            if not traps.register(machine, trap, fetched.address):
                # a breakpoint: RARS carries on in a run without a debugger, and
                # so does the command line of pyRARS (user decision 2026-10-03)
                outcome.breakpoints += 1
                machine.csr.retire()
                outcome.steps += 1
                continue
            continue  # a faulting instruction does not count as retired
        machine.csr.retire()
        outcome.steps += 1
    return outcome
