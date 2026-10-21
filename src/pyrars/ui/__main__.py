"""`python -m pyrars.ui [--project FILE | FILE...]`.

The window has its own way in and is not a subcommand of `pyrars`: the command line
must run where there is no window system at all, so it may not import this package
(INV-L2).
"""

import argparse
import sys
from pathlib import Path

from pyrars.session import project as projects
from pyrars.ui.app import Application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pyrars.ui",
                                     description="pyRARS in a window")
    parser.add_argument("files", nargs="*", help="source files of one program")
    parser.add_argument("--project", metavar="FILE",
                        help="open a project file instead of naming the files")

    arguments = parser.parse_args(argv)
    try:
        project, files = _opened(arguments)
    except ValueError as problem:
        print(problem, file=sys.stderr)
        return 1
    return Application(project=project, files=files,
                       where=arguments.project or "").run([])


def _opened(arguments):
    """What the window opens with: a project, or files that are only open.

    Files NAMED on the line are files to work on, not a program in several pieces:
    a program of several files is a project, and saying so is what `--project` and
    the project window are for (the architect, 2026-10-21).
    """
    if arguments.project is not None:
        if arguments.files:
            raise ValueError("--project settles which files the program is made of, "
                             "so they cannot be named as well")
        project = projects.read(arguments.project)
        return project, tuple(project.paths)
    return None, tuple(arguments.files)


if __name__ == "__main__":
    sys.exit(main())
