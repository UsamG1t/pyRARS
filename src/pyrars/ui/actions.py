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
reset), because a person who comes from RARS should keep their fingers. The two
actions it has not got took the free keys beside them.
"""

from dataclasses import dataclass

from pyrars.session.control import ENDED, NOTHING, RUNNING, STANDING

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
    Action("stop", "Stop", "End the run where it is", "F11",
           frozenset({RUNNING})),
    Action("restart", "Restart", "The program from the beginning; the breakpoints and "
           "the watches stay", "F12", frozenset({STANDING, ENDED})),
)

BY_NAME = {action.name: action for action in ACTIONS}


def possible(state: str, journal: int = 0) -> frozenset[str]:
    """The actions that can be done now: in this state of the run, with this many
    steps left in the journal."""
    return frozenset(action.name for action in ACTIONS
                     if state in action.states and (journal or not action.journal))
