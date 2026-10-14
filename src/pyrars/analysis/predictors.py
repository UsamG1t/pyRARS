"""How a machine guesses where a branch will go.

A pipeline has to fetch something behind a branch before it knows where the branch
leads, so it guesses; a wrong guess costs the cycles of what was fetched in vain.
Two kinds of guesser live here.

The simple one always says the same thing - a branch is never taken, or always is.
"Never taken" is what a machine with no table does, and it is right as often as a
program runs straight on.

The other keeps a TABLE: a counter for every entry, and the entry of a branch is
`(address >> 2) % entries`, for the two low bits of the address of an instruction
are always zero. A counter of `bits` bits says what to expect - taken while it is
in its upper half - and every outcome moves it one step towards what happened, as
far as it will go. One bit therefore means "expect what happened last time"; two
mean a wrong guess has to happen twice in a row before the expectation changes,
which is what keeps a loop from being mispredicted twice for every time it ends.

This is the counter of the textbooks and of real machines. RARS keeps a history of
the last outcomes instead and turns its expectation round only when EVERY one of
them disagrees with it (DEV-61); with one bit the two rules are the same thing,
and they part company from two bits up.

Everything here is passive (INV-P): a guesser is told what a branch did, and what
it counts is its own.
"""

from dataclasses import dataclass


class Static:
    """A guesser that says the same thing about every branch."""

    def __init__(self, taken: bool = False) -> None:
        self.taken = taken
        self.guesses = 0
        self.right = 0

    @property
    def name(self) -> str:
        return "always taken" if self.taken else "never taken"

    @property
    def wrong(self) -> int:
        return self.guesses - self.right

    @property
    def accuracy(self) -> float:
        return self.right / self.guesses if self.guesses else 0.0

    def guess(self, pc: int) -> bool:
        self.guesses += 1
        return self.taken

    def told(self, pc: int, went: bool) -> None:
        """What the branch did; there is nothing to learn from it."""
        if went == self.taken:
            self.right += 1

    def reset(self) -> None:
        self.guesses = self.right = 0


@dataclass(slots=True)
class Entry:
    """One entry of the table: what it expects, and how it has done."""

    counter: int
    half: int  # where the upper half of the counter begins
    right: int = 0
    wrong: int = 0

    @property
    def taken(self) -> bool:
        """What the counter says: taken while it is in its upper half."""
        return self.counter >= self.half


class History:
    """A table of counters, one for every entry a branch falls into."""

    def __init__(self, entries: int = 16, bits: int = 1, taken: bool = False) -> None:
        if entries < 1:
            raise ValueError(f"a table holds at least one entry, not {entries}")
        if bits < 1:
            raise ValueError(f"a counter holds at least one bit, not {bits}")
        self.entries = entries
        self.bits = bits
        self.highest = (1 << bits) - 1
        self.half = 1 << (bits - 1)
        self.start = self.highest if taken else 0
        self.table = [Entry(self.start, self.half) for _ in range(entries)]
        self.guesses = 0
        self.right = 0

    @property
    def name(self) -> str:
        return f"a table of {self.entries} entries of {self.bits} bits"

    @property
    def wrong(self) -> int:
        return self.guesses - self.right

    @property
    def accuracy(self) -> float:
        return self.right / self.guesses if self.guesses else 0.0

    def at(self, pc: int) -> int:
        """Which entry a branch falls into. The two low bits of the address of an
        instruction are always zero, so they say nothing and are dropped."""
        return (pc >> 2) % self.entries

    def guess(self, pc: int) -> bool:
        self.guesses += 1
        return self.table[self.at(pc)].taken

    def told(self, pc: int, went: bool) -> None:
        """What the branch did: the counter takes one step towards it."""
        entry = self.table[self.at(pc)]
        if entry.taken == went:
            self.right += 1
            entry.right += 1
        else:
            entry.wrong += 1
        entry.counter = (min(entry.counter + 1, self.highest) if went
                         else max(entry.counter - 1, 0))

    def reset(self) -> None:
        self.table = [Entry(self.start, self.half) for _ in range(self.entries)]
        self.guesses = self.right = 0
