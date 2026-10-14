"""What a program IS: the files it is made of, and how they are assembled.

A project answers "what am I working on": the files of one program, which of them
is its main file, and the three things that must be settled before a line of it can
be assembled - the width of the machine, the memory configuration, and whether
pseudo-instructions are allowed. It is kept as JSON beside the program, by
convention as `<name>.pyrars.json`, so that a person can read it, a repository can
hold it and somebody else can be sent it.

It says nothing about HOW to run the program: no devices, no models, no
breakpoints, no window, no speed. Those are settings of a RUN and belong to M8
(the architect's decision of 2026-10-13, variant A). A project outlives any one
run of it, which is why the two are kept apart.

The paths are kept relative to the folder of the project file, so that a project
moves with its files; saving one somewhere else puts its paths right for the new
place. An absolute path is kept absolute, and says plainly that the project is
tied to one machine.
"""

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from pyrars.asm.assembler import Options
from pyrars.isa.memory import CONFIGS

# What a project file may hold, which is also the order it is written in.
SETTINGS = ("files", "main", "xlen", "mem_config", "pseudo")
SUFFIX = ".pyrars.json"  # the convention, not a rule: any name may be read


@dataclass(frozen=True, slots=True)
class Project:
    """One program, as a project file describes it.

    A project is checked when it is made, however it was made, so one that exists
    at all can be assembled; what cannot be checked here is whether its files are
    on the disk, which is the assembler's to report and a window's to show.
    """

    files: tuple[str, ...] = ()
    main: str = ""  # which of the files is assembled first; the first of them when empty
    xlen: int = 32
    mem_config: str = "Default"
    pseudo: bool = True
    folder: str = ""  # where the project file lies; not part of what is written

    def __post_init__(self) -> None:
        if self.xlen not in (32, 64):
            raise ValueError(f"{self.xlen}: a machine is 32 or 64 bits wide")
        if self.mem_config not in CONFIGS:
            raise ValueError(f'"{self.mem_config}": no memory configuration of that '
                             f'name; they are {", ".join(CONFIGS)}')
        if self.main and self.main not in self.files:
            raise ValueError(f'"{self.main}": the main file is not one of the files '
                             "of the project")
        seen = [name for name in self.files if self.files.count(name) > 1]
        if seen:
            raise ValueError(f'"{seen[0]}": a project holds a file once')

    @property
    def ordered(self) -> tuple[str, ...]:
        """The files as they are assembled: the main one first, the rest after it in
        the order the project holds them. Our assembler lays one file after another,
        so the main file first is what puts the beginning of the program at the base
        of the text."""
        if not self.main:
            return self.files
        return (self.main,) + tuple(name for name in self.files if name != self.main)

    @property
    def paths(self) -> tuple[str, ...]:
        """The files as the assembler is given them: in order, and where they are."""
        return tuple(self._where(name) for name in self.ordered)

    def options(self) -> Options:
        """What a project settles for the assembler. What it does NOT settle stays
        at its own default: whether a warning is an error and whether a run begins
        at `main` are choices of the person at the time, not of the program."""
        return Options(xlen=self.xlen, config=CONFIGS[self.mem_config],
                       pseudo=self.pseudo)

    def with_files(self, paths: Sequence[str], main: str = "") -> "Project":
        """The same project over other files, each put relative to its folder."""
        files = tuple(_relative(path, self.folder) for path in paths)
        return replace(self, files=files,
                       main=_relative(main, self.folder) if main else "")

    def written(self) -> str:
        """The project as a project file holds it."""
        held = {"files": list(self.files), "main": self.main, "xlen": self.xlen,
                "mem_config": self.mem_config, "pseudo": self.pseudo}
        return json.dumps(held, indent=2) + "\n"

    def save(self, path: str) -> "Project":
        """Write the project, and answer with it as it now lies on the disk.

        Saving it in another folder puts its paths right for that folder, so a
        project that is moved does not lose its files; the answer is the project
        the file now holds, which is what a window keeps from then on.
        """
        folder = str(Path(path).parent)
        moved = replace(self, files=tuple(_relative(self._where(name), folder)
                                          for name in self.files),
                        main=_relative(self._where(self.main), folder)
                        if self.main else "", folder=folder)
        Path(path).write_text(moved.written())
        return moved

    def _where(self, name: str) -> str:
        """One file of the project, where it really is. An absolute path comes out
        as it went in, because joining a folder to one leaves it alone."""
        if not self.folder:
            return name
        return os.path.normpath(os.path.join(self.folder, name))


def read(path: str) -> Project:
    """A project from its file. Raises ValueError with one message, for a window to
    show and a command line to print."""
    try:
        text = Path(path).read_text()
    except OSError as problem:
        raise ValueError(f"{path}: {problem.strerror or problem}") from None
    try:
        held = json.loads(text)
    except json.JSONDecodeError as problem:
        raise ValueError(f"{path}: {problem.msg}, line {problem.lineno}") from None
    if not isinstance(held, dict):
        raise ValueError(f"{path}: a project is a JSON object holding "
                         f"{', '.join(SETTINGS)}")
    for name in held:
        if name not in SETTINGS:
            raise ValueError(f'{path}: "{name}" is no setting of a project; they are '
                             f'{", ".join(SETTINGS)}')
    # Every "wrong" of a project says the same thing - what the setting is - and
    # the file it was read from is put in front of it once, here.
    try:
        return Project(files=_names(held), main=_string(held, "main", ""),
                       xlen=_whole(held, "xlen", 32),
                       mem_config=_string(held, "mem_config", "Default"),
                       pseudo=_yes_or_no(held, "pseudo", True),
                       folder=str(Path(path).parent))
    except ValueError as problem:
        raise ValueError(f"{path}: {problem}") from None


def of(paths: Sequence[str], folder: str = "", main: str = "", xlen: int = 32,
       mem_config: str = "Default", pseudo: bool = True) -> Project:
    """A project over files that are already somewhere, for whoever is making one:
    the paths are put relative to the folder the project will live in."""
    return Project(files=tuple(_relative(path, folder) for path in paths),
                   main=_relative(main, folder) if main else "", xlen=xlen,
                   mem_config=mem_config, pseudo=pseudo, folder=folder)


def _relative(path: str, folder: str) -> str:
    """A path as a project holds it: relative to its folder where that can be said
    at all, and absolute where it cannot - a file on another root of the file
    system has no way back to the folder."""
    if not folder:
        return path
    try:
        return os.path.relpath(path, folder)
    except ValueError:  # another root: there is no relative way from here to there
        return path


def _names(held: dict) -> tuple[str, ...]:
    value = held.get("files", [])
    if not isinstance(value, list) or any(not isinstance(one, str) for one in value):
        raise ValueError("the files of a project are a list of names")
    return tuple(value)


def _string(held: dict, name: str, default: str) -> str:
    value = held.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f'"{name}" of a project is a name')
    return value


def _whole(held: dict, name: str, default: int) -> int:
    value = held.get(name, default)
    # A bool is a number in Python and is not one here: `"xlen": true` is a mistake.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f'"{name}" of a project is a whole number')
    return value


def _yes_or_no(held: dict, name: str, default: bool) -> bool:
    value = held.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f'"{name}" of a project is true or false')
    return value
