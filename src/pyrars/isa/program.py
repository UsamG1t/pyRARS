"""Result of assembling: the data the assembler gives to the simulator and the UI."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceLoc:
    file: str
    line: int  # 1-based
    column: int  # 1-based, as in RARS messages; 0 when the message has no column
    # Macro calls that led to this line, outermost first (empty outside a macro).
    calls: tuple["SourceLoc", ...] = ()


@dataclass(frozen=True)
class Diagnostic:
    """An assembler error or warning; message texts follow RARS."""

    kind: str  # "Error" or "Warning"
    loc: SourceLoc | None
    message: str


@dataclass(frozen=True)
class TextEntry:
    """One basic instruction of the text segment."""

    address: int
    word: int
    basic: str  # basic instruction as text, e.g. "addi x5,x0,5"
    loc: SourceLoc | None  # None for the 2nd and later words of an expanded pseudo-instruction
    source: str  # source line text ("" when loc is None)


@dataclass(frozen=True)
class DataItem:
    """Where a data directive put its value: the data view shows it in this format."""

    address: int
    size: int  # bytes
    directive: str  # ".word", ".asciz", ...
    loc: SourceLoc


@dataclass(frozen=True)
class AssembledProgram:
    xlen: int
    mem_config: str  # name of the memory configuration (isa/memory.py)
    text: tuple[TextEntry, ...]
    data_base: int
    data: bytes  # from data_base to the end of the last item
    data_layout: tuple[DataItem, ...]
    symbols: Mapping[str, int]
    globals: frozenset[str]
    entry: int  # where the simulator starts
    diagnostics: tuple[Diagnostic, ...]

    @property
    def failed(self) -> bool:
        return any(d.kind == "Error" for d in self.diagnostics)
