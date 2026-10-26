"""What a window can be told to do, and when.

Which actions are possible is a rule, so it is tested here like any other rule and
needs no GTK at all. The states are the controller's own (`session/control.py`),
and the keys of the actions RARS has are RARS's keys, which is a fact of its byte
code and not a choice to be mutated away quietly.
"""

import pytest

from pyrars.session.control import ENDED, NOTHING, RUNNING, STANDING, WAITING
from pyrars.ui.actions import (
    ACTIONS, BY_NAME, FILES, Action, possible, possible_of_a_file)


def test_nothing_but_assembling_before_a_program_is_opened():
    assert possible(NOTHING) == {"assemble"}


def test_what_can_be_done_while_the_machine_stands_still():
    assert possible(STANDING) == {"assemble", "continue", "until", "step", "over",
                                  "finish", "restart"}
    assert possible(STANDING, pipeline=True) == {
        "assemble", "continue", "until", "step", "over", "finish", "restart",
        "cycle"}


def test_a_cycle_of_the_pipeline_needs_a_pipeline():
    """A cycle of a model nobody asked for is no cycle at all, so the action is
    not there - and the window does not even show its button."""
    assert "cycle" not in possible(STANDING)
    assert "cycle" in possible(STANDING, pipeline=True)
    assert "cycle" not in possible(RUNNING, pipeline=True)  # one thing at a time
    # but a run that is OVER has cycles left to walk: the pipeline drains for four
    # cycles after the last instruction was fetched, and that is the half of the
    # picture nobody ever sees otherwise
    assert "cycle" in possible(ENDED, pipeline=True)
    assert BY_NAME["cycle"].keys == "<Shift>F7"  # a smaller thing than a step


def test_only_stopping_while_the_machine_is_going():
    """A run that is going cannot be stepped, and a run that stands cannot be
    paused: everything else would be asking the thread of the run to do two things
    at once."""
    assert possible(RUNNING) == {"pause", "stop"}


def test_what_is_left_when_the_run_is_over():
    assert possible(ENDED) == {"assemble", "restart"}
    assert possible(ENDED, pipeline=True) == {"assemble", "restart", "cycle"}


def test_a_program_waiting_for_a_line_can_only_be_ended():
    """There is nothing to pause: the machine is not going anywhere until somebody
    types. Everything else would queue behind a thread that is standing still."""
    assert possible(WAITING) == {"stop"}
    assert possible(WAITING, journal=99) == {"stop"}


def test_a_step_back_needs_something_in_the_journal():
    assert "back" not in possible(STANDING, 0)
    assert "back" in possible(STANDING, 1)
    assert "back" in possible(ENDED, 12)  # a step back reaches over the end of a run
    assert "back" not in possible(RUNNING, 12)  # but not while the machine is going


def test_every_action_has_a_key_of_its_own():
    """Of the run and of the files alike: they are pressed in the same window, and
    one key cannot mean two things in it."""
    keys = [action.keys for action in ACTIONS + FILES]
    assert len(set(keys)) == len(keys)
    assert all(action.keys for action in ACTIONS + FILES)


def test_the_actions_rars_has_keep_the_keys_rars_gives_them():
    """Verified in the byte code of `VenusUI`: a person who comes from RARS keeps
    their fingers."""
    assert BY_NAME["assemble"].keys == "F3"
    assert BY_NAME["continue"].keys == "F5"  # "Run" there
    assert BY_NAME["step"].keys == "F7"
    assert BY_NAME["back"].keys == "F8"  # "Backstep" there
    assert BY_NAME["pause"].keys == "F9"
    assert BY_NAME["stop"].keys == "F11"
    assert BY_NAME["restart"].keys == "F12"  # "Reset" there


def test_the_actions_rars_has_not_got_took_the_free_keys_beside_them():
    assert BY_NAME["over"].keys == "F6"
    assert BY_NAME["finish"].keys == "<Shift>F6"
    assert BY_NAME["until"].keys == "F4"


def test_every_action_says_what_it_is_for():
    for action in ACTIONS:
        assert action.label and action.about
        assert action.about[0].isupper(), action.name
        assert not action.about.endswith("."), action.name


def test_the_guesses_say_that_they_are_guesses():
    """`over` and `finish` read the return address the way the convention says, and
    a window must not offer them as if they were certain (D21)."""
    assert "guess" in BY_NAME["over"].about
    assert "guess" in BY_NAME["finish"].about


# ------------------------------------------------------- what is done to a file


def test_nothing_but_opening_with_no_file_open():
    # what the program IS, how it is RUN and what may be written in one can always
    # be asked: none of the three is about the file being looked at
    assert possible_of_a_file() == {"new", "open", "project", "settings",
                                    "reference"}


def test_what_can_be_done_to_a_file_that_is_open():
    assert possible_of_a_file(1) == {"new", "open", "project", "settings",
                                     "reference", "save_as", "close_tab", "find",
                                     "toggle_break"}


def test_the_breakpoint_by_key_says_where_it_lands():
    """"here" is the word that matters: it acts on the line the cursor is on, which
    is what tells it from the margin, where a line is chosen by pointing at it."""
    assert BY_NAME["toggle_break"].label == "Breakpoint here"
    assert "the line the cursor is on" in BY_NAME["toggle_break"].about


def test_a_breakpoint_can_be_put_in_before_there_is_a_program():
    """A line is marked in a file, and a file is there before any of it is
    assembled: open, mark, assemble is the ordinary way of working."""
    assert "toggle_break" in possible_of_a_file(1)
    assert "toggle_break" not in possible_of_a_file(0)


def test_a_file_is_saved_when_there_is_something_to_save():
    assert "save" not in possible_of_a_file(1)  # it is as it is on the disk
    assert "save" in possible_of_a_file(1, modified=True)


def test_a_file_that_has_never_been_saved_can_always_be_saved():
    """There is somewhere for it to go: the person is asked where."""
    assert "save" in possible_of_a_file(1, modified=False, named=False)


def test_undoing_needs_something_to_undo():
    assert "undo" not in possible_of_a_file(1)
    assert "redo" not in possible_of_a_file(1)
    assert "undo" in possible_of_a_file(1, undo=True)
    assert "redo" in possible_of_a_file(1, redo=True)


def test_what_is_done_to_a_file_does_not_depend_on_what_the_machine_is_doing():
    """A program may be read and written while it runs: the two rules do not meet,
    and nothing of a file is in the rule of the run."""
    of_the_run = {action.name for action in ACTIONS}
    of_a_file = {action.name for action in FILES}
    assert not of_the_run & of_a_file
    assert possible_of_a_file(1, modified=True) == possible_of_a_file(1, modified=True)


def test_every_action_of_a_file_has_a_key_of_its_own():
    keys = [action.keys for action in FILES]
    assert len(set(keys)) == len(keys)
    assert BY_NAME["save"].keys == "<Primary>s"  # what every editor uses
    assert BY_NAME["find"].keys == "<Primary>f"
    assert BY_NAME["undo"].keys == "<Primary>z"


def test_no_two_actions_anywhere_share_a_key():
    keys = [action.keys for action in ACTIONS + FILES]
    assert len(set(keys)) == len(keys)


def test_a_state_nobody_has():
    assert possible("sideways") == frozenset()
