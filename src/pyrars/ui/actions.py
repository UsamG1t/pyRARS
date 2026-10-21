"""What a window can be told to do, and when it can be told it.

Which actions are possible is a RULE, not a widget: a run that stands still can be
stepped and cannot be paused, a run that is going can be paused and cannot be
stepped, and a step back is only possible while the journal has something in it.
So the catalogue lives here, away from GTK, and the window only reads it.

The names are the session's own - assemble, continue, step, over, back, finish,
pause, stop, restart - and not the Run-and-Debug pair of RARS, because the
difference RARS needs does not exist for us: a session always keeps a journal and
always stands still once a program is assembled, so there is nothing to choose
between before a run begins.

The keys are RARS's where the action is RARS's (verified in the byte code of
`VenusUI`: F3 assemble, F5 run, F7 step, F8 backstep, F9 pause, F11 stop, F12
reset), because a person who comes from RARS should keep their fingers. The
actions it has not got took the free keys beside them.
"""

from dataclasses import dataclass

from pyrars.session.control import ENDED, NOTHING, RUNNING, STANDING, WAITING

# A run that has ended, or stands still, or has not begun: in all three the
# machine is not going anywhere by itself.
STILL = frozenset({NOTHING, STANDING, ENDED})


@dataclass(frozen=True, slots=True)
class Action:
    """One thing a window can be told to do."""

    name: str
    label: str  # what the button says
    about: str  # what it says when the pointer rests on it
    keys: str  # the accelerator, in the spelling of GTK
    states: frozenset[str]  # the states of a run in which it is possible at all
    journal: bool = False  # whether it needs something in the journal as well


ACTIONS = (
    Action("assemble", "Assemble", "Assemble the program and stand at its first "
           "instruction", "F3", STILL),
    Action("continue", "Run", "Carry on to a breakpoint, a watchpoint or the end of "
           "the run", "F5", frozenset({STANDING})),
    Action("until", "To here", "Carry on to the line the cursor is on, and no "
           "further", "F4", frozenset({STANDING})),
    Action("step", "Step", "Carry out one instruction", "F7",
           frozenset({STANDING})),
    Action("over", "Over", "Carry out one instruction, passing over a call - a guess "
           "from the convention", "F6", frozenset({STANDING})),
    Action("finish", "Finish", "Carry on out of the call the run is inside - a guess "
           "from the convention", "<Shift>F6", frozenset({STANDING})),
    Action("back", "Back", "Take the last step back", "F8",
           frozenset({STANDING, ENDED}), journal=True),
    Action("pause", "Pause", "Let the machine stand where it is; the run may carry "
           "on from there", "F9", frozenset({RUNNING})),
    # A program waiting for a line can only be ended: the machine is not going
    # anywhere, so there is nothing to pause, and nothing else can be done to it
    # until it has its line.
    Action("stop", "Stop", "End the run where it is", "F11",
           frozenset({RUNNING, WAITING})),
    Action("restart", "Restart", "The program from the beginning; the breakpoints and "
           "the watches stay", "F12", frozenset({STANDING, ENDED})),
)

# What is done to the FILES rather than to the run. These do not depend on what the
# machine is doing - a program may be read and written while it runs - but on what
# is open and what has been changed, so they have a rule of their own.
FILES = (
    Action("new", "New", "A file that is not on the disk yet", "<Primary>n",
           frozenset()),
    Action("open", "Open", "Open a file of a program", "<Primary>o", frozenset()),
    Action("save", "Save", "Write this file to the disk", "<Primary>s", frozenset()),
    Action("save_as", "Save as", "Write this file somewhere else",
           "<Primary><Shift>s", frozenset()),
    Action("close_tab", "Close", "Close this file", "<Primary>w", frozenset()),
    Action("find", "Find", "Find and replace in this file", "<Primary>f",
           frozenset()),
    Action("reference", "What can be written…",
           "Every instruction, directive and register the assembler takes, with "
           "what each of them means", "F1", frozenset()),
    Action("settings", "The run…",
           "What the machine is given besides the program: the devices, the cache, "
           "the pipeline, the counting", "<Primary>comma", frozenset()),
    Action("project", "The program…",
           "What the program IS: the files it is made of, the width of the machine, "
           "the memory configuration", "<Primary>p", frozenset()),
    Action("toggle_break", "Breakpoint here",
           "Stop the run before the line the cursor is on; the margin does the "
           "same when it is clicked", "<Primary>b", frozenset()),
    Action("undo", "Undo", "Take back the last change to this file", "<Primary>z",
           frozenset()),
    Action("redo", "Redo", "Do again what was taken back", "<Primary><Shift>z",
           frozenset()),
)

BY_NAME = {action.name: action for action in ACTIONS + FILES}


def possible(state: str, journal: int = 0) -> frozenset[str]:
    """The actions of the RUN that can be done now: in this state of the run, with
    this many steps left in the journal."""
    return frozenset(action.name for action in ACTIONS
                     if state in action.states and (journal or not action.journal))


def possible_of_a_file(pages: int = 0, modified: bool = False, named: bool = True,
                       undo: bool = False, redo: bool = False) -> frozenset[str]:
    """The actions of the FILES that can be done now.

    A file that has never been saved can always be saved - there is somewhere for
    it to go, and the person is asked where - while one that is on the disk already
    is saved only when it has been changed; everything else needs a file open at
    all, and undo and redo need something to undo.
    """
    # What the program IS and how it is RUN can both be said whether anything is
    # open or not: a project may name files nobody has opened, and the settings of
    # a run belong to the person and not to any one program.
    if not pages:
        return frozenset({"new", "open", "project", "settings", "reference"})
    doing = {"new", "open", "project", "settings", "reference", "save_as",
             "close_tab", "find", "toggle_break"}
    if modified or not named:
        doing.add("save")
    if undo:
        doing.add("undo")
    if redo:
        doing.add("redo")
    return frozenset(doing)
