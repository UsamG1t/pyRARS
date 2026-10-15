"""The application: one window, and the keys that reach its actions."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402 - after require_version

from pyrars.session.project import Project  # noqa: E402
from pyrars.ui import actions  # noqa: E402
from pyrars.ui.window import Window  # noqa: E402

NAME = "org.pyrars.Pyrars"


class Application(Adw.Application):
    """What holds the window, the actions and their keys together."""

    def __init__(self, project: Project | None = None,
                 files: tuple[str, ...] = ()) -> None:
        super().__init__(application_id=NAME, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.project = project
        self.files = files
        self.window: Window | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # Every action of `ui/actions.py` becomes an action of the application, so
        # that a key reaches it wherever the pointer happens to be.
        for action in actions.ACTIONS + actions.FILES:
            doing = Gio.SimpleAction.new(action.name, None)
            doing.connect("activate", self._asked, action.name)
            self.add_action(doing)
            self.set_accels_for_action(f"app.{action.name}", [action.keys])
        quitting = Gio.SimpleAction.new("quit", None)
        quitting.connect("activate", lambda *gone: self.quit())
        self.add_action(quitting)
        self.set_accels_for_action("app.quit", ["<Primary>q"])

    def do_activate(self) -> None:
        if self.window is None:
            self.window = Window(application=self, project=self.project,
                                 files=self.files)
            self.window.connect("close-request", self._closing)
        self.window.present()

    def _asked(self, action, parameter, name: str) -> None:
        if self.window is not None:
            self.window.do(name)

    def _closing(self, window) -> bool:
        window.close_up()
        return False  # and then it really closes
