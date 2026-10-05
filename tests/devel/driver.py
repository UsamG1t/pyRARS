"""The simulator of `pyrars.core`, driven the way the differential tests want it.

The loop itself lives in `core/simulator.py` since stage 22; this is the thin
adapter the tests of the earlier stages were written against: it runs a program and
says in one word how it ended ("exit", "waiting", "cliff", "steps", "breakpoint")
or, when a trap stopped the machine, what the trap said.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pyrars.core.machine import Machine
from pyrars.core.options import Options
from pyrars.core.simulator import Simulator, Stop, StopReason
from pyrars.core.systemio import SystemIO
from pyrars.isa.program import AssembledProgram

STEPS = 100_000

# What a stop reason is called here; EXCEPTION says the message of the trap instead.
REASONS = {
    StopReason.NORMAL_TERMINATION: "exit",
    StopReason.WAITING: "waiting",
    StopReason.CLIFF_TERMINATION: "cliff",
    StopReason.MAX_STEPS: "steps",
    StopReason.BREAKPOINT: "breakpoint",
    StopReason.PAUSE: "pause",
    StopReason.STOP: "stop",
}


@dataclass
class Outcome:
    """What a run left behind."""

    machine: Machine
    simulator: Simulator
    reason: str  # "exit", "waiting", "cliff", "steps", or the message of a trap
    code: int = 0  # what the program exited with
    steps: int = 0  # instructions carried out
    breakpoints: int = 0  # how often `ebreak` was met
    taken: list = field(default_factory=list)  # what the machine did with events

    @property
    def registers(self) -> dict[int, int]:
        return {number: self.machine.x.read(number) for number in range(1, 32)}

    def words(self, address: int, count: int) -> list[int]:
        return [self.machine.memory.peek(address + 4 * index, 4) for index in range(count)]


def run(program: AssembledProgram, options: Options = Options(), steps: int = STEPS,
        io: SystemIO | None = None, arguments: Sequence[str] = ()) -> Outcome:
    machine = Machine(options, io=io)
    simulator = Simulator(machine)
    simulator.load(program, arguments)
    outcome = Outcome(machine, simulator, "steps")
    for _ in range(steps):
        turn = simulator.step()
        if isinstance(turn, Stop):
            outcome.reason = REASONS.get(turn.reason) or turn.message
            outcome.code = turn.code
            break
        if turn.taken is not None:
            outcome.taken.append(turn.taken)
        if turn.trap is not None and turn.retired:  # `ebreak` is no trap of the machine
            outcome.breakpoints += 1
    outcome.steps = simulator.count
    return outcome
