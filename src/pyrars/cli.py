"""Command line of pyRARS.

    python -m pyrars asm [options] file...     assemble source files
    python -m pyrars disasm [options] file     read a dump of words back

Messages go to the error stream, everything else (listing, symbols, dumps
without a file) to the standard output, so that the output can be redirected.
The exit code is 1 when the program has errors, 0 otherwise.
"""

import argparse
import sys
from collections.abc import Sequence

from pyrars.asm import disasm
from pyrars.asm.assembler import Options, assemble
from pyrars.isa.memory import CONFIGS, MemoryConfig
from pyrars.isa.program import AssembledProgram, Diagnostic

FORMATS = ("hex", "bin", "text")
SEGMENTS = (".text", ".data")


def main(argv: Sequence[str] | None = None, out=None, errors=None) -> int:
    """Run the command line; returns the exit code."""
    out = out if out is not None else sys.stdout
    errors = errors if errors is not None else sys.stderr
    arguments = _parser().parse_args(argv)
    if arguments.command == "asm":
        return _assemble(arguments, out, errors)
    return _disassemble(arguments, out, errors)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyrars", description="RISC-V assembler of pyRARS")
    commands = parser.add_subparsers(dest="command", required=True)

    asm = commands.add_parser("asm", help="assemble source files")
    asm.add_argument("files", nargs="+", help="source files of one program")
    asm.add_argument("-x", "--xlen", type=int, choices=(32, 64), default=32,
                     help="width of the registers (default: 32)")
    asm.add_argument("-m", "--mem-config", choices=tuple(CONFIGS), default="Default",
                     help="memory configuration (default: Default)")
    asm.add_argument("-d", "--dump", action="append", default=[], metavar="SEGMENT:FORMAT:FILE",
                     help=f"write a segment to a file: {'|'.join(SEGMENTS)} : {'|'.join(FORMATS)} "
                          ': a path or "-" for the standard output; may be repeated')
    asm.add_argument("-l", "--listing", action="store_true", help="print the text segment")
    asm.add_argument("-s", "--symbols", action="store_true", help="print the symbol table")
    asm.add_argument("-a", "--abi-names", action="store_true", help="write t0 instead of x5")
    asm.add_argument("-w", "--warnings-are-errors", action="store_true",
                     help="a warning makes the program fail")
    asm.add_argument("--no-pseudo", action="store_true", help="forbid pseudo-instructions")
    asm.add_argument("--start-at-main", action="store_true",
                     help='the entry point is the label "main" if there is one')

    dis = commands.add_parser("disasm", help="read a dump of instruction words back")
    dis.add_argument("file", help='a dump written by "asm --dump", or "-" for the standard input')
    dis.add_argument("-f", "--format", choices=("hex", "bin"), default="hex",
                     help="format of the file (default: hex)")
    dis.add_argument("-b", "--base", type=address, default=None,
                     help="address of the first word (default: the text base of the configuration)")
    dis.add_argument("-x", "--xlen", type=int, choices=(32, 64), default=32,
                     help="width of the registers (default: 32)")
    dis.add_argument("-m", "--mem-config", choices=tuple(CONFIGS), default="Default",
                     help="memory configuration, for the default base address")
    dis.add_argument("-a", "--abi-names", action="store_true", help="write t0 instead of x5")
    dis.add_argument("-p", "--pseudo", action="store_true",
                     help="name the pseudo-instruction a word stands for")
    return parser


def address(text: str) -> int:
    """An address of the command line: decimal, or 0x... - argparse needs a
    callable for this, and its name appears in the message of a wrong value."""
    return int(text, 0)


# ------------------------------------------------------------------- assemble


def _assemble(arguments, out, errors) -> int:
    config = CONFIGS[arguments.mem_config]
    program = assemble(arguments.files, Options(
        xlen=arguments.xlen, config=config, pseudo=not arguments.no_pseudo,
        warnings_are_errors=arguments.warnings_are_errors, start_at_main=arguments.start_at_main))
    for diagnostic in program.diagnostics:
        print(_message(diagnostic), file=errors)
    if program.failed:
        return 1
    if arguments.listing:
        _listing(program, out, arguments.abi_names)
    if arguments.symbols:
        _symbols(program, out)
    for request in arguments.dump:
        if not _dump(program, request, out, errors):
            return 1
    return 0


def _message(diagnostic: Diagnostic) -> str:
    """A message in the form of RARS: "Error in f.s line 5 column 8: text"."""
    loc = diagnostic.loc
    if loc is None:
        return f"{diagnostic.kind}: {diagnostic.message}"
    calls = "".join(f"{call.line}->" for call in loc.calls)  # a line reached through macros
    column = f" column {loc.column}" if loc.column else ""
    return f"{diagnostic.kind} in {loc.file} line {calls}{loc.line}{column}: {diagnostic.message}"


def _listing(program: AssembledProgram, out, abi: bool) -> None:
    for entry in program.text:
        basic = disasm.text(entry.word, program.xlen, abi=abi) or "" if abi else entry.basic
        line = str(entry.loc.line) if entry.loc else ""
        print(f"{entry.address:08x}  {entry.word:08x}  {basic:<28} {line:>5}  {entry.source}".rstrip(),
              file=out)


def _symbols(program: AssembledProgram, out) -> None:
    for name in sorted(program.symbols):
        mark = " (global)" if name in program.globals else ""
        print(f"{program.symbols[name]:08x}  {name}{mark}", file=out)


def _dump(program: AssembledProgram, request: str, out, errors) -> bool:
    parts = request.split(":")
    if len(parts) != 3 or parts[0] not in SEGMENTS or parts[1] not in FORMATS:
        print(f'"{request}": expected SEGMENT:FORMAT:FILE with SEGMENT in '
              f"{'|'.join(SEGMENTS)} and FORMAT in {'|'.join(FORMATS)}", file=errors)
        return False
    segment, form, path = parts
    data = _segment_bytes(program, segment)
    if form == "bin" and path == "-":
        print(f'"{request}": the format bin needs a file', file=errors)
        return False
    if form == "bin":
        with open(path, "wb") as file:
            file.write(data)
        return True
    lines = _text_lines(program, segment) if form == "text" else _hex_lines(data)
    if path == "-":
        for line in lines:
            print(line, file=out)
    else:
        with open(path, "w") as file:
            file.writelines(line + "\n" for line in lines)
    return True


def _segment_bytes(program: AssembledProgram, segment: str) -> bytes:
    if segment == ".data":
        return program.data
    words = bytearray()
    for entry in program.text:
        words += entry.word.to_bytes(4, "little")
    return bytes(words)


def _hex_lines(data: bytes) -> list[str]:
    return [f"{int.from_bytes(data[i:i + 4], 'little'):08x}" for i in range(0, len(data), 4)]


def _text_lines(program: AssembledProgram, segment: str) -> list[str]:
    """The text segment as a table; the data segment as address and word."""
    if segment == ".text":
        return [f"{entry.address:08x}  {entry.word:08x}  {entry.basic}".rstrip()
                for entry in program.text]
    return [f"{program.data_base + offset:08x}  {int.from_bytes(program.data[offset:offset + 4], 'little'):08x}"
            for offset in range(0, len(program.data), 4)]


# ---------------------------------------------------------------- disassemble


def _disassemble(arguments, out, errors) -> int:
    config: MemoryConfig = CONFIGS[arguments.mem_config]
    base = config.text_base if arguments.base is None else arguments.base
    try:
        words = _read_words(arguments.file, arguments.format)
    except (OSError, ValueError) as problem:
        print(f"{arguments.file}: {problem}", file=errors)
        return 1
    for number, word in enumerate(words):
        written = disasm.text(word, arguments.xlen, abi=arguments.abi_names,
                              pseudos=arguments.pseudo)
        print(f"{base + 4 * number:08x}  {word:08x}  {written or ''}".rstrip(), file=out)
    return 0


def _read_words(path: str, form: str) -> list[int]:
    if form == "bin":
        data = sys.stdin.buffer.read() if path == "-" else open(path, "rb").read()
        if len(data) % 4:
            raise ValueError("the file does not hold whole words")
        return [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]
    text = sys.stdin.read() if path == "-" else open(path).read()
    return [int(line, 16) for line in text.split()]
