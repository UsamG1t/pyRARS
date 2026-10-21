"""What the window shows, worked out where no widget can be seen.

Everything in here turns what the session answers - or what the editor holds -
into the words and the rows that go on the screen, and imports no `gi`, so it is
tested and mutated like every other module of the project. The widgets ask it and
put the answer up.
"""

from dataclasses import dataclass
from pathlib import Path

UNTITLED = "Untitled"
CHANGED = "•"  # the dot that says a file has been changed and not yet saved


def tab_title(path: str | None, modified: bool = False) -> str:
    """What a tab of the editor says: the name of the file, and a dot while what
    is in it is not what is on the disk."""
    name = Path(path).name if path else UNTITLED
    return f"{name} {CHANGED}" if modified else name


def name_of(path: str) -> str:
    """A file by its name alone: a window says where it is in a tooltip, not in
    the middle of a sentence."""
    return Path(path).name


def tab_about(path: str | None) -> str:
    """What a tab says when the pointer rests on it: where the file really is."""
    return str(Path(path).resolve()) if path else "not saved anywhere yet"


def window_title(path: str | None, modified: bool = False,
                 project: str = "") -> str:
    """The title of the window: the file being worked on, the project it is part of
    where there is one, and the name of the tool after them.

    The project is named because it changes what Assemble does - one file, or
    several - and nothing else on the screen would say so.
    """
    said = [tab_title(path, modified)]
    if project:
        said.append(project)
    return " - ".join(said + ["pyRARS"])


def project_called(where: str, files: int) -> str:
    """What the program is called in the title, where it is worth calling anything.

    A project kept in a file is called by that file. One made in the window and
    never kept is called by what it holds - and a project of ONE file is called
    nothing at all, because it does to the program exactly what no project does,
    and a title that said so twice would be saying nothing.
    """
    if where:
        return name_of(where)
    return f"a project of {files} files" if files > 1 else ""


ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Problem:
    """One thing the assembler had to say about one line."""

    line: int
    kind: str  # "error" or "warning"
    message: str


def problems(diagnostics) -> tuple[dict[str, tuple[Problem, ...]], tuple[str, ...]]:
    """What the assembler said, by the file it said it about.

    A diagnostic that names no place belongs to no line and cannot be marked in
    the margin of anything; those come back on their own, for a window to say
    somewhere a person will see them.
    """
    found: dict[str, list[Problem]] = {}
    loose: list[str] = []
    for one in diagnostics:
        if one.loc is None:
            loose.append(one.message)
            continue
        found.setdefault(one.loc.file, []).append(
            Problem(one.loc.line, one.kind.lower(), one.message))
    return ({file: tuple(these) for file, these in found.items()}, tuple(loose))


def said(problems_of_a_line) -> str:
    """What the margin of one line says when the pointer rests on it."""
    return "\n".join(f"{one.kind}: {one.message}" for one in problems_of_a_line)


# ------------------------------------------------------- the views of the machine

from pyrars.values import value_text  # noqa: E402 - the shapes a value is written in

HERE = "▶"  # the row the machine stands on
BREAK = "●"  # a row the run stops before

REGISTERS = ("Name", "Number", "Value")
FLOATS = ("Name", "Number", "Bits", "As a number")
CONTROL = ("Name", "Number", "Value", "What it holds")
TEXT = ("", "Address", "Code", "Basic", "Source")
DATA = ("Address", "Directive", "Size", "Value", "As text")
LABELS = ("Name", "Address", "Reach")
FRAMES = ("Depth", "Called", "From", "Stack pointer")


def standing(shot) -> str:
    """Where the run is, in the one line above the registers."""
    said = [shot.state]
    if shot.place is not None:
        said.append(f"0x{shot.place.address:08x}")
        if shot.place.basic:
            said.append(shot.place.basic)
    said.append(f"{shot.instructions} carried out")
    if shot.back:
        said.append(f"{shot.back} to take back")
    if shot.stopped is not None:
        said.append(shot.stopped.reason)
    return "  |  ".join(said)


def cell(cells, index: int) -> str:
    """What goes in one column of one row. A row may be shorter than the table is
    wide - a place with no source line, a frame with no name - and a column of a
    table has to show something either way."""
    return cells[index] if 0 <= index < len(cells) else ""


def registers(values, form: str = "hex") -> tuple[tuple[str, ...], ...]:
    """The integer registers, as the rows of a table."""
    return tuple((one.name, f"x{one.number}", value_text(one.value, one.bits, form))
                 for one in values)


def floats(values, form: str = "hex") -> tuple[tuple[str, ...], ...]:
    """The floating point registers: the bits as they lie, and what they mean.

    The bits are always shown as bits, whatever format was chosen for the rest: a
    float read as a signed number says nothing to anybody.
    """
    return tuple((one.name, f"f{one.number}", value_text(one.value, 64, "hex"),
                  one.about) for one in values)


def control(values, form: str = "hex") -> tuple[tuple[str, ...], ...]:
    """The control and status registers, with their fields spelled out - which is
    what the "flags" of another machine would be (the entry of M8)."""
    return tuple((one.name, f"0x{one.number:03x}",
                  value_text(one.value, one.bits, form), one.about)
                 for one in values)


def text(entries, here: int | None = None, breaks=(), form: str = "hex"
         ) -> tuple[tuple[str, ...], ...]:
    """The text segment: every instruction of the program, with the one the machine
    stands on marked and the ones the run stops before marked as well."""
    stopping = set(breaks)
    rows = []
    for entry in entries:
        mark = HERE if entry.address == here else ""
        if entry.address in stopping:
            mark = BREAK + mark
        rows.append((mark, f"0x{entry.address:08x}",
                     value_text(entry.word, 32, form), entry.basic,
                     entry.source.strip()))
    return tuple(rows)


def data(items, form: str = "hex") -> tuple[tuple[str, ...], ...]:
    """The data segment, each thing as the directive that put it there wrote it."""
    return tuple((f"0x{item.address:08x}", item.directive, str(item.size),
                  " ".join(value_text(one, min(item.size, 4) * 8, form)
                           for one in item.values),
                  item.text) for item in items)


def labels(symbols) -> tuple[tuple[str, ...], ...]:
    return tuple((one.name, f"0x{one.address:08x}",
                  "global" if one.public else "local") for one in symbols)


def frames(found) -> tuple[tuple[str, ...], ...]:
    """The calls the run is inside - a GUESS from the convention (D21), which
    whoever shows it must say."""
    return tuple((str(one.depth), _place(one.called), _place(one.called_from),
                  "?" if one.sp is None else f"0x{one.sp:08x}") for one in found)


def _place(place) -> str:
    """A place of the program, as a row of a table shows it."""
    name = f" <{place.symbol}>" if place.symbol else ""
    return f"0x{place.address:08x}{name}"
