"""What a run would have cost a machine with a pipeline of five stages.

This is a MODEL of time, not a machine: the run has already happened, and every
instruction of it is known - what it was, which registers it touched, where it
went next. The model only asks how long such a sequence would have taken a machine
that fetches, decodes, computes, reaches memory and writes back, one stage to a
cycle, in order.

    IF  the instruction is read
    ID  it is decoded and its registers are read
    EX  it is computed; a kind of instruction may hold the stage longer
    MEM memory is reached, if it has to be
    WB  the result is written back

A stage holds its instruction until the next stage takes it, so a wait anywhere
backs the earlier stages up, as it does in a real machine. Three things make a
machine wait:

  - a value that is not there yet. With forwarding a result can be used as soon as
    it has been computed (the end of EX), and the value of a load as soon as it has
    been read (the end of MEM), so a load used by the instruction right after it
    costs one cycle. Without forwarding a value waits until it has been written
    back.
  - a stage that is still busy: an instruction whose EX takes several cycles holds
    the one behind it in ID.
  - one port to memory, if the machine is said to have one: then an instruction
    reaching memory and the fetch of another cannot happen in the same cycle. Our
    default is two ports, which is what a machine with a cache of its own for the
    instructions has, and what the drawings in the books assume.

A branch is guessed at. The run itself says where the branch went, so the model
knows whether the guess was right; a wrong one throws away what was fetched after
it, and the machine loses the cycles between the fetch and the stage where the
branch is settled - two, since this model settles it in EX. An instruction that
could not be carried out at all empties the pipeline in the same way.

What comes out: the cycles the run would have taken, the instructions carried out,
CPI, and the cycles lost by cause - so that "it waited 300 cycles for values and
80 for wrong guesses" can be said. The diagram of what happened in which cycle is
kept for the first instructions only (a number given with the settings), because a
long run must not eat the memory.

The model is passive (INV-P) and is handed the records of the turns of the loop.
"""

from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum, auto

from pyrars.core.simulator import Stepped
from pyrars.isa.classes import Kind, RegRef, kind, reads, writes

STAGES = ("IF", "ID", "EX", "MEM", "WB")

# What holds a machine up, as the model tells the causes apart.
DATA = "data"  # a value that has not been computed yet
LOAD = "load"  # a value that is still being read from memory
BUSY = "busy"  # a stage that has not finished with the instruction before
PORT = "port"  # memory reached by one instruction while another is fetched
BRANCH = "branch"  # a guess at a branch that was wrong
TRAP = "trap"  # an instruction that could not be carried out

CAUSES = (DATA, LOAD, BUSY, PORT, BRANCH, TRAP)

# Which kinds of instruction reach memory.
MEMORY = (Kind.LOAD, Kind.STORE, Kind.FLOAT_LOAD, Kind.FLOAT_STORE)
LOADS = (Kind.LOAD, Kind.FLOAT_LOAD)


@dataclass(frozen=True, slots=True)
class Settings:
    """How the machine of the model is built."""

    forwarding: bool = True  # a result may be used before it is written back
    one_port: bool = False  # the fetch and the reach into memory share a port
    penalty: int = 2  # cycles thrown away by a wrong guess, settled in EX
    trap_penalty: int = 2  # and by an instruction that could not be carried out
    latency: dict[Kind, int] = field(default_factory=dict)  # EX cycles, 1 where unsaid
    diagram: int = 200  # instructions kept in the diagram; 0 keeps none

    def __post_init__(self) -> None:
        if self.penalty < 0 or self.trap_penalty < 0 or self.diagram < 0:
            raise ValueError("a penalty and a diagram are never below nothing")
        for which, cycles in self.latency.items():
            if cycles < 1:
                raise ValueError(f"{which.name.lower()} takes at least one cycle")

    def cycles_of(self, which: Kind) -> int:
        """How long the EX stage holds an instruction of that kind."""
        return self.latency.get(which, 1)


@dataclass(frozen=True, slots=True)
class Row:
    """Where one instruction was in which cycle, for whoever draws it."""

    pc: int
    mnemonic: str
    starts: tuple[int, int, int, int, int]  # the cycle each of the five stages began
    ex_cycles: int  # how long EX held it
    waited: int  # cycles it waited before it could go on


class Pipeline:
    """The time a run would have taken."""

    def __init__(self, settings: Settings = Settings()) -> None:
        self.settings = settings
        self.instructions = 0
        self.cycles = 0
        self.stalls: Counter[str] = Counter()
        self.diagram: list[Row] = []
        self.mispredictions = 0
        self.branches = 0
        # Where each stage is free, where each register is ready, and from which
        # cycle a fetch may happen again after a flush.
        self._free = dict.fromkeys(STAGES, 0)
        self._ready: dict[RegRef, int] = {}
        self._from_loads: set[RegRef] = set()  # values still coming out of memory
        self._fetch_from = 0
        # The cycles in which memory is busy, where the machine has one port. Only
        # the ones a fetch has not passed yet are kept, so this stays small: the
        # instruction held up by a load is the one fetched three cycles later, not
        # the one behind it.
        self._memory_cycles: deque[int] = deque()

    # ------------------------------------------------------- what a run does

    def saw(self, turn: Stepped) -> None:
        """One turn of the loop of the simulator."""
        if turn.instr is None:
            return  # a word that encodes no instruction times nothing
        which = kind(turn.instr.instr)
        settings = self.settings
        ex_cycles = settings.cycles_of(which)

        fetch = max(self._free["IF"], self._fetch_from)
        if self._busy_at(fetch):  # memory is busy with another instruction
            self.stalls[PORT] += 1
            fetch += 1
        decode = max(fetch + 1, self._free["ID"])

        wanted = self._wanted(turn)
        compute = max(decode + 1, self._free["EX"], wanted)
        self._blamed(decode, compute, wanted, turn)

        memory = max(compute + ex_cycles, self._free["MEM"])
        back = max(memory + 1, self._free["WB"])

        self._free["IF"] = decode
        self._free["ID"] = compute
        self._free["EX"] = memory
        self._free["MEM"] = back
        self._free["WB"] = back + 1
        self.cycles = max(self.cycles, back + 1)
        self.instructions += 1

        self._wrote(turn, which, compute, ex_cycles, memory)
        self._guessed(turn, which, compute)
        if turn.trap is not None:
            self.stalls[TRAP] += settings.trap_penalty
            self._fetch_from = compute + settings.trap_penalty
        if settings.one_port and which in MEMORY:
            self._memory_cycles.append(memory)
        self._drawn(turn, compute, decode, fetch, memory, back, ex_cycles)

    @property
    def cpi(self) -> float:
        """Cycles to an instruction; nothing of nothing is zero."""
        return self.cycles / self.instructions if self.instructions else 0.0

    @property
    def lost(self) -> int:
        """All the cycles a machine without hindrance would not have spent."""
        return sum(self.stalls.values())

    def reset(self) -> None:
        self.instructions = self.cycles = self.mispredictions = self.branches = 0
        self.stalls.clear()
        self.diagram.clear()
        self._free = dict.fromkeys(STAGES, 0)
        self._ready.clear()
        self._from_loads.clear()
        self._fetch_from = 0
        self._memory_cycles.clear()

    # ---------------------------------------------------------------- the parts

    def _busy_at(self, cycle: int) -> bool:
        """Whether memory is reached in that cycle by an instruction already in the
        pipeline, which a machine of one port cannot do while it fetches."""
        while self._memory_cycles and self._memory_cycles[0] < cycle:
            self._memory_cycles.popleft()
        return bool(self._memory_cycles) and self._memory_cycles[0] == cycle

    def _wanted(self, turn: Stepped) -> int:
        """The cycle at which every value this instruction reads is there."""
        return max((self._ready.get(ref, 0) for ref in reads(turn.instr)), default=0)

    def _blamed(self, decode: int, compute: int, wanted: int, turn: Stepped) -> None:
        """Why the instruction could not compute as soon as it was decoded."""
        waited = compute - (decode + 1)
        if waited <= 0:
            return
        if wanted == compute:
            readers = reads(turn.instr)
            from_load = any(ref in self._from_loads for ref in readers)
            self.stalls[LOAD if from_load else DATA] += waited
        else:
            self.stalls[BUSY] += waited

    def _wrote(self, turn: Stepped, which: Kind, compute: int, ex_cycles: int,
               memory: int) -> None:
        """When what this instruction writes can be used by another."""
        if self.settings.forwarding:
            ready = memory + 1 if which in LOADS else compute + ex_cycles
        else:
            ready = memory + 2  # not before it has been written back
        for ref in writes(turn.instr):
            self._ready[ref] = ready
            if which in LOADS:
                self._from_loads.add(ref)
            else:
                self._from_loads.discard(ref)

    def _guessed(self, turn: Stepped, which: Kind, compute: int) -> None:
        """A branch is guessed at; a wrong guess throws away what was fetched."""
        if which is not Kind.BRANCH:
            return
        self.branches += 1
        went = turn.next_pc != turn.pc + 4
        if not self.guess(turn.pc, went):
            self.mispredictions += 1
            self.stalls[BRANCH] += self.settings.penalty
            self._fetch_from = compute + self.settings.penalty

    def guess(self, pc: int, went: bool) -> bool:
        """Whether the guess about this branch was right. This machine never
        expects a branch to be taken."""
        return not went

    def _drawn(self, turn: Stepped, compute: int, decode: int, fetch: int,
               memory: int, back: int, ex_cycles: int) -> None:
        if len(self.diagram) >= self.settings.diagram:
            return
        self.diagram.append(Row(turn.pc, turn.instr.instr.mnemonic,
                                (fetch, decode, compute, memory, back), ex_cycles,
                                compute - (decode + 1)))
