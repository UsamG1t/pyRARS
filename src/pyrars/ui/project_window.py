"""The window that says what the program IS.

One file open in an editor is one program; several are several things somebody is
working on. A program made of several files is a PROJECT, and this is where that
is said - along with the width of the machine, the memory configuration and
whether pseudo-instructions are allowed, which are the other things that have to be
settled before a line can be assembled.

It edits a `pyrars.session.project.Project` and nothing else: what it answers with
is that record, and the window above it does the assembling. A project may be read
from a file and written to one, so that it can be kept beside the program.
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402 - after require_version

from pyrars.isa.memory import CONFIGS  # noqa: E402
from pyrars.session import project as projects  # noqa: E402
from pyrars.session.project import SUFFIX, Project  # noqa: E402
from pyrars.ui import shown  # noqa: E402

WIDTHS = ("32", "64")


class ProjectWindow(Adw.Window):
    """What a program is made of, and how it is assembled."""

    __gtype_name__ = "PyrarsProjectWindow"

    def __init__(self, project: Project | None, files=(), where: str = "",
                 settled=None, **kept) -> None:
        super().__init__(title="The program", modal=True, default_width=620,
                         default_height=560, **kept)
        self.settled = settled or (lambda project, where: None)
        self.where = where
        self.chosen: dict[str, Gtk.CheckButton] = {}  # is it part of the program
        self.main_of: dict[str, Gtk.CheckButton] = {}  # and is it the main file
        # Every file that could be part of the program: those open in the editor,
        # and those the project names already - a project may name a file nobody
        # has opened.
        self.files = list(dict.fromkeys([*files, *(project.paths if project else ())]))
        self.set_content(self._built(project))

    # ---------------------------------------------------------------- the shape

    def _built(self, project: Project | None) -> Gtk.Widget:
        whole = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.header_title = Adw.WindowTitle(title="The program",
                                            subtitle=_about(self.where))
        header.set_title_widget(self.header_title)
        whole.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.add(self._of_the_files(project))
        page.add(self._of_the_machine(project))
        whole.set_content(page)
        whole.add_bottom_bar(self._buttons())
        return whole

    def _of_the_files(self, project: Project | None) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="The files of the program",
            description="Everything ticked is assembled, one after another, with "
                        "the main file first. One file is the ordinary case; "
                        "several make one program of several pieces.")
        held = set(project.paths) if project is not None else set()
        main = project.paths[0] if project is not None and project.paths else ""
        first = None
        for path in self.files:
            row = Adw.ActionRow(title=shown.name_of(path), subtitle=path)
            ticked = Gtk.CheckButton(active=path in held or not held and not first)
            ticked.connect("toggled", lambda *gone: self._files_chosen())
            row.add_prefix(ticked)
            self.chosen[path] = ticked
            main_here = Gtk.CheckButton(group=first, active=path == main)
            main_here.set_tooltip_text("The main file: it is assembled first, so the "
                                       "program begins in it")
            row.add_suffix(main_here)
            row.set_activatable_widget(ticked)
            first = first or main_here
            self.main_of[path] = main_here
            group.add(row)
        if not self.files:
            group.add(Adw.ActionRow(title="No file is open",
                                    subtitle="Open one, and it can be part of the "
                                             "program"))
        return group

    def _of_the_machine(self, project: Project | None) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="How it is assembled",
            description="These are settled before a line of the program can be "
                        "read, so they belong to the program and not to a run of it.")
        self.width = Adw.ComboRow(title="Width of the machine",
                                  subtitle="RV32 or RV64",
                                  model=Gtk.StringList.new(list(WIDTHS)))
        self.width.set_selected(WIDTHS.index(str(project.xlen if project else 32)))
        group.add(self.width)

        self.config = Adw.ComboRow(
            title="Memory configuration",
            subtitle="Where the text, the data and the stack are",
            model=Gtk.StringList.new(list(CONFIGS)))
        self.config.set_selected(
            list(CONFIGS).index(project.mem_config if project else "Default"))
        self.config.connect("notify::selected", self._configuration_chosen)
        group.add(self.config)

        # What the name of a configuration MEANS. Three names on a chooser say
        # nothing about where a program will find itself; the addresses do, and
        # they are the names the assembler and the simulator use in their own
        # messages about an address.
        self.where_things_are = Adw.ExpanderRow(
            title="Where everything is",
            subtitle="The addresses this configuration puts the parts of the "
                     "memory at")
        self.said_of_the_memory: list[Adw.ActionRow] = []
        group.add(self.where_things_are)
        self._configuration_chosen()

        self.pseudo = Adw.SwitchRow(
            title="Pseudo-instructions",
            subtitle="li, la, mv and the rest, which the assembler writes out",
            active=project.pseudo if project else True)
        group.add(self.pseudo)
        return group

    def _buttons(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                      margin_top=8, margin_bottom=8, margin_start=8, margin_end=8)
        box.append(_button("Open a project…", self._opening))
        box.append(_button("Save as…", self._saving))
        self.says = Gtk.Label(hexpand=True, xalign=0.0, wrap=True)
        self.says.add_css_class("dim-label")
        box.append(self.says)
        box.append(_button("One file only", self._let_go))
        use = _button("Use this project", self._use)
        use.add_css_class("suggested-action")
        box.append(use)
        return box

    # --------------------------------------------------------------- what is said

    def _files_chosen(self) -> None:
        self.says.set_text("")

    def _configuration_chosen(self, *gone) -> None:
        """The addresses of the configuration now chosen, under the chooser."""
        for row in self.said_of_the_memory:
            self.where_things_are.remove(row)
        self.said_of_the_memory = []
        config = CONFIGS[list(CONFIGS)[self.config.get_selected()]]
        for name, address in shown.memory(config):
            row = Adw.ActionRow(title=name.replace("_", " "))
            said = Gtk.Label(label=address)
            said.add_css_class("monospace")
            said.add_css_class("dim-label")
            row.add_suffix(said)
            self.where_things_are.add_row(row)
            self.said_of_the_memory.append(row)

    def project_now(self) -> Project | None:
        """What is ticked, as a project; nothing where it cannot be one."""
        wanted = [path for path in self.files if self.chosen[path].get_active()]
        if not wanted:
            self.says.set_text("Tick the files the program is made of")
            return None
        main = next((path for path in wanted
                     if self.main_of[path].get_active()), wanted[0])
        folder = str(Path(self.where).parent if self.where
                     else Path(main).parent)
        try:
            return projects.of(wanted, folder=folder, main=main,
                               xlen=int(WIDTHS[self.width.get_selected()]),
                               mem_config=list(CONFIGS)[self.config.get_selected()],
                               pseudo=self.pseudo.get_active())
        except ValueError as problem:  # a project checks itself, whoever made it
            self.says.set_text(str(problem))
            return None

    def _use(self, *gone) -> None:
        project = self.project_now()
        if project is not None:
            self.settled(project, self.where)
            self.close()

    def _let_go(self, *gone) -> None:
        """No project: the file being looked at is the program, which is the
        ordinary way of working."""
        self.settled(None, "")
        self.close()

    # ------------------------------------------------------------ to and from a file

    def _opening(self, *gone) -> None:
        dialog = Gtk.FileDialog(title="Open a project")
        dialog.open(self, None, self._opened)

    def _opened(self, dialog, answer) -> None:
        try:
            file = dialog.open_finish(answer)
        except GLib.Error:
            return
        if file is None:
            return
        try:
            project = projects.read(file.get_path())
        except ValueError as problem:
            self.says.set_text(str(problem))
            return
        self.settled(project, file.get_path())
        self.close()

    def _saving(self, *gone) -> None:
        if self.project_now() is None:
            return
        dialog = Gtk.FileDialog(title="Write the project",
                                initial_name=_named(self.files))
        dialog.save(self, None, self._saved)

    def _saved(self, dialog, answer) -> None:
        try:
            file = dialog.save_finish(answer)
        except GLib.Error:
            return
        project = self.project_now()
        if file is None or project is None:
            return
        self.where = file.get_path()
        kept = project.save(self.where)
        self.settled(kept, self.where)
        self.close()


def _named(files) -> str:
    """What a project file is called when nobody has said: the name of the first
    file of the program, with the suffix of a project."""
    return (Path(files[0]).stem if files else "program") + SUFFIX


def _about(where: str) -> str:
    return shown.name_of(where) if where else "not kept in a file yet"


def _button(label: str, doing) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.connect("clicked", doing)
    return button
