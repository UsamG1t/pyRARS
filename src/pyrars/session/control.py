"""Driving a run from somewhere that must not wait: one thread owns the machine.

A window cannot sit inside the loop of a program - the loop would hold the window
still, and a program without an end would hold it for ever. So a thread of its own
carries out every movement and answers every question, and whoever owns the main
loop only asks and listens. INV-T: nothing but that thread touches the machine, or
the session around it; what comes back is the data of `session/debug.py`, which is
already made to be looked at and never changed.

Two things do NOT go through the queue, because the thread is busy inside a
movement exactly when they are needed: `pause` and `stop` set a flag that the loop
of the machine reads every turn (`Simulator.pause`, `Simulator.stop`), and
`Waiting.answer` hands the program the line it is waiting for. A flag written in
one thread and read in another is all they are, which is what RARS does as well.

What comes back comes back through ONE callback, given once: `Snapshot` says where
the run is, `Answer` is what a question asked for, `Failed` is a question that
could not be answered. A window wraps that callback in `GLib.idle_add` and so
touches its widgets from its own thread only; a test gives a list to append to.
Nothing here knows of GTK, and nothing here imports it (INV-L2).

A movement is a method of its own, because it takes time and ends in a `Stopped`.
Everything else a session can do - the breakpoints, the watchpoints, every view,
`set` and `poke` - is a QUESTION, asked with `ask` and a function over the session,
so that this module does not have to grow a method for every method of a session.

What comes back is also PACED BY WHOEVER IS TOLD, where they ask for that
(`waits`): the loop says nothing more until it has been told that the last
snapshot was dealt with. A window does work for every snapshot it gets, and a
machine that runs a hundred thousand instructions a second can tell it more than
it can ever answer for.

A run may be SLOWED: `speed` is how many instructions a second it is allowed to
carry out, or nothing at all for as fast as it can (RARS has the same, as a slider
from one a second to unlimited). It is read every turn of the loop, so it may be
changed while the run goes on, and it is the one thing besides the flags above
that another thread may write. While something is being watched - the registers,
the memory - every snapshot of a movement carries the answers to those questions
with it: a run nobody could follow needs no registers thirty times a second, and a
run somebody is following needs all of them, and only the thread of the run may go
and get them.
"""

import queue
import threading
import time
from dataclasses import dataclass

from pyrars.asm.assembler import assemble
from pyrars.core.systemio import ConsoleIO
from pyrars.isa.program import AssembledProgram
from pyrars.session.debug import Place, Session, Stopped
from pyrars.session.project import Project

# How often a snapshot goes out while a program runs. Thirty a second is what a
# screen can show and an eye can follow; the loop pays one comparison a turn.
EVERY = 1 / 30

# How long the thread of the run GIVES UP with every snapshot it sends, so that
# whoever owns a main loop can have the interpreter.
#
# `time.sleep(0)` was here first and does not do it. CPython hands the interpreter
# on when a thread's slice runs out - five milliseconds by default - and whoever
# owns the main loop of a window asks for it back after every call it makes into C,
# so it loses that race again and again. Measured on a program that paints a bitmap
# at full speed: the main loop of the window waited NINE SECONDS for a turn, and
# the window stood still (the architect, 2026-10-25). A thousandth of a second
# given up thirty times a second is three per cent of the run, and the longest the
# window then waits is the gap between two snapshots.
YIELD = 0.001

# Where a run is, as a snapshot says it.
NOTHING = "nothing"  # no program is open
STANDING = "standing"  # a program is open and the machine stands still
RUNNING = "running"
WAITING = "waiting"  # the program has asked for a line and nothing goes on until it has one
ENDED = "ended"  # the run is over: a restart or a step back follows

# The names the controller answers under, where it asks something of its own.
LOAD = "load"
ASKING = "asking"  # the program is waiting for a line of input
DEVICE = "the device"  # something was done TO a device, and this is how it is now
IMAGE = "the image"  # and what a device was holding, for whoever asked for it


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Where a run is, as a window shows it.

    It holds what is wanted at every moment and cheap to take; everything else -
    the registers, the memory, the frames - is a question, because a window shows
    those when it is looking at them and not thirty times a second.
    """

    state: str
    place: Place | None = None
    instructions: int = 0
    turns: int = 0
    back: int = 0  # steps that can still be taken back
    stopped: Stopped | None = None  # what a movement ended on, when one just did


@dataclass(frozen=True, slots=True)
class Answer:
    """What a question asked for."""

    what: str
    value: object


@dataclass(frozen=True, slots=True)
class Failed:
    """A question that could not be answered, in one sentence."""

    what: str
    message: str


class Waiting:
    """The input of a program driven from a window: it asks, and it waits.

    `asked` is called in the thread of the run when the program wants something,
    and `answer` from wherever the answer comes - the main loop of a window, a
    test. `ended` says there is no more input, which the program sees as the end of
    its own input. Everything read is kept by `ConsoleIO` as ever, so a step back
    hands the same line out again without asking anyone.
    """

    def __init__(self, asked=None, answered=None) -> None:
        self.asked = asked  # the program wants a line and nothing has one
        self.answered = answered  # and now it has one
        self.lines: queue.Queue[str] = queue.Queue()
        self.kept = ""  # what was answered and not taken yet
        self.over = False

    def answer(self, text: str) -> None:
        self.lines.put(text if text.endswith("\n") else text + "\n")

    def ended(self) -> None:
        """There is no more input; a program asking for more sees the end of it.

        This is also the only way to WAKE a program that is waiting for a line
        nobody is going to give it, which is what ending a run has to do: the
        thread of the run is standing here and not in the loop of the machine, so
        the flag that stops the loop would never be read.
        """
        self.over = True
        self.lines.put("")

    def again(self) -> None:
        """The input is open once more, for a run that begins again."""
        self.over = False

    def forget(self) -> None:
        """Throw away what was typed and never read.

        A line is typed FOR a run - the one that was open when it was typed. A run
        that begins afresh must ask for its own, or somebody who typed ahead and
        then changed their mind would be feeding a program they never meant to.
        """
        self.again()
        self.kept = ""
        while not self.lines.empty():
            self.lines.get_nowait()

    def readline(self) -> str:
        """One line. An answer may hold several, or none of a line at all, so what
        is left over waits here for the next asking."""
        while "\n" not in self.kept:
            more = self._more()
            if not more:  # the end of the input: what there is, is the line
                line, self.kept = self.kept, ""
                return line
            self.kept += more
        line, _, self.kept = self.kept.partition("\n")
        return line + "\n"

    def read(self, count: int) -> str:
        while len(self.kept) < count:
            more = self._more()
            if not more:
                break
            self.kept += more
        text, self.kept = self.kept[:count], self.kept[count:]
        return text

    def _more(self) -> str:
        """One answer, waited for.

        What was answered is taken FIRST, whatever else has happened: the input
        ending does not throw away what somebody had already typed. Only when
        there is nothing left to take is anybody asked for more - so a line typed
        ahead is read without the program being announced as waiting - and the end
        of the input is what wakes a reader that is waiting for a line nobody is
        going to give it.
        """
        if not self.lines.empty():
            return self.lines.get()
        if self.over:
            return ""
        if self.asked is not None:
            self.asked()
        line = self.lines.get()
        if self.answered is not None:
            self.answered()
        return line


def _no_stop(answer) -> None:
    """A movement that does not end in a `Stopped`: the snapshot carries no reason
    to have stopped, because nothing of the machine was asked to stop."""
    return None


class RunController:
    """One thread, one machine, one way in and one way out."""

    def __init__(self, tell, out=None, errors=None, every: float = EVERY,
                 speed: float | None = None, waits: bool = False) -> None:
        self.tell = tell  # called IN THE THREAD OF THE RUN with every event
        # The input of the program is always `Waiting`: a window has no standard
        # input to read, and the answer comes from whoever owns its main loop. What
        # the program writes goes to the streams the caller gives - a window hands
        # over something that shows what is written as it arrives.
        self.waiting = Waiting(asked=self._asked_for_a_line,
                               answered=self._given_a_line)
        self.io = ConsoleIO(out=out, errors=errors, reader=self.waiting)
        self.every = every
        # How many instructions a second the machine is to carry out, or nothing at
        # all for as fast as it can. A machine that runs at a million instructions
        # a second cannot be watched; one that runs at five can.
        self.speed = speed
        # Whether the loop WAITS TO BE HEARD before it says anything again.
        #
        # Whoever is told a snapshot answers for it - a window builds tables and
        # paints pictures - and if it is told oftener than it can answer, the
        # telling piles up in front of it and it is buried in work it cannot
        # refuse. Measured with the text segment open and a program running at the
        # speed of the machine: the main loop of the window never came up for air
        # (2026-10-25). So whoever is told says `heard()` when it has finished with
        # a snapshot, and until then nothing more is sent: a window that can answer
        # five times a second is told five times a second, and the RUN goes on at
        # its own speed either way - only the telling waits. Whoever does not say
        # so, a test or a script, is told as often as `every` allows.
        self.waits = waits
        self._heard = True
        # Questions answered with every snapshot of a movement, by name, so that
        # whoever is watching a slowed run sees the machine change and not only
        # where it stands. They are answered IN THE THREAD OF THE RUN like any
        # other question, and one that cannot be answered is not asked again.
        self.watching: dict = {}
        self.session: Session | None = None
        self.program: AssembledProgram | None = None
        self.state = NOTHING
        self._work: queue.Queue = queue.Queue()
        # What the world outside asks of a DEVICE - a key pressed, and whatever
        # comes after it. It is a queue of its own because the one moment a key
        # matters is while a program is running and waiting for it, and the queue
        # of work is not looked at again until the movement ends.
        self._world: queue.Queue = queue.Queue()
        self._quiet = threading.Condition()
        self._busy = False
        # Whether the thread has ended, and ended because it was told to rather
        # than by falling over on the way.
        self.closed = False
        self._stopping = False  # whether the run was told to end where it is
        self._said = 0.0  # when the last snapshot went out
        self._due = 0.0  # when the next instruction of a slowed run is due
        self._thread = threading.Thread(target=self._working, name="pyrars-run",
                                        daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- what is asked

    def load(self, project: Project, arguments: tuple[str, ...] = (), **kept) -> None:
        """Assemble a project and open a session over it. Assembling is work, and
        work belongs in the thread of the run."""
        self._queue(LOAD, lambda: self._load(project, arguments, kept))

    def step(self, count: int = 1) -> None:
        self._movement("step", lambda session: session.step(count))

    def over(self, count: int = 1) -> None:
        self._movement("over", lambda session: session.over(count))

    def back(self, count: int = 1) -> None:
        self._movement("back", lambda session: session.back(count))

    def finish(self) -> None:
        self._movement("finish", lambda session: session.finish())

    def carry_on(self) -> None:
        self._movement("continue", lambda session: session.carry_on())

    def until(self, where: int | str) -> None:
        """On to a place and no further. The place may be an address or anything a
        session can name one by - a label, `file:line` - and the naming is done in
        the thread of the run, because only there is there a program to name it in.
        """
        self._movement("until", lambda session: session.until(
            where if isinstance(where, int) else session.address_of(where)))

    def cycle(self, count: int = 1) -> None:
        """On by a cycle of the model of the pipeline.

        It is a MOVEMENT, because knowing what is in the pipeline at the next cycle
        may mean carrying some instructions out; where it does not, nothing of the
        machine moves and the snapshot says as much. Which cycle it now is comes
        back with the models, like everything else about them.
        """
        self._movement("cycle", lambda session: _no_stop(session.cycle_on(count)))

    def restart(self) -> None:
        self.waiting.forget()
        self._movement("restart", lambda session: session.restart())

    def heard(self) -> None:
        """Whoever is being told has finished with the last snapshot and is ready
        for another. It is said from the thread that was told, which is the one
        thread that writes this (see `waits`)."""
        self._heard = True

    def look(self) -> None:
        """Ask for a snapshot of where things are now. A window wants one when it
        has just been opened, or attached to a controller that was already going;
        with no program open it gets a snapshot that says so."""
        self._queue("look", self._shot)

    def ask(self, what: str, question) -> None:
        """Anything else a session can do: `question` is handed the session in the
        thread of the run, and whatever it answers comes back as `Answer(what, ...)`.
        """
        self._queue(what, lambda: Answer(what, question(self._open())))

    def press(self, name: str, key: int) -> None:
        """A key of a device pressed, from wherever that device is shown.

        This and the four below it go in the queue of the world, which the thread
        of the run empties every turn of the loop - so a program that is RUNNING
        and waiting for a key gets it - and a nudge goes through the queue of work
        as well, because the thread may be sitting on that one with nothing to do.
        Whichever of the two gets there first empties the world; the other finds it
        empty.
        """
        self._to_the_world(DEVICE, lambda session: session.press(name, key))

    def typed(self, name: str, text: str) -> None:
        """A text typed at a device AT ONCE, as a hand at a keyboard does it: what
        the program has not read in time is lost, which is the thing a keyboard of
        one key is there to show."""
        self._to_the_world(DEVICE, lambda session: session.typed(name, text))

    def fed(self, name: str, text: str) -> None:
        """A file of keys for a device to take from as it has room, which loses
        nothing: what a command line gives a keyboard."""
        self._to_the_world(DEVICE, lambda session: session.fed(name, text))

    def put_on(self, name: str, data: bytes) -> None:
        """An image onto a device that holds one: a file onto a disk."""
        self._to_the_world(DEVICE, lambda session: session.put_on(name, data))

    def image_of(self, name: str) -> None:
        """What a device is holding, to be written somewhere. It answers under a
        name of its own, because it answers with the BYTES of an image and not with
        the state of a device."""
        self._to_the_world(IMAGE, lambda session: session.image_of(name))

    def ticking(self, name: str, on: bool) -> None:
        """Start or stop the clock of a device by hand."""
        self._to_the_world(DEVICE, lambda session: session.ticking(name, on))

    def _to_the_world(self, what: str, doing) -> None:
        """Something to be done to a device, in the queue of the world and with a
        nudge through the queue of work besides."""
        self._world.put((what, doing))
        self._queue(what, self._world_now)

    # ------------------------------------------- what does not wait for the queue

    def pause(self) -> None:
        """Ask the machine to stop where it is. This is the one thing a window may
        say while a movement is being carried out, so it does not go through the
        queue: it sets a flag the loop reads every turn."""
        if self.session is not None:
            self.session.simulator.pause()

    def stop(self) -> None:
        """End the run where it is.

        `pause` lets the machine stand and the run go on from there; `stop` is the
        end of that run, as it is in RARS, and what follows it is a restart - or a
        step back, for the journal reaches over the end of a run like anywhere else.

        A program WAITING for a line is ended as well. The flag of the loop would
        never be read there - the thread is standing in the input and not in the
        machine - so its input is ended, which wakes it; what the program makes of
        that is its own business, and what the person is told is that the run was
        stopped, because that is what they asked for.
        """
        self._stopping = True
        if self.session is not None:
            self.session.simulator.stop()
        self.waiting.ended()

    def answer(self, text: str) -> None:
        """Hand the program the line it is waiting for."""
        self.waiting.answer(text)

    def no_more_input(self) -> None:
        self.waiting.ended()

    # -------------------------------------------------------------- the thread

    @property
    def queued(self) -> int:
        """How much is waiting to be done. Nothing should pile up here while a
        movement goes on: the thread is inside the movement, so whatever is asked
        of it waits, and a run without an end makes everything wait for ever."""
        return self._work.qsize()

    def settled(self, timeout: float = 5.0) -> bool:
        """Wait until everything asked for has been done; False if it is still
        going. For a test and for a window that is closing - never for the loop of
        a window, which must not wait for anything."""
        with self._quiet:
            return self._quiet.wait_for(
                lambda: not self._busy and self._work.empty(), timeout)

    def close(self, timeout: float = 5.0) -> None:
        """Let the thread end. A movement still being carried out is asked to stop
        first, so that closing a window does not wait for a program without an end.
        """
        self.stop()
        self._work.put(None)
        self._thread.join(timeout)

    def __enter__(self) -> "RunController":
        return self

    def __exit__(self, *gone) -> None:
        self.close()

    # ------------------------------------------------------------- inside only

    def _working(self) -> None:
        """The thread of the run: one piece of work at a time, in the order asked."""
        while True:
            work = self._work.get()
            if work is None:  # the controller is closing
                self.closed = True
                return
            what, doing = work
            with self._quiet:
                self._busy = True
            try:
                told = doing()
                if told is not None:
                    self.tell(told)
            except Exception as problem:  # a question of a window must not kill it
                self.tell(Failed(what, str(problem) or problem.__class__.__name__))
            finally:
                with self._quiet:
                    self._busy = False
                    self._quiet.notify_all()

    def _queue(self, what: str, doing) -> None:
        self._work.put((what, doing))

    def _movement(self, what: str, moving) -> None:
        """A movement of the machine: it takes time, and it ends in a snapshot."""
        self._queue(what, lambda: self._moved(moving))

    def _moved(self, moving) -> Snapshot:
        session = self._open()
        self.state = RUNNING
        self._said = 0.0  # the first turn of a movement says where it is at once
        self._due = 0.0  # and nothing is owed yet: a movement begins unheld
        try:
            stopped = moving(session)
        finally:
            if self._stopping:  # the run was told to end, and it has
                session.ended = True
                self._stopping = False
                # The input was ended to wake the run; whatever follows - a step
                # back and on again, a restart - may be spoken to afresh.
                self.waiting.again()
            self.state = ENDED if session.ended else STANDING
        return self._shot(stopped)

    def _asked_for_a_line(self) -> None:
        """The program wants a line, IN THE THREAD OF THE RUN: nothing of the
        machine goes on until somebody answers, and the window must say so."""
        self.state = WAITING
        self.tell(Answer(ASKING, None))
        self.tell(self._shot())

    def _given_a_line(self) -> None:
        self.state = RUNNING
        self.tell(self._shot())

    def _load(self, project: Project, arguments, kept) -> Answer:
        program = assemble(project.paths, project.options())
        self.program = program
        if program.failed:
            self.session, self.state = None, NOTHING
            return Answer(LOAD, program)
        self.waiting.forget()
        self.session = Session(program, io=self.io, arguments=arguments,
                               watch=self._turn, **kept)
        self.state = STANDING
        self.tell(self._shot())
        return Answer(LOAD, program)

    def _turn(self, turn) -> None:
        """Every turn of the loop, in the thread of the run: whatever the world
        outside asked of a device is done, the run is held back to the speed it was
        given, and a snapshot goes out when enough time has passed since the last
        one, and no oftener."""
        if not self._world.empty():
            self._world_now()
        if self.speed:
            self._held_back()
        now = time.monotonic()
        if now - self._said < self.every or (self.waits and not self._heard):
            return
        self._said = now
        self._heard = False
        # The answers for what is being watched first and the snapshot LAST, so
        # that the snapshot is the end of a batch: whoever is told says it has
        # heard when it has that one, and by then it has had all of them.
        self._watched()
        self.tell(self._shot())
        # And give way, REALLY (see `YIELD`). A run that is being held back to a
        # speed gives way by being slow - it sleeps between its instructions - and
        # is left alone here, so that the pace it was asked for is the pace it
        # keeps.
        if not self.speed:
            time.sleep(YIELD)

    def _world_now(self) -> None:
        """Whatever the world outside asked of a device, IN THE THREAD OF THE RUN,
        which is the only thread that may touch one (INV-T). Each answer goes out
        under its own name, so that whoever shows the device shows it as it now
        is."""
        while not self._world.empty():
            what, doing = self._world.get()
            try:
                self.tell(Answer(what, doing(self._open())))
            except Exception as problem:
                self.tell(Failed(what, str(problem) or problem.__class__.__name__))

    def _watched(self) -> None:
        """Whatever is being watched, with this snapshot."""
        for what, question in tuple(self.watching.items()):
            try:
                self.tell(Answer(what, question(self.session)))
            except Exception as problem:
                # Thirty of the same complaint a second says nothing a window can
                # use; one, and the question is let go.
                self.watching.pop(what, None)
                self.tell(Failed(what, str(problem) or problem.__class__.__name__))

    def _held_back(self) -> None:
        """Hold the run back before it carries out the next instruction.

        A speed is a CEILING: so many instructions a second and no more. The
        waiting is counted from when the last instruction was DUE rather than from
        now, so that what the turn itself took is part of what it was given and not
        something added to it; but a run that has fallen behind - a slow
        instruction, a line waited for, a speed just raised - begins counting again
        from now rather than owing the difference for ever and then racing to repay
        it, which is the opposite of what a slow run is for.

        The first turn of a movement waits for nothing - its `_due` of zero is a
        time long past, which is the same thing as having fallen behind. This is
        called AFTER an instruction, so by then that instruction has been carried
        out: a step at one a second is a step and not a second of nothing, and a
        run of N instructions takes the N - 1 intervals that lie between them.
        """
        now = time.monotonic()
        wait = 1.0 / self.speed
        if self._due > now:
            time.sleep(self._due - now)
            self._due += wait
        else:
            self._due = now + wait

    def _shot(self, stopped: Stopped | None = None) -> Snapshot:
        """Where the run is now."""
        session = self.session
        if session is None:
            return Snapshot(NOTHING)
        counted = session.count()
        return Snapshot(self.state, session.where(), counted.instructions,
                        counted.turns, counted.back, stopped)

    def _open(self) -> Session:
        if self.session is None:
            raise ValueError("no program is open")
        return self.session
