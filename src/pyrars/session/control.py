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

# Where a run is, as a snapshot says it.
NOTHING = "nothing"  # no program is open
STANDING = "standing"  # a program is open and the machine stands still
RUNNING = "running"
WAITING = "waiting"  # the program has asked for a line and nothing goes on until it has one
ENDED = "ended"  # the run is over: a restart or a step back follows

# The names the controller answers under, where it asks something of its own.
LOAD = "load"
ASKING = "asking"  # the program is waiting for a line of input


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


class RunController:
    """One thread, one machine, one way in and one way out."""

    def __init__(self, tell, out=None, errors=None, every: float = EVERY) -> None:
        self.tell = tell  # called IN THE THREAD OF THE RUN with every event
        # The input of the program is always `Waiting`: a window has no standard
        # input to read, and the answer comes from whoever owns its main loop. What
        # the program writes goes to the streams the caller gives - a window hands
        # over something that shows what is written as it arrives.
        self.waiting = Waiting(asked=self._asked_for_a_line,
                               answered=self._given_a_line)
        self.io = ConsoleIO(out=out, errors=errors, reader=self.waiting)
        self.every = every
        self.session: Session | None = None
        self.program: AssembledProgram | None = None
        self.state = NOTHING
        self._work: queue.Queue = queue.Queue()
        self._quiet = threading.Condition()
        self._busy = False
        # Whether the thread has ended, and ended because it was told to rather
        # than by falling over on the way.
        self.closed = False
        self._stopping = False  # whether the run was told to end where it is
        self._said = 0.0  # when the last snapshot went out
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

    def until(self, address: int) -> None:
        self._movement("until", lambda session: session.until(address))

    def restart(self) -> None:
        self.waiting.forget()
        self._movement("restart", lambda session: session.restart())

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
        """Every turn of the loop, in the thread of the run: a snapshot goes out
        when enough time has passed since the last one, and no oftener."""
        now = time.monotonic()
        if now - self._said < self.every:
            return
        self._said = now
        self.tell(self._shot())
        # And give way. The loop of the machine is Python, so it holds the
        # interpreter until it is taken from it; whoever is being told these
        # snapshots has to be able to answer a pointer while they arrive.
        time.sleep(0)

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
