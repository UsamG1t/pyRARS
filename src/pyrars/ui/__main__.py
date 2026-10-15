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
    parser.add_argument("-x", "--xlen", type=int, choices=(32, 64), default=32,
                        help="width of the registers (default: 32)")
    arguments = parser.parse_args(argv)
    try:
        project = _opened(arguments)
    except ValueError as problem:
        print(problem, file=sys.stderr)
        return 1
    text = "\n".join(Path(path).read_text() for path in project.paths) if project else ""
    return Application(project=project, text=text).run([])


def _opened(arguments) -> projects.Project | None:
    """The project the window opens with, or nothing at all."""
    if arguments.project is not None:
        if arguments.files:
            raise ValueError("--project settles which files the program is made of, "
                             "so they cannot be named as well")
        return projects.read(arguments.project)
    if not arguments.files:
        return None
    return projects.of(arguments.files, folder=str(Path(arguments.files[0]).parent),
                       xlen=arguments.xlen)


if __name__ == "__main__":
    sys.exit(main())
