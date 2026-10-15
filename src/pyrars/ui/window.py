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
    NOTHING, Answer, Failed, RunController, Snapshot)
from pyrars.session import project as projects  # noqa: E402
from pyrars.session.project import Project  # noqa: E402
from pyrars.ui import actions, shown  # noqa: E402
from pyrars.ui.editor import Editor  # noqa: E402


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
        self.standing = _telling()
        self.console = _telling()
        self.messages = _telling()
        self.set_content(self._built())
        for path in files or (project.paths if project is not None else ()):
            self.editor.open(path)

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
        return header

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
        upper.set_end_child(_in_a_frame(self.standing, "Machine"))
        upper.set_position(720)
        upper.set_resize_start_child(True)
        whole = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        whole.set_start_child(upper)
        whole.set_end_child(self._views())
        whole.set_position(480)
        whole.set_resize_start_child(True)
        return whole

    def _views(self) -> Gtk.Widget:
        views = Gtk.Notebook()
        views.append_page(_scrolled(self.console), Gtk.Label(label="Console"))
        views.append_page(_scrolled(self.messages), Gtk.Label(label="Messages"))
        return views

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

    def _opening(self) -> None:
        dialog = Gtk.FileDialog(title="Open a file of the program")
        dialog.open(self, None, self._opened)

    def _opened(self, dialog, answer) -> None:
        try:
            file = dialog.open_finish(answer)
        except GLib.Error:  # the person changed their mind
            return
        if file is not None:
            self.editor.open(file.get_path())

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
        elif isinstance(event, Answer):
            self._said(f"{event.what}: {_short(event.value)}")
        elif isinstance(event, Failed):
            self._said(f"{event.what} failed: {event.message}")
        return GLib.SOURCE_REMOVE

    def _shown(self, shot: Snapshot) -> None:
        """Where the machine stands, as much of it as a skeleton shows."""
        lines = [f"state        {shot.state}"]
        if shot.place is not None:
            lines += [f"pc           0x{shot.place.address:08x}",
                      f"instruction  {shot.place.basic}",
                      f"source       {shot.place.source.strip()}"]
        lines += [f"instructions {shot.instructions}",
                  f"turns        {shot.turns}",
                  f"back         {shot.back}"]
        if shot.stopped is not None:
            lines.append(f"stopped      {shot.stopped.reason}")
        self.standing.get_buffer().set_text("\n".join(lines))

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
