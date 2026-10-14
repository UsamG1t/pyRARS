"""A cache watching the accesses of a run.

A cache divides the address space into blocks of bytes and keeps some of them. A
block is `address // bytes of a block`; the set it may lie in is that number
modulo the number of sets, and what is left is the tag. The size of an access does
not matter: two bytes of one block are one block.

The geometry is given the way hardware is described: how many BYTES a block holds,
how many SETS there are, and how many blocks fit in a set (the ways) - one way is
a direct cache, one set is a fully associative one, and anything between is what
is usually called N-way. How many blocks the cache holds follows from the two
numbers and need not be a power of two: a cache of four sets and three ways holds
twelve, and such caches are built.

The size of a block and the number of sets ARE powers of two, because a cache
splits an address into three fields - the offset in the block, the number of the
set, the tag - and a field is a group of bits. A number of sets that is not a
power of two would need a divider in the path of an address, which is not how
caches are made. Nothing else is limited: the sets are kept in a table and made
when they are first touched, as the pages of our memory are, so a cache of a
million sets costs nothing until a run reaches into it.

Besides the three ways of choosing what to throw out, the model answers the two
questions a real cache has about a write: whether memory hears at once or when the
block is thrown out, and whether a write that misses brings its block in at all.

What is kept: the totals, always exact; a log of the last accesses, bounded by a
number given with the settings, because a run of a thousand million accesses must
not eat the memory; and, if asked for, a point of a time series every so many
accesses, so that whoever draws it can show how the cache warmed up.

The defaults - a block of 16 bytes, eight sets, direct, the lately used thrown out
- are the numbers RARS starts its own tool with (user decision 2026-10-14), so
that a run held against it needs no translating. They are numbers, not a tie:
nothing here knows of RARS.

The model is passive (INV-P): it is handed what a run did - the accesses of memory
from `Memory.subscribe` and the addresses of the instructions from the records of
the loop - and touches nothing.
"""

import random
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

REPLACEMENTS = ("lru", "fifo", "random")


class Use(Enum):
    """What the access was for."""

    FETCH = auto()  # an instruction was read
    READ = auto()
    WRITE = auto()


@dataclass(frozen=True, slots=True)
class Settings:
    """How a cache is built."""

    block_bytes: int = 16  # bytes a block holds; a power of two, for it is a field
    sets: int = 8  # sets of blocks; a power of two, for its number is a field too
    ways: int = 1  # blocks to a set: 1 is direct, and one set is fully associative
    replacement: str = "lru"
    seed: int | None = None  # for the replacement by chance, so a run repeats
    write_back: bool = True  # a block written to goes to memory when it is thrown out
    write_allocate: bool = True  # a write that misses brings its block in
    log: int = 10_000  # accesses kept; 0 keeps none, and the totals stay exact
    sample: int = 0  # a point of the time series every so many accesses; 0 means none

    def __post_init__(self) -> None:
        for name, value in (("block_bytes", self.block_bytes), ("sets", self.sets)):
            if value < 1 or value & (value - 1):
                raise ValueError(f"{name} is a power of two, because a cache reads it "
                                 f"off the bits of an address, not {value}")
        if self.ways < 1:
            raise ValueError(f"a set holds at least one block, not {self.ways}")
        if self.replacement not in REPLACEMENTS:
            raise ValueError(f'"{self.replacement}": a block is replaced by '
                             f'{" or ".join(REPLACEMENTS)}')
        if self.log < 0 or self.sample < 0:
            raise ValueError("a log and a sample are counted in accesses, never below nothing")

    @property
    def blocks(self) -> int:
        """How many blocks the cache holds; no power of two is asked of it."""
        return self.sets * self.ways


@dataclass(frozen=True, slots=True)
class Access:
    """One access, as the cache saw it."""

    use: Use
    address: int
    hit: bool
    set: int
    tag: int
    evicted: int | None = None  # the tag that was thrown out, if one was
    wrote_back: bool = False  # and whether it had to be written to memory


@dataclass(frozen=True, slots=True)
class Point:
    """One point of the time series: what happened in that stretch of accesses."""

    accesses: int  # how many there had been by then, in all
    hits: int  # and of this stretch
    misses: int


@dataclass(slots=True)
class Line:
    """One block held in the cache."""

    tag: int
    dirty: bool = False


class Cache:
    """One cache."""

    def __init__(self, settings: Settings = Settings()) -> None:
        self.settings = settings
        self.random = random.Random(settings.seed)
        # The sets are made when they are first touched, as the pages of our memory
        # are: a cache of a million sets costs nothing until a run reaches into it.
        self.lines: dict[int, list[Line]] = {}
        self.accesses = 0
        self.hits = 0
        self.misses = 0
        self.writebacks = 0  # blocks written to memory because they were thrown out
        self.through = 0  # writes that went to memory at once
        self.log: deque[Access] = deque(maxlen=settings.log)
        self.series: list[Point] = []
        self._sampled = (0, 0)  # hits and misses when the last point was taken

    # ------------------------------------------------------- what a run does

    def fetch(self, address: int) -> Access:
        return self.access(Use.FETCH, address)

    def read(self, address: int) -> Access:
        return self.access(Use.READ, address)

    def write(self, address: int) -> Access:
        return self.access(Use.WRITE, address)

    def access(self, use: Use, address: int) -> Access:
        """One access of a run, hit or miss."""
        settings = self.settings
        block = address // settings.block_bytes
        index = block % settings.sets
        tag = block // settings.sets
        lines = self.lines.setdefault(index, [])

        self.accesses += 1
        found = next((line for line in lines if line.tag == tag), None)
        if found is not None:
            self.hits += 1
            seen = Access(use, address, True, index, tag)
            self._kept(found, lines, use)
        else:
            self.misses += 1
            seen = self._missed(use, address, index, tag, lines)
        self.log.append(seen)
        self._sample()
        return seen

    def reset(self) -> None:
        """Empty, as a cache is when a run begins."""
        self.lines.clear()
        self.accesses = self.hits = self.misses = self.writebacks = self.through = 0
        self.log.clear()
        self.series.clear()
        self._sampled = (0, 0)

    @property
    def hit_rate(self) -> float:
        """The share of the accesses that were hits; nothing of nothing is zero."""
        return self.hits / self.accesses if self.accesses else 0.0

    # ---------------------------------------------------------------- the parts

    def _kept(self, line: Line, lines: list[Line], use: Use) -> None:
        """A block that was there already."""
        if self.settings.replacement == "lru":
            lines.remove(line)  # the most lately used goes last
            lines.append(line)
        if use is Use.WRITE:
            self._wrote(line)

    def _missed(self, use: Use, address: int, index: int, tag: int,
                lines: list[Line]) -> Access:
        """A block that was not there."""
        if use is Use.WRITE and not self.settings.write_allocate:
            self.through += 1  # it goes to memory and the cache stays as it was
            return Access(use, address, False, index, tag)
        evicted, wrote_back = None, False
        if len(lines) == self.settings.ways:
            thrown = self._thrown(lines)
            lines.remove(thrown)
            evicted = thrown.tag
            if thrown.dirty:
                self.writebacks += 1
                wrote_back = True
        line = Line(tag)
        lines.append(line)
        if use is Use.WRITE:
            self._wrote(line)
        return Access(use, address, False, index, tag, evicted, wrote_back)

    def _wrote(self, line: Line) -> None:
        """A block was written to: either it is marked, or memory hears at once."""
        if self.settings.write_back:
            line.dirty = True
        else:
            self.through += 1

    def _thrown(self, lines: list[Line]) -> Line:
        """Which block makes room for the new one."""
        if self.settings.replacement == "random":
            return self.random.choice(lines)
        return lines[0]  # LRU keeps the lately used last; FIFO the newest last

    def _sample(self) -> None:
        if not self.settings.sample or self.accesses % self.settings.sample:
            return
        hits, misses = self._sampled
        self.series.append(Point(self.accesses, self.hits - hits, self.misses - misses))
        self._sampled = (self.hits, self.misses)


class Caches:
    """What a run is watched with: one cache for everything, as RARS has it, or one
    for the instructions beside one for the data.

    Whoever drives the run decides what reaches it: the accesses of memory always,
    and the addresses of the instructions only where a cache of instructions is
    wanted - RARS never shows its cache a fetch.
    """

    def __init__(self, data: Settings = Settings(),
                 instructions: Settings | None = None) -> None:
        self.data = Cache(data)
        self.instructions = Cache(instructions) if instructions is not None else None

    @property
    def split(self) -> bool:
        return self.instructions is not None

    def fetch(self, address: int) -> Access:
        return (self.instructions or self.data).fetch(address)

    def read(self, address: int) -> Access:
        return self.data.read(address)

    def write(self, address: int) -> Access:
        return self.data.write(address)

    def reset(self) -> None:
        self.data.reset()
        if self.instructions is not None:
            self.instructions.reset()

    def each(self) -> dict[str, Cache]:
        """The caches by name, for whoever shows them."""
        if self.instructions is None:
            return {"cache": self.data}
        return {"instructions": self.instructions, "data": self.data}
