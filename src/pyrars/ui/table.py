"""A table of rows of words, which is what nearly every view of the machine is.

One widget serves them all: the registers, the text segment, the data segment, the
labels, the frames. What goes in the rows is worked out by `ui/shown.py`, which
knows nothing of GTK; this is the part that puts them on the screen.
"""

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gio, GObject, Gtk  # noqa: E402 - after require_version

from pyrars.ui.shown import cell  # noqa: E402


class Row(GObject.Object):
    """One row: its cells, already written out as words."""

    __gtype_name__ = "PyrarsTableRow"

    def __init__(self, cells: tuple[str, ...]) -> None:
        super().__init__()
        self.cells = cells


class Table(Gtk.Stack):
    """A column for every title, a row for every row it is shown.

    A table with nothing in it says WHY it has nothing in it. An empty table
    answers two questions at once - is there nothing, or is this broken? - and
    only one of them is the one being asked.
    """

    __gtype_name__ = "PyrarsTable"

    def __init__(self, titles: tuple[str, ...], otherwise: str = "",
                 monospace: bool = True) -> None:
        super().__init__(hexpand=True, vexpand=True)
        self.titles = titles
        self.store = Gio.ListStore.new(Row)
        view = Gtk.ColumnView(model=Gtk.NoSelection(model=self.store),
                              show_column_separators=False,
                              show_row_separators=False)
        view.add_css_class("data-table")
        for index, title in enumerate(titles):
            view.append_column(self._column(title, index, monospace))
        window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        window.set_child(view)
        self.add_named(window, "rows")
        self.otherwise = Gtk.Label(label=otherwise, wrap=True)
        self.otherwise.add_css_class("dim-label")
        self.add_named(self.otherwise, "nothing")
        self.set_visible_child_name("nothing" if otherwise else "rows")

    def _column(self, title: str, index: int, monospace: bool) -> Gtk.ColumnViewColumn:
        made = Gtk.SignalListItemFactory()
        made.connect("setup", self._made, monospace)
        made.connect("bind", self._filled, index)
        return Gtk.ColumnViewColumn(title=title, factory=made,
                                    resizable=True, expand=index == len(self.titles) - 1)

    def _made(self, factory, item, monospace: bool) -> None:
        label = Gtk.Label(xalign=0.0, selectable=True)
        if monospace:
            label.add_css_class("monospace")
        item.set_child(label)

    def _filled(self, factory, item, index: int) -> None:
        item.get_child().set_text(cell(item.get_item().cells, index))

    def show(self, rows) -> None:
        """What the table holds from now on; where that is nothing, what it says
        instead."""
        self.store.remove_all()
        for cells in rows:
            self.store.append(Row(tuple(cells)))
        self.set_visible_child_name(
            "rows" if rows or not self.otherwise.get_text() else "nothing")

    def says(self, otherwise: str) -> None:
        """Change what it says when it holds nothing. One table may have nothing in
        it for more than one reason - a cache nobody asked for, and a cache asked
        for but not yet given to a machine - and the reason is the whole value of
        the words."""
        self.otherwise.set_label(otherwise)
        self.set_visible_child_name("nothing" if otherwise and not self.rows
                                    else "rows")

    @property
    def saying(self) -> str:
        """What is being shown in place of rows, where anything is."""
        return (self.otherwise.get_text()
                if self.get_visible_child_name() == "nothing" else "")

    @property
    def rows(self) -> list[tuple[str, ...]]:
        """What it holds, for whoever is asking - a test, mostly."""
        return [self.store.get_item(index).cells
                for index in range(self.store.get_n_items())]
