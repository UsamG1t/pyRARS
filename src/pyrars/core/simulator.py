"""The loop of the machine: one turn of it, and as many turns as a run needs.

A turn is the step of the machine (DEV-52): take whatever event is waiting, fetch
the instruction the program counter points at, carry it out, count it. The order
is the one of RARS (R-SIM-LOOP), because a handler must see the same registers
there as here.

Nothing of a program reaches the caller as an exception (INV-E): a trap of an
instruction goes into its slot and is taken before the next turn, and everything
that ends a run comes back as a `Stop` saying why. The reasons are those of RARS
(R-SIM-REASON) plus `WAITING` for `wfi` with nothing to wait for, where RARS
blocks its thread for ever (DEV-46).

What one turn did comes back as `Stepped`, holding what the loop itself knows: the
address, the word, the instruction, where the machine went next, the event it took
and the cause of a trap. What an instruction READ and WROTE is not there: the
devices need only the count of what was carried out, and the pipeline of
`pyrars.analysis`, which needs the registers of each instruction, brings the
tables of `pyrars.isa` that say so (user decision 2026-10-04).

A step limit counts turns, as RARS counts them, and not instructions carried out:
a turn that only takes a trap is a turn. The count of instructions is `instret`,
which a faulting instruction and the service that ends a program never reach - and
the devices of `pyrars.devices` are told of exactly the instructions that reach it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum, auto

from pyrars.core import traps
from pyrars.core.executor import execute
from pyrars.core.machine import Machine
from pyrars.core.syscalls import Exited
from pyrars.core.traps import Taken, Trap, Waiting
from pyrars.isa.codec import Decoded
from pyrars.isa.program import AssembledProgram


class StopReason(Enum):
    """Why a run ended (R-SIM-REASON)."""

    BREAKPOINT = auto()  # the machine reached an address it was told to stop at
    EXCEPTION = auto()  # a trap with nowhere to go
    MAX_STEPS = auto()  # the limit of turns was reached
    NORMAL_TERMINATION = auto()  # the program asked to stop
    CLIFF_TERMINATION = auto()  # it ran off the end of its text
    WAITING = auto()  # `wfi` with nothing to wait for (DEV-46)
    PAUSE = auto()  # a caller asked to pause
    STOP = auto()  # a caller asked to stop


@dataclass(frozen=True, slots=True)
class Stop:
    """Why a run ended, and what a report of it needs."""

    reason: StopReason
    address: int  # the address the reason is about: the faulting instruction, the
    # breakpoint, the place a program ran off, or where the machine stands
    message: str = ""  # the message of a trap that stopped the machine
    code: int = 0  # what the program exited with


@dataclass(frozen=True, slots=True)
class Stepped:
    """What one turn of the loop did."""

    pc: int  # the address of the instruction of this turn
    word: int
    instr: Decoded | None
    next_pc: int  # where the machine went
    taken: Taken | None = None  # the event the machine took before the instruction
    trap: int | None = None  # the cause, where the instruction could not be carried out
    retired: bool = False  # whether it counted as carried out


class Simulator:
    """One machine, driven turn by turn."""

    def __init__(self, machine: Machine) -> None:
        self.machine = machine
        self.program: AssembledProgram | None = None
        self.count = 0  # instructions carried out
        self.paused = False
        self.stopped = False
        # The devices of `pyrars.devices` hear of every instruction carried out,
        # which is what replaces the text-fetch observation of RARS. The `Bus`
        # protocol of the memory knows only read and write, so a bus that wants to
        # hear says so by having the method; without one the loop pays one
        # comparison (INV-Z).
        self._tick = getattr(machine.memory.bus, "on_retire", None)

    def load(self, program: AssembledProgram, arguments: Sequence[str] = ()) -> None:
        self.machine.load(program, arguments)
        self.program = program
        self.count = 0

    # ------------------------------------------------------------- one turn

    def step(self) -> Stepped | Stop:
        """One turn of the loop: `Stepped` when the machine went on, `Stop` when
        it did not."""
        machine = self.machine
        if machine.history is not None:
            machine.history.begin(machine)

        event = traps.take(machine)
        if event is not None and not event.handled:  # nowhere to go
            return Stop(StopReason.EXCEPTION, event.pc, event.message)

        pc = machine.x.pc
        try:
            fetched = machine.fetch()
        except Trap as trap:  # the program counter itself cannot be read
            return self._trapped(Stepped(pc, 0, None, machine.x.pc, event), trap, pc)
        if fetched is None:  # the program ran off the end of its text
            return Stop(StopReason.CLIFF_TERMINATION, pc)

        turn = Stepped(pc, fetched.word, fetched.instr, pc, event)
        try:
            execute(machine, fetched)
        except Waiting:
            return Stop(StopReason.WAITING, pc)
        except Exited as done:
            return Stop(StopReason.NORMAL_TERMINATION, pc, code=done.code)
        except Trap as trap:
            return self._trapped(turn, trap, pc)
        return self._retired(turn)

    def _trapped(self, turn: Stepped, trap: Trap, pc: int) -> Stepped:
        """An instruction that could not be carried out. Its trap waits in its slot
        and is taken before the next turn; a breakpoint is no trap of the machine,
        and the instruction counts as carried out."""
        turn = Stepped(turn.pc, turn.word, turn.instr, self.machine.x.pc, turn.taken,
                       trap.cause)
        if traps.register(self.machine, trap, pc):
            return turn  # a faulting instruction does not count as retired
        return self._retired(turn)

    def _retired(self, turn: Stepped) -> Stepped:
        self.machine.csr.retire()
        self.count += 1
        if self._tick is not None:
            self._tick(1)
        return Stepped(turn.pc, turn.word, turn.instr, self.machine.x.pc, turn.taken,
                       turn.trap, retired=True)

    # ---------------------------------------------------------------- a run

    def run(self, max_steps: int | None = None, breakpoints: frozenset[int] = frozenset(),
            stop_at_ebreak: bool = False,
            watch: Callable[[Stepped], None] | None = None) -> Stop:
        """Turn after turn, until something ends the run.

        A breakpoint stops the machine BEFORE the instruction at that address, and
        never at the one the run starts on, so that a run carries on from where it
        stopped. `ebreak` stops the machine only when asked: RARS stops at it in its
        window and carries on past it from its command line (verified), and a
        debugger will ask for the first behaviour.

        `watch` is handed every turn that did something, which is how the models of
        `pyrars.analysis` are fed without their touching anything (INV-P); without
        one the loop pays a single comparison (INV-Z).
        """
        self.paused = self.stopped = False
        turns = 0
        standing = True  # the machine stands where a caller let it stand
        while True:
            pc = self.machine.x.pc
            if self.stopped:
                return Stop(StopReason.STOP, pc)
            if self.paused:
                return Stop(StopReason.PAUSE, pc)
            if not standing and pc in breakpoints:
                return Stop(StopReason.BREAKPOINT, pc)
            if max_steps is not None and turns >= max_steps:
                return Stop(StopReason.MAX_STEPS, pc)
            standing = False

            turn = self.step()
            turns += 1
            if isinstance(turn, Stop):
                return turn
            if watch is not None:
                watch(turn)
            if stop_at_ebreak and turn.trap == traps.BREAKPOINT:
                return Stop(StopReason.BREAKPOINT, turn.pc)

    # ------------------------------------------------------- going back, pausing

    def back_step(self) -> bool:
        """Take the last turn back (`core/history.py`); False when there is no
        journal or nothing to take back."""
        if self.machine.history is None:
            return False
        if not self.machine.history.back(self.machine):
            return False
        self.count = self.machine.csr.values["instret"]
        return True

    def pause(self) -> None:
        """Ask a run to stop at the end of the turn it is in; a run may be started
        again. Called from another thread than the one that runs (INV-T)."""
        self.paused = True

    def stop(self) -> None:
        self.stopped = True
