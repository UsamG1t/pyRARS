"""The one window: the program and the state of the machine side by side.

The editor and the state are seen at the same time, with the views below them and
the actions in the header (user decision 2026-10-14). The window holds no logic of
its own: which actions are possible comes from `ui/actions.py`, and everything
about the run comes from the controller, whose events arrive from the thread of the
run and are handed to the main loop before a widget is touched (INV-T).
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402 - after require_version

from pyrars.session.control import (  # noqa: E402
    ASKING, ENDED, LOAD, NOTHING, RUNNING, STANDING, WAITING, Answer, Failed,
    RunController, Snapshot)
from pyrars.session import project as projects  # noqa: E402
from pyrars.session.project import Project  # noqa: E402
from pyrars.ui import actions, shown  # noqa: E402
from pyrars.ui.editor import Editor  # noqa: E402
from pyrars.ui.table import Table  # noqa: E402
from pyrars.values import VALUE_FORMATS  # noqa: E402


class Writing:
    """A stream the program writes to that puts what it writes in the window.

    The program writes from the thread of the run, so every piece is handed to the
    main loop and the widget is touched from its own thread only. Nothing written
    here can be taken back, which is what the world of a shared terminal says as
    well: a step back does not unprint what has been seen.
    """

    def __init__(self, shown) -> None:
        self.shown = shown

    def write(self, text: str) -> int:
        GLib.idle_add(self.shown, text)
        return len(text)

    def flush(self) -> None:
        pass

    def seekable(self) -> bool:
        return False  # a window is a terminal, not a buffer that can be cut


class Window(Adw.ApplicationWindow):
    """The window itself."""

    __gtype_name__ = "PyrarsWindow"

    def __init__(self, project: Project | None = None, files: tuple[str, ...] = (),
                 cache: str | None = None, **kept) -> None:
        super().__init__(title="pyRARS", **kept)
        self.project = project
        self.state = NOTHING
        self.journal = 0
        self.buttons: dict[str, Gtk.Button] = {}
        self.set_default_size(1100, 740)

        self.editor = Editor(cache)
        self.editor.watchers.append(self._files_changed)
        self.editor.marked.append(self._breakpoint_changed)
        self.format = "hex"
        self.program = None
        self.standing = Gtk.Label(xalign=0.0, selectable=True)
        self.standing.add_css_class("monospace")
        self.views_of = {
            "registers": Table(shown.REGISTERS), "floats": Table(shown.FLOATS),
            "control": Table(shown.CONTROL), "text": Table(shown.TEXT),
            "data": Table(shown.DATA), "labels": Table(shown.LABELS),
            "frames": Table(shown.FRAMES),
        }
        self.console = _telling()
        self.messages = _telling()
        self.set_content(self._built())
        for path in files or (project.paths if project is not None else ()):
            self.open(path)

        # The controller writes from its own thread; `Writing` hands every piece to
        # the main loop, and the events go the same way through `_told`.
        self.control = RunController(self._told, out=Writing(self._printed),
                                     errors=Writing(self._printed))
        self._possible()

    # ---------------------------------------------------------------- the shape

    def _built(self) -> Gtk.Widget:
        whole = Adw.ToolbarView()
        whole.add_top_bar(self._header())
        whole.set_content(self._panes())
        return whole

    def _header(self) -> Gtk.Widget:
        header = Adw.HeaderBar()
        files = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for name, icon in (("open", "document-open-symbolic"),
                           ("save", "document-save-symbolic")):
            files.append(self._button(actions.BY_NAME[name], icon))
        header.pack_start(files)

        doing = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        doing.add_css_class("linked")
        for action in actions.ACTIONS:
            doing.append(self._button(action))
        header.pack_start(doing)
        header.pack_end(self._menu())
        header.pack_end(self._formats())
        return header

    def _formats(self) -> Gtk.Widget:
        """How every value of the machine is written, which is one choice for all
        of them: a person reading a register in hexadecimal is reading memory in
        hexadecimal too."""
        chooser = Gtk.DropDown.new_from_strings(list(VALUE_FORMATS))
        chooser.set_tooltip_text("How values are written")
        chooser.connect("notify::selected", self._format_chosen)
        return chooser

    def _format_chosen(self, chooser, parameter) -> None:
        self.format = VALUE_FORMATS[chooser.get_selected()]
        self._views_again()

    def _button(self, action: actions.Action, icon: str | None = None) -> Gtk.Button:
        button = (Gtk.Button(icon_name=icon) if icon
                  else Gtk.Button(label=action.label))
        button.set_tooltip_text(f"{action.about} ({action.keys})")
        button.connect("clicked", self._asked, action.name)
        self.buttons[action.name] = button
        return button

    def _menu(self) -> Gtk.Widget:
        """What is done to the files, where a header bar has no room for it."""
        menu = Gio.Menu()
        files = Gio.Menu()
        for name in ("new", "open", "save", "save_as", "close_tab"):
            files.append(actions.BY_NAME[name].label, f"app.{name}")
        changes = Gio.Menu()
        for name in ("undo", "redo", "find"):
            changes.append(actions.BY_NAME[name].label, f"app.{name}")
        menu.append_section(None, files)
        menu.append_section(None, changes)
        menu.append_section(None, _one_item("Quit", "app.quit"))
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu,
                              tooltip_text="Everything else")

    def _panes(self) -> Gtk.Widget:
        upper = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        upper.set_start_child(self.editor)
        upper.set_end_child(self._machine())
        upper.set_position(700)
        upper.set_resize_start_child(True)
        whole = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        whole.set_start_child(upper)
        whole.set_end_child(self._views())
        whole.set_position(480)
        whole.set_resize_start_child(True)
        return whole

    def _machine(self) -> Gtk.Widget:
        """Where the run is, and the three files of registers under it."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.standing.set_margin_start(8)
        self.standing.set_margin_top(6)
        self.standing.set_margin_bottom(6)
        box.append(self.standing)
        pages = Gtk.Notebook()
        for name, title in (("registers", "Registers"), ("floats", "Floats"),
                            ("control", "Control")):
            pages.append_page(self.views_of[name], Gtk.Label(label=title))
        box.append(pages)
        return box

    def _views(self) -> Gtk.Widget:
        self.views = Gtk.Notebook()
        for name, title in (("text", "Text"), ("data", "Data"),
                            ("labels", "Labels"), ("frames", "Frames")):
            self.views.append_page(self.views_of[name], Gtk.Label(label=title))
        self.console_page = self.views.append_page(self._console(),
                                                   Gtk.Label(label="Console"))
        self.views.append_page(_scrolled(self.messages), Gtk.Label(label="Messages"))
        return self.views

    def _console(self) -> Gtk.Widget:
        """What the program writes, and the line it is waiting for.

        One page, as a terminal is one thing: what is typed is echoed where the
        program's own writing goes, so that what is read afterwards is the whole
        conversation and not half of it.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(_scrolled(self.console))
        self.typing = Gtk.Entry(placeholder_text=_TYPE_HERE, margin_top=4,
                                margin_bottom=4, margin_start=4, margin_end=4)
        self.typing.connect("activate", lambda *gone: self._typed())
        box.append(self.typing)
        return box

    # ------------------------------------------------------------- what is done

    def _asked(self, button, name: str) -> None:
        """A button was pressed, or its key. Nothing here waits for anything: the
        controller takes the word and the answer arrives through `_told`."""
        self.do(name)

    def do(self, name: str) -> None:
        """One action by its name, if it is possible at all."""
        if name not in self.allowed():
            return
        if name in _OF_A_FILE:
            _OF_A_FILE[name](self)
            return
        if name == "assemble":
            self._assembled()
            return
        getattr(self.control, {"continue": "carry_on"}.get(name, name))()

    def allowed(self) -> frozenset[str]:
        """Everything that can be done at this moment, of the run and of the files
        alike."""
        page = self.editor.page
        buffer = page.buffer if page is not None else None
        return actions.possible(self.state, self.journal) | actions.possible_of_a_file(
            len(self.editor.pages), self.editor.modified,
            named=bool(page.path) if page is not None else True,
            undo=bool(buffer and buffer.get_can_undo()),
            redo=bool(buffer and buffer.get_can_redo()))

    def _possible(self) -> None:
        """Only what can be done now can be pressed."""
        allowed = self.allowed()
        for name, button in self.buttons.items():
            button.set_sensitive(name in allowed)

    # ---------------------------------------------------------------- the files

    def _assembled(self) -> None:
        """Assemble what is on the screen.

        The assembler reads files from the disk, so everything that has been
        changed is written there first; a file that has never been saved is asked
        about rather than guessed at.
        """
        self.editor.save_every_change()
        paths = self.editor.paths
        if not paths:
            self._said("nothing to assemble: no file of the program is saved yet")
            return
        self.project = (self.project.with_files(paths) if self.project is not None
                        else projects.of(paths, folder=str(Path(paths[0]).parent)))
        self.control.load(self.project)

    def open(self, path: str) -> None:
        """A file into the editor. A file that cannot be read is SAID, not thrown:
        a window that is given a name nobody has must still open."""
        try:
            self.editor.open(path)
        except OSError as problem:
            self._said(f"{path}: {problem.strerror or problem}")

    def _opening(self) -> None:
        dialog = Gtk.FileDialog(title="Open a file of the program")
        dialog.open(self, None, self._opened)

    def _opened(self, dialog, answer) -> None:
        try:
            file = dialog.open_finish(answer)
        except GLib.Error:  # the person changed their mind
            return
        if file is not None:
            self.open(file.get_path())

    def _saving(self) -> None:
        page = self.editor.page
        if page is None:
            return
        if page.path:
            self.editor.save()
            return
        self._saving_as()

    def _saving_as(self) -> None:
        dialog = Gtk.FileDialog(title="Write this file")
        dialog.save(self, None, self._saved)

    def _saved(self, dialog, answer) -> None:
        try:
            file = dialog.save_finish(answer)
        except GLib.Error:
            return
        if file is not None:
            self.editor.save(file.get_path())

    def _files_changed(self) -> None:
        """The editor's tabs or their state changed."""
        page = self.editor.page
        self.set_title(shown.window_title(page.path if page else None,
                                          page.modified if page else False))
        self._possible()

    # ------------------------------------------------------- what comes back

    def _told(self, event) -> None:
        """An event, FROM THE THREAD OF THE RUN: it is handed to the main loop and
        nothing of the window is touched here."""
        GLib.idle_add(self._heard, event)

    def _heard(self, event) -> bool:
        """The same event, now in the thread of the window."""
        if isinstance(event, Snapshot):
            self.state, self.journal = event.state, event.back
            self._shown(event)
            self._possible()
            self.typing.set_placeholder_text(
                _WAITING if event.state == WAITING else _TYPE_HERE)
        elif isinstance(event, Answer):
            if event.what == ASKING:
                self._waiting_for_a_line()
            elif event.what == LOAD:
                self._assembled_into(event.value)
                return GLib.SOURCE_REMOVE
            elif event.what == BREAKS:
                self._breaks_that_missed(event.value)
                return GLib.SOURCE_REMOVE
            elif event.what == REGISTERS:
                self._registers_shown(event.value)
                return GLib.SOURCE_REMOVE
            elif event.what == PLACES:
                self._places_shown(event.value)
                return GLib.SOURCE_REMOVE
            self._said(f"{event.what}: {_short(event.value)}")
        elif isinstance(event, Failed):
            self._said(f"{event.what} failed: {event.message}")
        return GLib.SOURCE_REMOVE

    # ---------------------------------------------- what the editor is told

    def _assembled_into(self, program) -> None:
        """What the assembler said, into the margins of the files it said it
        about; what it said about no place at all, into the messages."""
        by_file, loose = shown.problems(program.diagnostics)
        self.program = None if program.failed else program
        if program.failed:
            self.here = None  # there is no machine to stand anywhere
        # And where it DOES stand is not touched here: the snapshot of the session
        # being built came before this answer did, and it is the one that knows.
        self._text_again()
        self.editor.problems(by_file)
        self.editor.labels = tuple(program.symbols)
        for message in loose:
            self._said(message)
        counted = sum(len(these) for these in by_file.values()) + len(loose)
        if program.failed:
            self._said(f"the program has not been assembled: {counted} to mend")
            return
        self._said(f"assembled: {len(program.text)} instructions"
                   + (f", {counted} to say about it" if counted else ""))
        self._breaks_to_the_machine()

    def _breakpoint_changed(self, page, line: int, on: bool) -> None:
        """A breakpoint was put on or taken off in the margin."""
        if self.state != NOTHING:
            self._breaks_to_the_machine()

    def _breaks_to_the_machine(self) -> None:
        """Every breakpoint the person has put in, as the machine's own.

        They are all given again each time rather than one being added or taken
        off: what the margins hold is what the run must stop at, and saying the
        whole of it cannot drift from it.
        """
        wanted = self.editor.breakpoints()
        self.control.ask(BREAKS, lambda session: _asked_to_stop(session, wanted))

    def _breaks_that_missed(self, missed) -> None:
        """A line with no instruction on it cannot be stopped before, so the mark
        comes off again and the person is told why.

        Whatever came of them, the text segment is written again: it shows what the
        run stops before, and that is what has just changed.
        """
        self._text_again()
        for path, line in missed:
            for page in self.editor.pages:
                if page.path == path and line in page.marked("breakpoint"):
                    page.toggle(line)
            self._said(f"{_short(path)}:{line}: no instruction of the program is "
                       "there, so nothing can stop before it")
        if missed:
            self._text_again()

    def _shown(self, shot: Snapshot) -> None:
        """Where the machine stands, and everything that follows from it.

        While the machine RUNS, this does as little as it can: the line that says
        where the run is, and nothing else. The thread of the run holds the
        interpreter nearly all the time - a loop of a million instructions a second
        is a loop of Python - so every call this thread makes waits its turn, and a
        window that rebuilt its tables thirty times a second would answer the
        pointer in half a second instead of at once. Nothing of what is left out
        could be read at that speed anyway; it is all put up the moment the machine
        stands still.
        """
        self.standing.set_text(shown.standing(shot))
        if shot.state == RUNNING:
            return
        place = shot.place
        self.editor.here(place.file if place else None, place.line if place else 0)
        self.here = place.address if place is not None else None
        if self.session_is_open:
            self.control.ask(REGISTERS, _of_the_registers)
            if shot.state in (STANDING, ENDED):
                # A run that waits for a line is in no state to answer questions:
                # the thread is standing in the input, and the asking would only
                # queue behind it.
                self.control.ask(PLACES, _of_the_places)
        self._text_again()

    def _registers_shown(self, values: dict) -> None:
        self.views_of["registers"].show(
            shown.registers(values["registers"], self.format))
        self.views_of["floats"].show(shown.floats(values["floats"], self.format))
        self.views_of["control"].show(shown.control(values["control"], self.format))

    def _places_shown(self, values: dict) -> None:
        self.views_of["data"].show(shown.data(values["data"], self.format))
        self.views_of["labels"].show(shown.labels(values["labels"]))
        self.views_of["frames"].show(shown.frames(values["frames"]))

    def _text_again(self) -> None:
        """The text segment: the program itself, with the place the machine stands
        on and the places it stops before marked."""
        if self.program is None:
            return
        breaks = {entry.address for entry in self.program.text
                  for page in self.editor.pages
                  if page.path and entry.loc is not None
                  and entry.loc.file == page.path
                  and entry.loc.line in page.marked("breakpoint")}
        self.views_of["text"].show(
            shown.text(self.program.text, self.here, breaks, self.format))

    def _views_again(self) -> None:
        """Everything again, in the format now chosen."""
        self._text_again()
        if self.session_is_open:
            self.control.ask(REGISTERS, _of_the_registers)
            self.control.ask(PLACES, _of_the_places)

    @property
    def session_is_open(self) -> bool:
        return self.state != NOTHING

    def _typed(self) -> None:
        """A line for the program. It may be typed before the program asks for it,
        as it may at a terminal, and it waits here until the program reads it."""
        line = self.typing.get_text()
        self.typing.set_text("")
        self._added(self.console, line + "\n")
        self.control.answer(line)

    def _waiting_for_a_line(self) -> None:
        """The program has asked for something: the console is where the answer
        goes, so that is what the window shows, with the cursor already in it."""
        self.views.set_current_page(self.console_page)
        self.typing.grab_focus()

    def _said(self, line: str) -> None:
        self._added(self.messages, line + "\n")

    def _printed(self, text: str) -> bool:
        self._added(self.console, text)
        return GLib.SOURCE_REMOVE

    def _added(self, view: Gtk.TextView, text: str) -> None:
        buffer = view.get_buffer()
        buffer.insert(buffer.get_end_iter(), text)
        view.scroll_to_iter(buffer.get_end_iter(), 0.0, False, 0.0, 0.0)

    def close_up(self) -> None:
        """Let the thread of the run end; a window that is closing waits for
        nothing."""
        self.control.close()


# What the window asks the session for under its own name.
BREAKS = "breaks"
REGISTERS = "the registers"
PLACES = "the places"


def _of_the_registers(session) -> dict:
    """The three files of registers, in one asking: a question of its own for each
    would be three turns of the queue for one snapshot."""
    return {"registers": session.registers(), "floats": session.floats(),
            "control": session.csr()}


def _of_the_places(session) -> dict:
    return {"data": session.data(), "labels": session.symbols(),
            "frames": session.frames()}

# What the line under the console says when nothing is in it.
_TYPE_HERE = "A line for the program"
_WAITING = "The program is waiting for a line - type it here"


# What each action of the files does to the window.
_OF_A_FILE = {
    "new": lambda window: window.editor.add(),
    "open": lambda window: window._opening(),
    "save": lambda window: window._saving(),
    "save_as": lambda window: window._saving_as(),
    "close_tab": lambda window: window.editor.close(),
    "find": lambda window: window.editor.find(),
    "undo": lambda window: window.editor.undo(),
    "redo": lambda window: window.editor.redo(),
}


def _asked_to_stop(session, wanted) -> list[tuple[str, int]]:
    """Give the session every breakpoint the margins hold, IN THE THREAD OF THE
    RUN; answers with those it could not take."""
    session.remove_break()
    missed = []
    for path, line in wanted:
        try:
            session.add_break(session.address_of(f"{path}:{line}"))
        except ValueError:
            missed.append((path, line))
    return missed


def _one_item(label: str, action: str) -> Gio.Menu:
    menu = Gio.Menu()
    menu.append(label, action)
    return menu


def _telling() -> Gtk.TextView:
    """A view that shows text nobody types into."""
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
    view.set_left_margin(8)
    view.set_top_margin(4)
    return view


def _scrolled(child: Gtk.Widget) -> Gtk.Widget:
    window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
    window.set_child(child)
    return window


def _in_a_frame(child: Gtk.Widget, title: str) -> Gtk.Widget:
    """A piece of the window with its name above it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    label = Gtk.Label(label=title, xalign=0.0)
    label.add_css_class("heading")
    label.set_margin_start(8)
    label.set_margin_top(6)
    label.set_margin_bottom(4)
    box.append(label)
    box.append(_scrolled(child))
    return box


def _short(value: object) -> str:
    """What an answer was, in one line of a window's messages."""
    text = str(value)
    if len(text) > 120:
        text = text[:117] + "..."
    return text.replace("\n", " ")
