"""The window that says how a program is RUN.

The other half of "what am I working on": the project says what the program IS,
and this says what the machine is GIVEN besides it - which devices are attached,
whether the run is counted, whether a cache and a pipeline are modelled and how
each of them is built.

Nothing of what can be set is written here. `session/settings.py` reads the
options off the models and the devices themselves, and `ui/meanings.py` says what
each of them means; this window turns that description into rows - a number, a yes
or no, one of a few words - so a model that gains an option gains a row here the
same day and nobody has to come back for it.

It edits a `pyrars.session.settings.Settings` and nothing else. What it answers
with is that record; the window above it keeps it, writes it where a desktop keeps
what belongs to a person, and gives it to the machine the next time a program is
assembled - which is the one thing this window has to SAY, because a change that
waits for an Assemble looks like a change that did nothing.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402 - after require_version

from pyrars.devices import DEVICES  # noqa: E402
from pyrars.session import settings as runs  # noqa: E402
from pyrars.ui import meanings  # noqa: E402

WAITS = ("What is set here is given to the machine when the program is assembled, "
         "so a program that is already open must be assembled again")


class Row:
    """One option, and the widget that asks for it.

    One class for all four kinds, because everything above it wants the same two
    things of a row: put it in a group, and say what it holds now.
    """

    def __init__(self, what: str, option: runs.Option, value: object) -> None:
        self.option = option
        title = option.name.replace("_", " ")
        about = meanings.of_a_setting(f"{what}.{option.name}")
        if option.kind == runs.YES_OR_NO:
            self.widget = Adw.SwitchRow(title=title.capitalize(), subtitle=about,
                                        active=bool(value))
        elif option.kind == runs.WHOLE:
            self.widget = Adw.SpinRow.new_with_range(0, 1 << 20, 1)
            self.widget.set_title(title.capitalize())
            self.widget.set_subtitle(about)
            self.widget.set_value(int(value))
        elif option.kind == runs.AMONG:
            self.widget = Adw.ComboRow(
                title=title.capitalize(), subtitle=about,
                model=Gtk.StringList.new(list(option.among)))
            self.widget.set_selected(option.among.index(str(value))
                                     if str(value) in option.among else 0)
        else:
            self.widget = Adw.EntryRow(title=title.capitalize(), text=str(value))

    def value(self) -> object:
        """What the row holds now, of the kind the option takes."""
        if self.option.kind == runs.YES_OR_NO:
            return self.widget.get_active()
        if self.option.kind == runs.WHOLE:
            return int(self.widget.get_value())
        if self.option.kind == runs.AMONG:
            return self.option.among[self.widget.get_selected()]
        return self.widget.get_text()


class SettingsWindow(Adw.Window):
    """How a program is run: the devices, the models and the counting."""

    __gtype_name__ = "PyrarsSettingsWindow"

    def __init__(self, settings: runs.Settings | None = None, settled=None,
                 **kept) -> None:
        super().__init__(title="The run", modal=True, default_width=680,
                         default_height=680, **kept)
        self.settings = settings or runs.Settings()
        self.settled = settled or (lambda settings: None)
        self.rows: dict[str, dict[str, Row]] = {}  # what -> option -> its row
        self.wanted: dict[str, Adw.ExpanderRow | Adw.SwitchRow] = {}
        self.set_content(self._built())

    # ---------------------------------------------------------------- the shape

    def _built(self) -> Gtk.Widget:
        whole = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="The run", subtitle=WAITS))
        whole.add_top_bar(header)
        page = Adw.PreferencesPage()
        page.add(self._of_the_counting())
        page.add(self._of_the_cache())
        page.add(self._of_the_pipeline())
        page.add(self._of_the_devices())
        whole.set_content(page)
        whole.add_bottom_bar(self._buttons())
        return whole

    def _of_the_counting(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Counting the run", description=WAITS)
        self.statistics = Adw.SwitchRow(title="Count what the run is made of",
                                        subtitle=meanings.of_a_setting("statistics"),
                                        active=self.settings.statistics)
        group.add(self.statistics)
        return group

    def _of_the_cache(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="The cache",
                                     description=meanings.of_a_setting("cache"))
        group.add(self._expanding("cache", "A cache of the data",
                                  self.settings.cache))
        self.fetches = Adw.SwitchRow(title="The instructions reach it",
                                     subtitle=meanings.of_a_setting("fetches"),
                                     active=self.settings.fetches)
        group.add(self.fetches)
        group.add(self._expanding("instructions", "A cache of the instructions",
                                  self.settings.instructions,
                                  about=meanings.of_a_setting("instructions"),
                                  options_of="cache"))
        return group

    def _of_the_pipeline(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="The pipeline",
                                     description=meanings.of_a_setting("pipeline"))
        group.add(self._expanding("pipeline", "A model of the time",
                                  self.settings.pipeline))
        group.add(self._expanding("guesser", "How a branch is guessed at",
                                  self.settings.guesser, always=True,
                                  about=meanings.of_a_setting("guesser")))
        return group

    def _of_the_devices(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="The devices",
            description="What is attached to the machine. A device answers at an "
                        "address of its own in the area of the devices, and a "
                        "program talks to it by reading and writing there.")
        for name in sorted(DEVICES):
            group.add(self._expanding(name, name, self.settings.devices.get(name),
                                      about=meanings.of_a_setting(name)))
        return group

    def _expanding(self, what: str, title: str, asked: dict | None,
                   about: str = "", options_of: str = "", always: bool = False):
        """One thing that may be wanted, with what can be asked of it inside it.

        A thing with nothing to ask about - the halt register, the digital lab - is
        a switch and no more; `always` is for the one thing that is not wanted or
        unwanted at all (how a branch is guessed at belongs to the pipeline, and is
        only ever read when there is one).
        """
        options = runs.options_of(options_of or what)
        if not options:
            row = Adw.SwitchRow(title=title.capitalize(), subtitle=about,
                                active=asked is not None)
            self.wanted[what] = row
            return row
        row = Adw.ExpanderRow(title=title.capitalize(),
                              subtitle=about or meanings.of_a_setting(what))
        if not always:
            row.set_show_enable_switch(True)
            row.set_enable_expansion(asked is not None)
        self.wanted[what] = row
        self.rows[what] = {}
        held = asked or {}
        for option in options:
            one = Row(options_of or what, option,
                      held.get(option.name, option.default))
            self.rows[what][option.name] = one
            row.add_row(one.widget)
        return row

    def _buttons(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        box.append(_button("As it comes", self._let_go))
        self.says = Gtk.Label(hexpand=True, xalign=0.0, wrap=True)
        self.says.add_css_class("dim-label")
        box.append(self.says)
        use = _button("Run it this way", self._use)
        use.add_css_class("suggested-action")
        box.append(use)
        return box

    # --------------------------------------------------------------- what is said

    def settings_now(self) -> runs.Settings:
        """What the window holds, as the settings of a run."""
        return runs.Settings(
            statistics=self.statistics.get_active(),
            cache=self._asked_of("cache"),
            fetches=self.fetches.get_active(),
            instructions=self._asked_of("instructions"),
            pipeline=self._asked_of("pipeline"),
            guesser=self._held_of("guesser"),
            devices={name: self._held_of(name) for name in sorted(DEVICES)
                     if self._is_wanted(name)})

    def _asked_of(self, what: str) -> dict | None:
        """What was asked of a thing, or nothing at all where it is not wanted."""
        return self._held_of(what) if self._is_wanted(what) else None

    def _held_of(self, what: str) -> dict:
        return {name: row.value() for name, row in self.rows.get(what, {}).items()}

    def _is_wanted(self, what: str) -> bool:
        row = self.wanted[what]
        if isinstance(row, Adw.ExpanderRow):
            return row.get_enable_expansion()
        return row.get_active()

    def _use(self, *gone) -> None:
        """Use these settings - if a machine can be built from them at all.

        What cannot be built is said HERE, beside the rows that say it, and not in
        the messages of a window somebody would have to go and look at.
        """
        settings = self.settings_now()
        try:
            runs.world(settings)
        except ValueError as problem:
            self.says.set_text(str(problem))
            return
        self.settled(settings)
        self.close()

    def _let_go(self, *gone) -> None:
        """Everything as it comes: nothing modelled, nothing attached, the run
        counted."""
        self.settled(runs.Settings())
        self.close()


def _button(label: str, doing) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.connect("clicked", doing)
    return button
