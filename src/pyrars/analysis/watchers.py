"""The models a run is watched with, fed as the run goes.

Whoever drives a run - the command line, a session of debugging - builds the
models it was asked for and hands every turn of the loop to this holder, which
passes it on to each of them. The holder itself knows nothing of text: what the
models have to say is rendered by whoever asked for them.

The accesses of memory do not come with a turn, because they do not come from the
loop: a cache hears them through a subscription of the memory, which `listen` sets
up. What does come with a turn is the address of every instruction, for a cache of
instructions wants it and nothing else has it.

Passive throughout (INV-P): nothing here touches the run it watches.
"""

from dataclasses import dataclass

from pyrars.analysis.cache import Caches
from pyrars.analysis.callstack import CallStack
from pyrars.analysis.pipeline import Pipeline
from pyrars.analysis.stats import Statistics
from pyrars.core.memory import Access
from pyrars.core.simulator import Stepped

SP = 2  # the register the convention keeps a stack pointer in


@dataclass
class Watchers:
    """The models of one run."""

    statistics: Statistics | None = None
    caches: Caches | None = None
    pipeline: Pipeline | None = None
    callstack: CallStack | None = None
    fetches: bool = False  # whether the addresses of instructions reach a cache
    machine: object | None = None  # for the stack pointer a stack of calls wants

    def __bool__(self) -> bool:
        return any((self.statistics, self.caches, self.pipeline, self.callstack))

    def saw(self, turn: Stepped) -> None:
        """One turn of the loop, handed to every model that wants it."""
        if self.statistics is not None:
            self.statistics.saw(turn)
        if self.pipeline is not None:
            self.pipeline.saw(turn)
        if self.callstack is not None:
            sp = self.machine.x.read(SP) if self.machine is not None else None
            self.callstack.saw(turn, sp=sp)
        if self.fetches and self.caches is not None:
            self.caches.fetch(turn.pc)

    def listen(self):
        """Hand the caches the accesses of memory, and answer with how to stop.

        They watch the data segment only. The area of the devices is never
        watched: the registers of a device are not the kind of thing a cache may
        keep. Where no cache was asked for, there is nothing to listen for.
        """
        if self.caches is None or self.machine is None:
            return lambda: None
        config = self.machine.options.config
        low, high = config.data_segment_base, config.data_segment_limit
        caches = self.caches
        ends = [
            self.machine.memory.subscribe(
                Access.READ, lambda access: caches.read(access.address), low, high),
            self.machine.memory.subscribe(
                Access.WRITE, lambda access: caches.write(access.address), low, high),
        ]

        def end() -> None:
            for one in ends:
                one()

        return end

    def reset(self) -> None:
        """Forget everything of the run watched so far."""
        for model in (self.statistics, self.caches, self.pipeline, self.callstack):
            if model is not None and hasattr(model, "reset"):
                model.reset()
