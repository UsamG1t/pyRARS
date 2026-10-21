"""The window that says what can be written in a program.

Everything the assembler takes, in one place a person can read: the instructions
with the operands they want, what each pseudo-instruction is written out as, the
directives, the registers and the names they answer to. All of it comes from
`ui/help.py`, which makes it out of the tables that do the assembling, so there is
nothing here to go stale and nothing borrowed from anybody.

The same words are shown where the pointer rests on one in the editor; this is for
looking something up when there is nothing to point at yet.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402 - after require_version

from pyrars.ui.help import About, catalogue, matches  # noqa: E402


class HelpWindow(Adw.Window):
    """Every word of the language, and what each of them is."""

    __gtype_name__ = "PyrarsHelpWindow"

    def __init__(self, xlen: int = 32, **kept) -> None:
        super().__init__(title="What can be written", default_width=720,
                         default_height=680, **kept)
        self.words = catalogue(xlen)
        self.rows: dict[Gtk.ListBoxRow, About] = {}
        self.looking = ""
        self.set_content(self._built(xlen))

    def _built(self, xlen: int) -> Gtk.Widget:
        whole = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="What can be written",
            subtitle=f"everything a {xlen}-bit machine takes, "
                     f"{len(self.words)} words in all"))
        whole.add_top_bar(header)

        self.search = Gtk.SearchEntry(placeholder_text="A word, or anything said "
                                                       "about one", hexpand=True)
        self.search.connect("search-changed", self._looked_for)
        bar = Gtk.Box(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        bar.append(self.search)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.add_css_class("boxed-list")
        self.list.set_filter_func(self._wanted)
        self.list.set_header_func(self._heading)
        for one in self.words:
            row = Gtk.ListBoxRow(child=_told(one), activatable=False)
            self.rows[row] = one
            self.list.append(row)

        window = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        window.set_child(self.list)
        self.nothing = Gtk.Label(label="No word of the language says that")
        self.nothing.add_css_class("dim-label")
        self.shown = Gtk.Stack()
        self.shown.add_named(window, "words")
        self.shown.add_named(self.nothing, "nothing")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(bar)
        box.append(self.shown)
        whole.set_content(box)
        return whole

    # ------------------------------------------------------------- the looking

    def look_for(self, like: str) -> int:
        """Show only what answers to this; answers with how many that is."""
        self.looking = like
        self.list.invalidate_filter()
        self.list.invalidate_headers()
        many = sum(1 for one in self.words if matches(one, like))
        self.shown.set_visible_child_name("words" if many else "nothing")
        return many

    def _looked_for(self, entry) -> None:
        self.look_for(entry.get_text())

    def _wanted(self, row: Gtk.ListBoxRow) -> bool:
        return matches(self.rows[row], self.looking)

    def _heading(self, row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        """The kind of word, over the first of its kind that is being shown."""
        kind = self.rows[row].kind
        if before is not None and self.rows[before].kind == kind:
            row.set_header(None)
            return
        label = Gtk.Label(label=kind.capitalize() + "s", xalign=0.0,
                          margin_top=12, margin_bottom=4, margin_start=4)
        label.add_css_class("heading")
        row.set_header(label)


def _told(one: About) -> Gtk.Widget:
    """One word, as a row of the list shows it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                  margin_top=8, margin_bottom=8, margin_start=10, margin_end=10)
    heading = Gtk.Label(xalign=0.0, selectable=True)
    heading.set_markup(f"<b>{GLib.markup_escape_text(one.word)}</b>")
    heading.add_css_class("monospace")
    box.append(heading)
    # Three lines that must not run into one another: what KIND of word it is,
    # which is read once; what it DOES, which is what the looking was for; and how
    # it is WRITTEN, which is copied out of here into a program.
    about = Gtk.Label(label=one.about, xalign=0.0, wrap=True)
    about.add_css_class("dim-label")
    about.add_css_class("caption")
    box.append(about)
    if one.means:
        means = Gtk.Label(label=one.means, xalign=0.0, wrap=True, selectable=True)
        means.add_css_class("accent")
        means.add_css_class("heading")
        box.append(means)
    for index, form in enumerate(one.forms):
        becomes = one.becomes[index] if index < len(one.becomes) else ""
        line = Gtk.Label(xalign=0.0, selectable=True)
        line.set_markup(GLib.markup_escape_text(form)
                        + (f"   → <i>{GLib.markup_escape_text(becomes)}</i>"
                           if becomes else ""))
        line.add_css_class("monospace")
        box.append(line)
    return box
