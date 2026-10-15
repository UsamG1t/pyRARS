"""What a window can be told to do, and when.

Which actions are possible is a rule, so it is tested here like any other rule and
needs no GTK at all. The states are the controller's own (`session/control.py`),
and the keys of the actions RARS has are RARS's keys, which is a fact of its byte
code and not a choice to be mutated away quietly.
"""

import pytest

from pyrars.session.control import ENDED, NOTHING, RUNNING, STANDING
from pyrars.ui.actions import ACTIONS, BY_NAME, Action, possible


def test_nothing_but_assembling_before_a_program_is_opened():
    assert possible(NOTHING) == {"assemble"}


def test_what_can_be_done_while_the_machine_stands_still():
    assert possible(STANDING) == {"assemble", "continue", "step", "over", "finish",
                                  "restart"}


def test_only_stopping_while_the_machine_is_going():
    """A run that is going cannot be stepped, and a run that stands cannot be
    paused: everything else would be asking the thread of the run to do two things
    at once."""
    assert possible(RUNNING) == {"pause", "stop"}


def test_what_is_left_when_the_run_is_over():
    assert possible(ENDED) == {"assemble", "restart"}


def test_a_step_back_needs_something_in_the_journal():
    assert "back" not in possible(STANDING, 0)
    assert "back" in possible(STANDING, 1)
    assert "back" in possible(ENDED, 12)  # a step back reaches over the end of a run
    assert "back" not in possible(RUNNING, 12)  # but not while the machine is going


def test_every_action_has_a_key_of_its_own():
    keys = [action.keys for action in ACTIONS]
    assert len(set(keys)) == len(keys)
    assert all(action.keys for action in ACTIONS)


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


def test_a_state_nobody_has():
    assert possible("sideways") == frozenset()
