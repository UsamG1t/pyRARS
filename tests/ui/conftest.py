"""What a test of the window needs before it can build one.

The marker is `ui`, and it skips where there is no GTK and no display, exactly as
`devel` skips where there is no jar: the suite must run on a machine that has no
window system at all.
"""

import pytest


@pytest.fixture
def gtk():
    """GTK itself, or a skip. Answers with the main context, which a test turns by
    hand because there is no application running one."""
    gi = pytest.importorskip("gi", reason="the window needs PyGObject")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    if not Gtk.init_check():
        pytest.skip("the window needs a display")
    Adw.init()
    return GLib.MainContext.default()


@pytest.fixture
def turning(gtk):
    """Turn the main loop until something is true, or say that it never was.

    Every event of the controller arrives through `GLib.idle_add`, so a test that
    does not turn the loop sees nothing; and one that turns it for ever would hang,
    so this one always ends.
    """
    import time

    def turn(whether, timeout: float = 5.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            # A bounded number of events at a time: a program without an end keeps
            # the loop fed for ever, and a drain that waited for quiet would never
            # look at the clock again (stage 45).
            for _ in range(500):
                if not gtk.pending():
                    break
                gtk.iteration(False)
            if whether():
                return True
            time.sleep(0.002)
        return False

    return turn
