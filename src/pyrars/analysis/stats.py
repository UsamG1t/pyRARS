"""How much of what a run was made of.

A turn of the loop is handed over as it happens and counted: how many instructions
were carried out, of what kinds, how many branches went and how many did not, how
many instructions could not be carried out at all. Nothing is kept of the turns
themselves, so counting a run of a thousand million instructions costs as much as
counting ten.

The kinds are those of `isa/classes.py`, and `categories()` gives the five RARS
counts by, so a run can be held against its tool of statistics.
"""

from collections import Counter
from dataclasses import dataclass, field

from pyrars.core.simulator import Stepped
from pyrars.isa.classes import CATEGORIES, Kind, kind


@dataclass
class Statistics:
    """What a run was made of."""

    turns: int = 0  # turns of the loop, those that only took a waiting event included
    instructions: int = 0  # instructions carried out, which is what `instret` counts
    traps: int = 0  # instructions that could not be carried out
    unknown: int = 0  # words that encode no instruction of this width
    taken: int = 0  # branches that went
    not_taken: int = 0  # branches that did not
    by_kind: Counter[Kind] = field(default_factory=Counter)

    def saw(self, turn: Stepped) -> None:
        """One turn of the loop of the simulator."""
        self.turns += 1
        if turn.trap is not None:
            self.traps += 1
        if turn.instr is None:
            self.unknown += 1
            return
        if not turn.retired:
            return  # an instruction that faulted was not carried out
        self.instructions += 1
        which = kind(turn.instr.instr)
        self.by_kind[which] += 1
        if which is Kind.BRANCH:
            if turn.next_pc == turn.pc + 4:
                self.not_taken += 1
            else:
                self.taken += 1

    def reset(self) -> None:
        """Forget the run counted so far."""
        self.turns = self.instructions = self.traps = self.unknown = 0
        self.taken = self.not_taken = 0
        self.by_kind.clear()

    def categories(self) -> dict[str, int]:
        """The five kinds RARS counts by, in its own order."""
        counted = dict.fromkeys(("ALU", "Jump", "Branch", "Memory", "Other"), 0)
        for which, many in self.by_kind.items():
            counted[CATEGORIES[which]] += many
        return counted

    def kinds(self) -> dict[str, int]:
        """What was carried out, by kind, the kinds nobody met left out."""
        return {which.name.lower(): self.by_kind[which] for which in Kind
                if self.by_kind[which]}
