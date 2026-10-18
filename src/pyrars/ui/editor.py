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

from gi.repository import Adw, Gio, GLib, GObject, Gtk, GtkSource  # noqa: E402

from pyrars.ui import completions, shown  # noqa: E402
from pyrars.ui.help import about  # noqa: E402
from pyrars.ui.highlighting import ID, language  # noqa: E402

# What the margin of the editor can hold, and what each of them looks like. A
# breakpoint and the place the machine stands at are OURS; the other two are what
# the assembler said about the line.
MARKS = {
    shown.ERROR: ("dialog-error-symbolic", 30),
    shown.WARNING: ("dialog-warning-symbolic", 20),
    "breakpoint": ("media-record-symbolic", 10),
    "here": ("go-next-symbolic", 40),
}


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
        self.view.set_show_line_marks(True)
        # What each mark says, by its kind and its line. It is kept HERE and not on
        # the mark: a mark fetched out of the buffer again is a new Python object
        # every time, and anything hung on the old one is gone.
        self.says: dict[tuple[str, int], str] = {}
        for category, (icon, priority) in MARKS.items():
            look = GtkSource.MarkAttributes(icon_name=icon)
            look.connect("query-tooltip-markup", self._said_of_a_mark)
            self.view.set_mark_attributes(category, look, priority)
        # What a word is, where the pointer rests on one.
        self.view.set_has_tooltip(True)
        self.view.connect("query-tooltip", self._about_a_word)
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

    # ------------------------------------------------------------- the margin

    def mark(self, category: str, line: int, says: str = "") -> None:
        """Put a mark in the margin beside a line, counted from one as a person
        counts."""
        place = self.buffer.get_iter_at_line(max(line - 1, 0))[1]
        self.buffer.create_source_mark(None, category, place)
        if says:
            self.says[(category, line)] = says

    def unmark(self, category: str) -> None:
        start, end = self.buffer.get_bounds()
        self.buffer.remove_source_marks(start, end, category)
        self.says = {where: what for where, what in self.says.items()
                     if where[0] != category}

    def _said_of_a_mark(self, attributes, mark) -> str:
        where = (mark.get_category(),
                 self.buffer.get_iter_at_mark(mark).get_line() + 1)
        return GLib.markup_escape_text(self.says.get(where, ""))

    def marked(self, category: str) -> list[int]:
        """The lines that carry a mark of this kind, counted from one."""
        found, place = [], self.buffer.get_start_iter()
        while True:
            if self.buffer.get_source_marks_at_iter(place, category):
                found.append(place.get_line() + 1)
            if not place.forward_line():
                break
        return found

    def toggle(self, line: int, category: str = "breakpoint") -> bool:
        """Put a mark where there is none, take it off where there is one; answers
        with whether there is one now."""
        if line in self.marked(category):
            place = self.buffer.get_iter_at_line(max(line - 1, 0))[1]
            after = place.copy()
            after.forward_line()
            self.buffer.remove_source_marks(place, after, category)
            return False
        self.mark(category, line)
        return True

    def _about_a_word(self, view, x: int, y: int, keyboard: bool,
                      tooltip: Gtk.Tooltip) -> bool:
        """What the word under the pointer is, from the tables of the assembler."""
        if keyboard:
            return False
        where = view.window_to_buffer_coords(Gtk.TextWindowType.TEXT, x, y)
        found, place = view.get_iter_at_location(where[1], where[2])
        if not found:
            return False
        one = about(_word_at(place))
        if one is None:
            return False
        lines = [f"<b>{GLib.markup_escape_text(one.word)}</b>  <i>{one.kind}</i>",
                 GLib.markup_escape_text(one.about)]
        for index, form in enumerate(one.forms):
            becomes = one.becomes[index] if index < len(one.becomes) else ""
            lines.append(GLib.markup_escape_text(
                f"{form}" + (f"   \u2192 {becomes}" if becomes else "")))
        tooltip.set_markup("\n".join(lines))
        return True

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
        self.marked: list = []  # told whenever a breakpoint is put on or taken off
        self.labels: tuple[str, ...] = ()  # the names of the program, for the words

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
        page.view.get_completion().add_provider(Words(lambda: self.labels))
        page.view.connect("line-mark-activated", self._gutter)
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

    # ----------------------------------------------------- what is in the margin

    def _gutter(self, view, place, button, state, clicks) -> None:
        """The margin was clicked: a breakpoint goes on or comes off that line."""
        page = next((one for one in self.pages if one.view is view), None)
        if page is not None:
            self.toggle_breakpoint(page, place.get_line() + 1)

    def toggle_breakpoint(self, page: Page, line: int) -> bool:
        """Put a breakpoint on a line or take it off, and tell whoever is watching
        - which is the only way the machine hears of it."""
        on = page.toggle(line)
        for watcher in self.marked:
            watcher(page, line, on)
        return on

    def breakpoints(self) -> list[tuple[str, int]]:
        """Every breakpoint the person has put in, as a file and a line."""
        return [(page.path, line) for page in self.pages if page.path
                for line in page.marked("breakpoint")]

    def problems(self, by_file: dict) -> None:
        """What the assembler said, into the margins it was said about."""
        for page in self.pages:
            page.unmark(shown.ERROR)
            page.unmark(shown.WARNING)
            for one in by_file.get(page.path, ()):
                page.mark(one.kind, one.line, one.message)

    def here(self, path: str | None, line: int) -> None:
        """Where the machine stands, in the margin of the right file."""
        for page in self.pages:
            page.unmark("here")
        if not path:
            return
        for page in self.pages:
            if page.path == path:
                page.mark("here", line)
                self.tabs.set_selected_page(self.tabs.get_page(page))
                page.view.scroll_to_iter(
                    page.buffer.get_iter_at_line(max(line - 1, 0))[1],
                    0.2, False, 0.0, 0.0)

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


class Word(GObject.Object, GtkSource.CompletionProposal):
    """One word the editor offers."""

    __gtype_name__ = "PyrarsWord"

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class Words(GObject.Object, GtkSource.CompletionProvider):
    """What the editor offers while a line is being typed.

    WHICH words those are is worked out by `ui/completions.py`, which knows
    nothing of GTK; this is the part that hands them over and puts the chosen one
    in. The names a program gives things come from whoever built the editor, since
    they change with every assembly.
    """

    __gtype_name__ = "PyrarsWords"

    def __init__(self, labels=None) -> None:
        super().__init__()
        self.labels = labels if labels is not None else (lambda: ())

    def do_get_title(self) -> str:
        return "pyRARS"

    def do_populate_async(self, context, cancellable, callback, data=None) -> None:
        task = Gio.Task.new(self, cancellable, callback, data)
        store = Gio.ListStore.new(Word)
        for text in self.offered(context):
            store.append(Word(text))
        task.return_value(store)

    def do_populate_finish(self, result):
        return result.propagate_value().value

    def offered(self, context) -> tuple[str, ...]:
        """The words for where the typing is."""
        buffer = context.get_buffer()
        place = buffer.get_iter_at_mark(buffer.get_insert())
        line = place.copy()
        line.set_line_offset(0)
        return completions.words(line.get_text(place), labels=self.labels())

    def do_display(self, context, proposal, cell) -> None:
        if cell.get_column() == GtkSource.CompletionColumn.TYPED_TEXT:
            cell.set_text(proposal.text)

    def do_activate(self, context, proposal) -> None:
        """Put the word in place of what was typed of it."""
        buffer = context.get_buffer()
        found, start, end = context.get_bounds()
        buffer.begin_user_action()
        if found:
            buffer.delete(start, end)
        buffer.insert(start, proposal.text)
        buffer.end_user_action()


def _word_at(place) -> str:
    """The whole word the place is inside, as a program writes words."""
    start = place.copy()
    while not start.starts_line() and _of_a_word(start.copy(), back=True):
        start.backward_char()
    end = place.copy()
    while not end.ends_line() and _of_a_word(end.copy()):
        end.forward_char()
    return start.get_text(end)


def _of_a_word(place, back: bool = False) -> bool:
    if back:
        place.backward_char()
    letter = place.get_char()
    return bool(letter) and (letter.isalnum() or letter in "_.$")


def _button(icon: str, about: str, doing) -> Gtk.Button:
    button = Gtk.Button(icon_name=icon, tooltip_text=about)
    button.connect("clicked", lambda *gone: doing())
    return button


def _labelled(label: str, about: str, doing) -> Gtk.Button:
    button = Gtk.Button(label=label, tooltip_text=about)
    button.connect("clicked", lambda *gone: doing())
    return button
