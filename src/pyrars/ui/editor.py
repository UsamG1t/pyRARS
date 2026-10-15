"""The editor: the files of a program, one to a tab.

What it colours comes from `ui/highlighting.py`, which makes a language definition
out of the tables of the assembler itself, so the editor cannot know a mnemonic the
assembler does not. The definition is written into the cache folder of the person
and read from there, because GtkSourceView reads its languages from a folder and
there is no way to hand it one made in memory.

Undo, redo and the search are GtkSourceView's own; what belongs to us is the list
of files, which of them have been changed, and saving them before a program is
assembled - an assembler reads files from the disk, so what is on the screen has to
be on the disk first.
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GtkSource", "5")

from gi.repository import Adw, GLib, Gtk, GtkSource  # noqa: E402

from pyrars.ui import shown  # noqa: E402
from pyrars.ui.highlighting import ID, language  # noqa: E402


def languages(folder: str | None = None) -> GtkSource.LanguageManager:
    """A manager that knows our dialect, with the definition written out fresh.

    It is written every time: the tables it is made from are those of the running
    assembler, so a definition left over from another version is of no use to
    anyone.
    """
    where = Path(folder or GLib.get_user_cache_dir()) / "pyrars"
    where.mkdir(parents=True, exist_ok=True)
    (where / "pyrars.lang").write_text(language())
    manager = GtkSource.LanguageManager.new()
    manager.set_search_path(
        [str(where), *GtkSource.LanguageManager.get_default().get_search_path()])
    return manager


class Page(Gtk.Box):
    """One file of the program, open."""

    __gtype_name__ = "PyrarsPage"

    def __init__(self, manager: GtkSource.LanguageManager, path: str | None = None,
                 text: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.path = path
        self.buffer = GtkSource.Buffer()
        self.buffer.set_language(manager.get_language(ID))
        self.buffer.set_highlight_syntax(True)
        self.buffer.set_highlight_matching_brackets(True)
        # Putting the file there is no change of the person's and must not be
        # undoable, or the first Ctrl+Z would empty the window. Nothing is needed
        # for that: `set_text` of GTK 4 is an irreversible action already, which
        # the test of it holds us to.
        self.buffer.set_text(text)
        self.buffer.set_modified(False)
        self.view = GtkSource.View(buffer=self.buffer, monospace=True)
        self.view.set_show_line_numbers(True)
        self.view.set_highlight_current_line(True)
        self.view.set_auto_indent(True)
        self.view.set_insert_spaces_instead_of_tabs(True)
        self.view.set_tab_width(8)
        self.view.set_left_margin(6)
        window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        window.set_child(self.view)
        self.append(window)

    @property
    def text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(),
                                    self.buffer.get_end_iter(), False)

    @property
    def modified(self) -> bool:
        return self.buffer.get_modified()

    def save(self, path: str | None = None) -> str:
        """Write the file. Answers with where it went; raises ValueError where
        there is nowhere to put it yet."""
        where = path or self.path
        if not where:
            raise ValueError("this file has never been saved: name it first")
        text = self.text
        Path(where).write_text(text if text.endswith("\n") or not text else text + "\n")
        self.path = where
        self.buffer.set_modified(False)
        return where


class Editor(Gtk.Box):
    """Every file that is open, and what is done to them."""

    __gtype_name__ = "PyrarsEditor"

    def __init__(self, folder: str | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.languages = languages(folder)
        self.tabs = Adw.TabView(vexpand=True)
        self.tabs.connect("notify::selected-page", lambda *gone: self.changed())
        self.watchers: list = []  # told whenever the tabs or their state change

        bar = Adw.TabBar(view=self.tabs, autohide=False)
        self.search = Search(self)
        self.append(bar)
        self.append(self.tabs)
        self.append(self.search)

    # ------------------------------------------------------------- the files

    def open(self, path: str) -> Adw.TabPage:
        """A file from the disk, or the one already open over it."""
        full = str(Path(path).resolve())
        for page in self.pages:
            if page.path and str(Path(page.path).resolve()) == full:
                self.tabs.set_selected_page(self.tabs.get_page(page))
                return self.tabs.get_page(page)
        return self.add(Path(path).read_text(), path)

    def add(self, text: str = "", path: str | None = None) -> Adw.TabPage:
        page = Page(self.languages, path, text)
        page.buffer.connect("modified-changed", lambda *gone: self.changed())
        tab = self.tabs.append(page)
        self._named(tab, page)
        self.tabs.set_selected_page(tab)
        self.changed()
        return tab

    def close(self, page: Page | None = None) -> None:
        chosen = self.tabs.get_page(page or self.page) if (page or self.page) else None
        if chosen is not None:
            self.tabs.close_page(chosen)
            self.changed()

    @property
    def pages(self) -> list[Page]:
        return [self.tabs.get_nth_page(index).get_child()
                for index in range(self.tabs.get_n_pages())]

    @property
    def page(self) -> Page | None:
        chosen = self.tabs.get_selected_page()
        return chosen.get_child() if chosen is not None else None

    @property
    def paths(self) -> list[str]:
        """The files that are on the disk, in the order of their tabs."""
        return [page.path for page in self.pages if page.path]

    @property
    def modified(self) -> bool:
        return any(page.modified for page in self.pages)

    def save(self, path: str | None = None) -> str | None:
        page = self.page
        return None if page is None else self._saved(page, path)

    def save_every_change(self) -> list[str]:
        """Write every file that has been changed, and answer with what was
        written. An assembler reads the disk, so this is what has to happen before
        a program is assembled."""
        return [self._saved(page) for page in self.pages if page.modified
                and page.path]

    def _saved(self, page: Page, path: str | None = None) -> str:
        where = page.save(path)
        self._named(self.tabs.get_page(page), page)
        self.changed()
        return where

    # ------------------------------------------------- what is done to a file

    def undo(self) -> None:
        if self.page is not None and self.page.buffer.get_can_undo():
            self.page.buffer.undo()

    def redo(self) -> None:
        if self.page is not None and self.page.buffer.get_can_redo():
            self.page.buffer.redo()

    def find(self) -> None:
        self.search.open()

    # ------------------------------------------------------------ the telling

    def changed(self) -> None:
        """Something about the files changed: their names are written again and
        whoever is watching is told."""
        for page in self.pages:
            self._named(self.tabs.get_page(page), page)
        for watcher in self.watchers:
            watcher()

    def _named(self, tab: Adw.TabPage, page: Page) -> None:
        tab.set_title(shown.tab_title(page.path, page.modified))
        tab.set_tooltip(shown.tab_about(page.path))


class Search(Gtk.SearchBar):
    """Finding and replacing, which GtkSourceView does; this is the bar over it."""

    __gtype_name__ = "PyrarsSearch"

    def __init__(self, editor: Editor) -> None:
        super().__init__()
        self.editor = editor
        self.settings = GtkSource.SearchSettings(wrap_around=True)
        self.context: GtkSource.SearchContext | None = None

        self.what = Gtk.SearchEntry(placeholder_text="Find", width_chars=24)
        self.what.connect("search-changed", lambda *gone: self._looking())
        self.what.connect("activate", lambda *gone: self.next())
        self.instead = Gtk.Entry(placeholder_text="Replace with", width_chars=24)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.append(self.what)
        box.append(_button("go-up-symbolic", "Previous", self.previous))
        box.append(_button("go-down-symbolic", "Next", self.next))
        box.append(self.instead)
        box.append(_button("edit-find-replace-symbolic", "Replace", self.replace))
        box.append(_labelled("All", "Replace every one of them", self.replace_all))
        self.set_child(box)
        self.connect_entry(self.what)

    def open(self) -> None:
        self.set_search_mode(True)
        self.what.grab_focus()

    def _looking(self) -> None:
        """What is typed in the entry, as it is typed."""
        self._ready()

    def _ready(self) -> bool:
        """The search context over the file being looked at, made from what the
        entry holds NOW.

        It is not made when the entry changes: a search entry tells of a change
        only after the typing has stopped for a moment, and somebody who types a
        word and presses Enter at once is not going to wait for that.
        """
        page = self.editor.page
        if page is None:
            self.context = None
            return False
        # An empty entry is no search: GtkSourceView finds nothing for it, which
        # is the answer anybody asking would want.
        self.settings.set_search_text(self.what.get_text())
        if self.context is None or self.context.get_buffer() is not page.buffer:
            self.context = GtkSource.SearchContext(buffer=page.buffer,
                                                   settings=self.settings)
        return True

    def next(self) -> bool:
        return self._moved(forward=True)

    def previous(self) -> bool:
        return self._moved(forward=False)

    def _moved(self, forward: bool) -> bool:
        if not self._ready():
            return False
        page = self.editor.page
        buffer = page.buffer
        place = buffer.get_iter_at_mark(buffer.get_insert())
        found, start, end, _ = (self.context.forward(place) if forward
                                else self.context.backward(place))
        if found:
            buffer.select_range(start, end)
            page.view.scroll_to_iter(start, 0.1, False, 0.0, 0.0)
        return found

    def replace(self) -> bool:
        """What is chosen, if it is what was looked for; otherwise the next one is
        found first, so that pressing Replace twice replaces two of them."""
        if not self._ready():
            return False
        buffer = self.editor.page.buffer
        # Nothing chosen comes back as nothing at all, not as a pair of places.
        chosen = buffer.get_selection_bounds()
        if (not chosen
                or buffer.get_text(*chosen, False) != self.what.get_text()):
            if not self.next():
                return False
            chosen = buffer.get_selection_bounds()
        self.context.replace(*chosen, self.instead.get_text(), -1)
        return True

    def replace_all(self) -> int:
        if not self._ready():
            return 0
        return self.context.replace_all(self.instead.get_text(), -1)


def _button(icon: str, about: str, doing) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=about)
    button.connect("clicked", lambda *gone: doing())
    return button


def _labelled(label: str, about: str, doing) -> Gtk.Button:
    button = Gtk.Button(label=label, tooltip_text=about)
    button.connect("clicked", lambda *gone: doing())
    return button
