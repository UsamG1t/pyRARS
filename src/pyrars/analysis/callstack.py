"""Which call a run is inside, as far as the convention lets anyone tell.

A RISC-V machine has no notion of a call: `jal` and `jalr` write an address into a
register and go, and a return is a jump to the address in a register. What makes
one a CALL and another a RETURN is the convention programs keep - the address is
left in `ra`, and a return jumps to what `ra` holds - so everything here is a
GUESS about a program's shape, and whoever shows it must say so. A program that
keeps `ra` itself, jumps through another register, or never comes back will be
read wrongly, and the model says where it lost its way instead of pretending:

  - a call is `jal` or `jalr` that writes `ra`;
  - a return is `jalr` that writes nothing, reads `ra` and adds nothing to it -
    which is what `ret` is;
  - the place a call is expected to come back to is the instruction after it, and
    a return that lands anywhere else is counted as a surprise (`confused`);
  - a return with nothing to return from is counted too (`unmatched`), for a run
    may begin inside a call.

The stack keeps the address called, the address it should come back to, where the
stack pointer stood when the call was made, and the instruction that made it. The
stack pointer is not in the record of a turn, so whoever hands the turns over
passes it along; without it a frame simply does not know it.

How deep the model will follow is a number given with it, so that a recursion
without an end cannot eat the memory: deeper calls are counted and not kept.

The model is passive (INV-P): it watches and touches nothing.
"""

from dataclasses import dataclass, field

from pyrars.core.simulator import Stepped
from pyrars.isa.classes import Kind, kind

RA = 1  # the register the convention leaves a return address in
DEPTH = 10_000  # frames kept; deeper calls are counted only


@dataclass(frozen=True, slots=True)
class Frame:
    """One call the run is inside, as far as the convention lets anyone tell."""

    called: int  # where the call went
    comes_back_to: int  # where it should come back to: the instruction after the call
    called_from: int  # the address of the call itself
    sp: int | None  # where the stack pointer stood, if whoever watched knew


@dataclass
class CallStack:
    """The calls a run is inside."""

    depth_kept: int = DEPTH
    frames: list[Frame] = field(default_factory=list)
    calls: int = 0
    returns: int = 0
    deepest: int = 0
    unmatched: int = 0  # returns with nothing to return from
    confused: int = 0  # returns that landed somewhere else than the call expects
    beyond: int = 0  # calls deeper than the model follows

    def __post_init__(self) -> None:
        if self.depth_kept < 1:
            raise ValueError("a stack of calls holds at least one frame")

    @property
    def depth(self) -> int:
        """How many calls the run is inside, as far as the model followed."""
        return len(self.frames)

    def saw(self, turn: Stepped, sp: int | None = None) -> None:
        """One turn of the loop. `sp` is where the stack pointer stood, if known."""
        if turn.instr is None or not turn.retired:
            return  # nothing was carried out, so nothing was called or returned from
        operands = turn.instr.operands
        if kind(turn.instr.instr) is not Kind.JUMP:
            return
        if operands.get("rd") == RA:
            self._called(turn, sp)
        elif self._returning(turn):
            self._returned(turn)

    def reset(self) -> None:
        self.frames.clear()
        self.calls = self.returns = self.deepest = 0
        self.unmatched = self.confused = self.beyond = 0

    # ---------------------------------------------------------------- the parts

    def _returning(self, turn: Stepped) -> bool:
        """Whether this is what the convention calls a return: `ret`."""
        operands = turn.instr.operands
        return (turn.instr.instr.mnemonic == "jalr" and operands.get("rd") == 0
                and operands.get("rs1") == RA and operands.get("imm") == 0)

    def _called(self, turn: Stepped, sp: int | None) -> None:
        self.calls += 1
        if len(self.frames) >= self.depth_kept:
            self.beyond += 1
            return
        self.frames.append(Frame(turn.next_pc, turn.pc + 4, turn.pc, sp))
        self.deepest = max(self.deepest, len(self.frames))

    def _returned(self, turn: Stepped) -> None:
        self.returns += 1
        if not self.frames:
            self.unmatched += 1
            return
        frame = self.frames.pop()
        if turn.next_pc != frame.comes_back_to:
            self.confused += 1
