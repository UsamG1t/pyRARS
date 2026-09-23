"""Assembling a program: the interface the simulator, the user interface and
the command line use.

    program = assemble(["main.s", "lib.s"])

Every file is read (includes, .eqv, macros), placed by pass 1 and turned into
machine code by pass 2. Files keep their own symbols; a symbol becomes visible
to the other files through `.globl` (or `.extern`, `.comm`).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from pyrars.asm import pass1, pass2, pseudo
from pyrars.asm.source import read_source
from pyrars.isa.instructions import mnemonics
from pyrars.isa.memory import DEFAULT, MemoryConfig
from pyrars.isa.program import AssembledProgram, Diagnostic

START_LABEL = "main"


@dataclass(frozen=True)
class Options:
    xlen: int = 32
    config: MemoryConfig = DEFAULT
    pseudo: bool = True  # pseudo-instructions allowed (RARS command line: np)
    warnings_are_errors: bool = False  # RARS: we
    start_at_main: bool = False  # RARS: sm - begin at the label "main" if it exists


def assemble(paths: Sequence[str], options: Options = Options()) -> AssembledProgram:
    """Assemble the files of one program into machine code and data."""
    operators = mnemonics(options.xlen) | pseudo.mnemonics(options.xlen)
    diagnostics: list[Diagnostic] = []
    placed = []
    text = data = extern = None  # each file continues where the previous one stopped
    for path in paths:
        lines, errors = read_source(path, operators)
        diagnostics.extend(errors)
        result = pass1.run(lines, options.xlen, options.config, text, data, extern)
        diagnostics.extend(result.diagnostics)
        placed.append(result)
        text, data, extern = result.text_end, result.data_end, result.extern_end
    code = pass2.run(placed, options.pseudo)
    diagnostics.extend(code.diagnostics)
    if options.warnings_are_errors:
        diagnostics = [d if d.kind != "Warning" else Diagnostic("Error", d.loc, d.message)
                       for d in diagnostics]
    diagnostics = _without_repetitions(diagnostics)
    diagnostics.sort(key=_position)  # messages in the order of the source, not of the passes

    data_base, data = _data_image(code.data, options.config)
    entry = code.symbols.get(START_LABEL, options.config.text_base) if options.start_at_main \
        else options.config.text_base
    return AssembledProgram(
        xlen=options.xlen,
        mem_config=options.config.name,
        text=tuple(sorted(code.text, key=lambda entry: entry.address)),
        data_base=data_base,
        data=data,
        data_layout=code.layout,
        symbols=code.symbols,
        globals=code.globals,
        entry=entry,
        diagnostics=tuple(diagnostics),
    )


def _without_repetitions(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """The same message at the same place twice says nothing new: both passes
    may report a value that fits nowhere."""
    seen, result = set(), []
    for diagnostic in diagnostics:
        if diagnostic not in seen:
            seen.add(diagnostic)
            result.append(diagnostic)
    return result


def _position(diagnostic: Diagnostic) -> tuple[str, int, int]:
    """Where a message belongs; one without a place comes first."""
    loc = diagnostic.loc
    return ("", 0, 0) if loc is None else (loc.file, loc.line, loc.column)


def _data_image(memory: dict[int, int], config: MemoryConfig) -> tuple[int, bytes]:
    """Bytes of the data segment from its base to the last byte written."""
    if not memory:
        return config.data_base, b""
    base = min(config.data_base, min(memory))
    image = bytearray(max(memory) - base + 1)
    for address, byte in memory.items():
        image[address - base] = byte
    return base, bytes(image)
