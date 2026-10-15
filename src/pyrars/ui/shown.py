"""What the window shows, worked out where no widget can be seen.

Everything in here turns what the session answers - or what the editor holds -
into the words and the rows that go on the screen, and imports no `gi`, so it is
tested and mutated like every other module of the project. The widgets ask it and
put the answer up.
"""

from pathlib import Path

UNTITLED = "Untitled"
CHANGED = "•"  # the dot that says a file has been changed and not yet saved


def tab_title(path: str | None, modified: bool = False) -> str:
    """What a tab of the editor says: the name of the file, and a dot while what
    is in it is not what is on the disk."""
    name = Path(path).name if path else UNTITLED
    return f"{name} {CHANGED}" if modified else name


def tab_about(path: str | None) -> str:
    """What a tab says when the pointer rests on it: where the file really is."""
    return str(Path(path).resolve()) if path else "not saved anywhere yet"


def window_title(path: str | None, modified: bool = False) -> str:
    """The title of the window: the file being worked on, and the name of the tool
    after it, as every editor writes it."""
    return f"{tab_title(path, modified)} - pyRARS"
