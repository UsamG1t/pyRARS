"""The panels of the devices: what each one looks like on the screen.

A device is a MODEL and knows nothing of any of this (M5): it says what it HOLDS
(`state`, words for a table) and what it LOOKS LIKE (`looks`, numbers for a
picture), and the picking of a widget for it happens here and nowhere else.

Not every device has a picture, and one is not invented for those that have not: a
timer is a time and a time it was asked for, a halt register is the word last
written to it, and a drawing of a number tells nobody anything that the number
does not. A device with a picture gets it BESIDE its table - the bitmap display its units,
the keyboard and display the text it shows, the digital lab its segments and its
keys, the disk its blocks, the controller of direct access how far it has got.
Beside, because the room the views have is wide and shallow while a picture and a
table of names and values are both narrow and long (the architect, 2026-10-22).

A device nobody wrote a panel for still gets one: its table. That is the point of
`state` answering in the device's own words - a device of somebody else's making
shows up here the day it is attached, with nothing added to this module.
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

from pyrars.ui import drawing, shown  # noqa: E402
from pyrars.ui.canvas import Canvas, Pixels  # noqa: E402
from pyrars.ui.table import Table  # noqa: E402


class Display(Gtk.ScrolledWindow):
    """The text a display is showing, in a monospace view nobody types into.

    This is the picture of a display: what it shows is CHARACTERS, and a drawing
    of characters is characters.
    """

    __gtype_name__ = "PyrarsDisplay"

    def __init__(self, **kept) -> None:
        super().__init__(hexpand=True, vexpand=True, **kept)
        self.view = Gtk.TextView(editable=False, cursor_visible=False,
                                 monospace=True)
        self.view.set_left_margin(8)
        self.view.set_top_margin(4)
        self.set_child(self.view)

    def show(self, looks: dict) -> None:
        said = str(looks.get("text", ""))
        if looks.get("queued"):
            said += f"\n\n[{looks['queued']} keys typed and not read yet]"
        if looks.get("lost"):
            said += f"\n[{looks['lost']} keys lost: the program did not read them]"
        self.view.get_buffer().set_text(said)


# What a device is drawn with, and what the drawing is made from. A device that is
# not here has no picture and is its table alone.
PICTURES = {
    "bitmap": (Pixels, lambda looks: looks),
    "keyboard": (Display, lambda looks: looks),
    "lab": (Canvas, drawing.lab_picture),
    "disk": (Canvas, drawing.blocks_picture),
    "dma": (Canvas, drawing.copying_picture),
}


class Panel(Gtk.Box):
    """One device: what it looks like, and what it holds beside it."""

    __gtype_name__ = "PyrarsDevicePanel"

    def __init__(self, name: str, **kept) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kept)
        self.device = name
        self.table = Table(shown.ONE_STATE,
                           f"The {name} says nothing of itself until a program is "
                           "assembled")
        drawn = PICTURES.get(name)
        self.picture = None
        if drawn is None:
            self.append(self.table)
            return
        self.picture, self.made = drawn[0](), drawn[1]
        # A picture that scrolls itself is put in as it is; one that does not is
        # given something to scroll in, because a bitmap display of 512 by 256 is
        # wider and taller than any room it will be given.
        inside = (self.picture if isinstance(self.picture, Gtk.ScrolledWindow)
                  else _scrolled(self.picture))
        pane = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        pane.set_start_child(inside)
        pane.set_end_child(self.table)
        pane.set_position(520)
        pane.set_resize_start_child(True)
        pane.set_resize_end_child(True)
        self.append(pane)

    def show(self, seen, form: str = "hex", base: int = 0) -> None:
        """What the device is now: its table always, and its picture where it has
        one. A device that is not attached any more is left as it was - the last
        thing it held is more use than an empty panel."""
        if seen is None:
            return
        self.table.show(shown.one_state(seen, form, base))
        if self.picture is not None:
            self.picture.show(self.made(seen.looks))


def _scrolled(child: Gtk.Widget) -> Gtk.Widget:
    window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    window.set_child(child)
    return window
