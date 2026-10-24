"""The panels of the devices: what each one looks like on the screen.

A device is a MODEL and knows nothing of any of this (M5): it says what it HOLDS
(`state`, words for a table) and what it LOOKS LIKE (`looks`, numbers for a
picture), and the picking of a widget for it happens here and nowhere else.

Not every device has a picture, and one is not invented for those that have not: a
timer is a time and a time it was asked for, a halt register is the word last
written to it, and a drawing of a number tells nobody anything that the number
does not. A device with a picture gets it BESIDE its table: the bitmap display
its units, the keyboard and display the text it shows, the digital lab its
segments and its keys, the disk its blocks, the controller how far it has got.
Beside, because the room the views have is wide and shallow while a picture and a
table of names and values are both narrow and long (the architect, 2026-10-22).

A device nobody wrote a panel for still gets one: its table. That is the point of
`state` answering in the device's own words - a device of somebody else's making
shows up here the day it is attached, with nothing added to this module.

A device may also be TALKED TO, and under the picture of the ones that can be
there is a line of whatever that takes: a line to type at the keyboard and display,
the two files of a disk, the clock of a timer to start and stop. Every one of them
goes through a DOOR - `Panel.door` - which is a method of the controller that the
window hands over, so that the panel knows what can be done and nothing of how it
reaches the machine (which is the thread of the run, and nothing else may touch a
device: INV-T).
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import GLib, Gtk  # noqa: E402

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
        if looks.get("dropped"):
            said += (f"\n[{looks['dropped']} characters lost: the display was busy "
                     "with the one before]")
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

    def __init__(self, name: str, doors=None, **kept) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, **kept)
        self.device = name
        # The ways of doing something TO this device, by name: the window hands
        # over the controller's own methods, so a panel knows what can be done and
        # nothing of how it gets there. It is handed over as something to ASK,
        # because the first panels are built while the window is still being built
        # and the thread of the run is not there yet.
        self.doors = doors or (lambda: {})
        self.writing = ""  # where the image of a disk is to be written, when asked
        self.table = Table(shown.ONE_STATE,
                           f"The {name} says nothing of itself until a program is "
                           "assembled")
        drawn = PICTURES.get(name)
        self.picture = None
        if drawn is None:
            self.append(self.table)
            self._also_done()
            return
        self.picture, self.made = drawn[0](), drawn[1]
        if isinstance(self.picture, Canvas):
            self.picture.pressed = self._clicked
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
        self._also_done()

    def _also_done(self) -> None:
        """The line of what can be DONE to this device, where anything can."""
        doing = DOINGS.get(self.device)
        if doing is not None:
            self.append(doing(self))

    def door(self, what: str):
        """The way to do one thing to this device. A panel built without any - in
        a test, say - has doors that go nowhere, and pressing them does nothing."""
        return self.doors().get(what, lambda *gone: None)

    def _clicked(self, what: str) -> None:
        """Something of the picture was pressed."""
        key = _clicked_on(what)
        if key is not None:
            self.door("press")(self.device, key)

    def wrote(self, data: bytes) -> None:
        """The image this panel asked for, come back from the thread of the run. It
        goes to the file that was chosen when it was asked for, and whatever came
        of that is said where the window says things."""
        if not self.writing:
            return
        where, self.writing = self.writing, ""
        try:
            Path(where).write_bytes(data)
        except OSError as problem:
            self.door("said")(f"{where}: {problem.strerror or problem}")
            return
        self.door("said")(f"the {self.device}: {len(data)} bytes written to "
                          f"{shown.name_of(where)}")

    def show(self, seen, base: int = 0, tables: bool = True) -> None:
        """What the device is now: its picture where it has one, and its table.

        `tables` is false while the machine RUNS: a table is a call into GTK for
        every row of it and those calls are dear while a thread of Python runs flat
        out, where a picture is one call and a redraw (the rule of
        `Window._shown`). So a bitmap display paints and a lab lights up while the
        program runs, and their numbers wait for it to stand still.

        A device that is not attached any more is left as it was: the last thing it
        held is more use than an empty panel.
        """
        if seen is None:
            return
        if self.picture is not None:
            self.picture.show(self.made(seen.looks))
        if tables:
            self.table.show(shown.one_state(seen, base))


# ------------------------------------------------- what can be DONE to a device


def _typing(panel: "Panel") -> Gtk.Widget:
    """A line to type at the keyboard and display, and a file to pour into it.

    The line goes to the device AT ONCE, every letter of it, room or no room - and
    a keyboard of one key loses what the program did not read in time. That is
    deliberate (the architect, 2026-10-26): the device is there to show that the
    asking is not continuous and that letters CAN be lost, and a line that could
    not be lost would teach the opposite. The panel says how many went that way.

    The FILE is the other way (`fed`): the device takes a letter whenever it has
    room, so a prepared input is read whole - which is what the command line does
    with `--device keyboard:keys=...`.

    The newline of pressing Return goes in with the line, because that is what a
    program reading a line is waiting for - and it can be lost like any other.
    """
    typing = Gtk.Entry(placeholder_text="A line typed at it AT ONCE: what the "
                                        "program does not read in time is lost",
                       margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)

    def typed(*gone) -> None:
        line = typing.get_text()
        typing.set_text("")
        panel.door("typed")(panel.device, line + "\n")

    typing.connect("activate", typed)
    panel.typing = typing  # the one widget anybody else needs by name
    whole = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    typing.set_hexpand(True)
    whole.append(typing)
    poured = _button("Pour a file in…", lambda: _a_file_to_type(panel))
    poured.set_tooltip_text("A file the keyboard takes a letter from whenever it "
                            "has room, so that nothing of it is lost")
    whole.append(poured)
    return whole


def _a_file_to_type(panel: "Panel") -> None:
    """A whole file for the keyboard to type, which is what a command line does
    with `--device keyboard:keys=...`."""
    def chosen(dialog, answer) -> None:
        try:
            file = dialog.open_finish(answer)
        except GLib.Error:  # the person changed their mind
            return
        if file is not None:
            poured(panel, file.get_path())

    Gtk.FileDialog(title="A file for the keyboard to take keys from").open(
        panel.get_root(), None, chosen)


def poured(panel: "Panel", where: str) -> None:
    """A file for a keyboard to take letters FROM, whenever it has room: the way
    that loses nothing. A line typed by hand goes the other way (`typed`)."""
    text = _read(panel, where, binary=False)
    if text is not None:
        panel.door("fed")(panel.device, text)


def _files(panel: "Panel") -> Gtk.Widget:
    """The two files of a disk: one to put on it, and one to write it to.

    Writing happens WHEN IT IS ASKED FOR and never by itself (the architect's
    decision, 2026-10-25). The command line writes the image back at the end of a
    run because the person named the file in the command, which is the asking; a
    window that wrote to somebody's disk unasked would be taking that on itself.
    """
    whole = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                    margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)
    whole.append(_button("Put a file on it…", lambda: _an_image_for(panel)))
    whole.append(_button("Write it to a file…", lambda: _an_image_from(panel)))
    return whole


def _an_image_for(panel: "Panel") -> None:
    def chosen(dialog, answer) -> None:
        try:
            file = dialog.open_finish(answer)
        except GLib.Error:
            return
        if file is not None:
            put_on(panel, file.get_path())

    Gtk.FileDialog(title="An image for the disk").open(panel.get_root(), None,
                                                       chosen)


def put_on(panel: "Panel", where: str) -> None:
    """A file onto a device that holds an image. The size is the device's own, so
    a file of the wrong size is refused by the device and said by the window."""
    data = _read(panel, where, binary=True)
    if data is not None:
        panel.door("put_on")(panel.device, data)


def _an_image_from(panel: "Panel") -> None:
    """Where the image is to go. It is chosen FIRST and the image asked for after,
    because the image comes back from the thread of the run and whoever gets it
    has to know already where it belongs."""
    def chosen(dialog, answer) -> None:
        try:
            file = dialog.save_finish(answer)
        except GLib.Error:
            return
        if file is not None:
            panel.writing = file.get_path()
            panel.door("image_of")(panel.device)

    Gtk.FileDialog(title="Write the image of the disk",
                   initial_name=f"{panel.device}.img").save(panel.get_root(),
                                                            None, chosen)


def _clock(panel: "Panel") -> Gtk.Widget:
    """The clock of a timer, to be stopped and started by hand - which is what the
    timer of RARS lets one do, and what shows a program reading a time that does
    not move."""
    whole = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                    margin_top=4, margin_bottom=4, margin_start=4, margin_end=4)
    whole.append(_button("Start the clock",
                         lambda: panel.door("ticking")(panel.device, True)))
    whole.append(_button("Stop the clock",
                         lambda: panel.door("ticking")(panel.device, False)))
    return whole


# What can be done to a device, by its name. A device that is not here is looked
# at and not talked to.
DOINGS = {"keyboard": _typing, "disk": _files, "timer": _clock}


def _read(panel: "Panel", where: str, binary: bool):
    """A file for a device, or nothing and a word about why: a file that cannot be
    read is SAID and not thrown, as everywhere else a window reads one."""
    try:
        return (Path(where).read_bytes() if binary
                else Path(where).read_text())
    except (OSError, UnicodeDecodeError) as problem:
        panel.door("said")(f"{where}: "
                           f"{getattr(problem, 'strerror', None) or problem}")
        return None


def _button(label: str, doing) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.connect("clicked", lambda *gone: doing())
    return button


def _clicked_on(what: str) -> int | None:
    """The key a part of a picture stands for, or nothing where it stands for
    something else. The names come from the picture itself (`ui/drawing.py`), so
    what can be pressed is said in one place and read in another."""
    if not what.startswith(drawing.KEY_PRESSED):
        return None
    which = what[len(drawing.KEY_PRESSED):]
    return int(which) if which.isdigit() else None


def _scrolled(child: Gtk.Widget) -> Gtk.Widget:
    window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    window.set_child(child)
    return window
