"""The window: the one part of pyRARS that knows anything about GTK.

Nothing below this package imports `gi`, and nothing here holds any logic about a
run: the window asks the controller of `pyrars.session.control`, which owns the
thread that owns the machine, and shows the data it is handed back. The console
debugger of `pyrars.console` shows the SAME data its own way, and neither front
end knows anything the other does not.

Inside the package the line is drawn again. What turns the data of a session into
what is shown - which actions are possible, the rows of a table, the shape of a
value, the fields of a control register - lives in modules that import no `gi` at
all and are tested like every other module of the project. The widgets themselves
stay thin: they put what those modules work out on the screen, and their tests
carry the marker `ui`, which skips where there is no GTK and no display.

The way in is `python -m pyrars.ui`, not a subcommand of `pyrars`: the command line
must run where there is no window system at all, and so it may not import this
package (INV-L2).
"""
