"""Command line of pyRARS.

    python -m pyrars asm [options] file...     assemble source files
    python -m pyrars disasm [options] file     read a dump of words back
    python -m pyrars run [options] file...     assemble and run a program

Messages go to the error stream, everything else (listing, symbols, dumps
without a file, and what a program itself writes) to the standard output, so that
the output can be redirected. The exit code is 1 when the program has errors, 0
otherwise; a run gives back the code the program exited with, and 1 when a trap
stopped it.

The report of a run keeps the lines of RARS (R-SIM-REASON), with two of our own
for the two things RARS cannot do: a `wfi` nobody can answer, where RARS blocks for
ever (DEV-46), and a breakpoint of the command line, which RARS has only in its
window (DEV-55).
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pyrars.asm import disasm
from pyrars.asm.assembler import Options, assemble
from pyrars.core.machine import Machine
from pyrars.core.options import Options as RunOptions
from pyrars.core.simulator import Simulator, Stop, StopReason
from pyrars.core.memory import Access
from pyrars.core.systemio import ConsoleIO
from pyrars.analysis import cache as cache_model
from pyrars.analysis import predictors
from pyrars.analysis.callstack import CallStack
from pyrars.analysis.pipeline import Pipeline
from pyrars.analysis.pipeline import Settings as PipelineSettings
from pyrars.analysis.stats import Statistics
from pyrars.devices import DeviceBus, make, names as device_names
from pyrars.isa.classes import Kind
from pyrars.isa.memory import CONFIGS, MemoryConfig
from pyrars.isa.program import AssembledProgram, Diagnostic, SourceLoc
from pyrars.isa.registers import CSRS, F_NAMES, X_ALIASES, X_NAMES
from pyrars.softfloat.formats import BINARY64
from pyrars.softfloat.text import to_text

FORMATS = ("hex", "bin", "text")
SEGMENTS = (".text", ".data")
VALUE_FORMATS = ("hex", "dec", "ascii")

# What the report says about each way a run can end; the address and the message
# of a trap are added where they belong.
REPORTS = {
    StopReason.NORMAL_TERMINATION: "Program terminated by calling exit",
    StopReason.CLIFF_TERMINATION: "Program terminated by dropping off the bottom.",
    StopReason.WAITING: "Program stopped waiting for an interrupt that cannot come",
    StopReason.PAUSE: "Program paused",
    StopReason.STOP: "Program stopped",
}


def main(argv: Sequence[str] | None = None, out=None, errors=None, reader=None) -> int:
    """Run the command line; returns the exit code."""
    out = out if out is not None else sys.stdout
    errors = errors if errors is not None else sys.stderr
    arguments = _parser().parse_args(_mended(argv))
    if arguments.command == "asm":
        return _assemble(arguments, out, errors)
    if arguments.command == "run":
        return _run(arguments, out, errors,
                    reader if reader is not None else sys.stdin)
    return _disassemble(arguments, out, errors)


def _mended(argv: Sequence[str] | None) -> Sequence[str] | None:
    """`--pipeline` may be given with options or without any, and the options of a
    model always hold an "=" - so a `--pipeline` followed by anything else is one
    without options, and what follows is a file.
    """
    if argv is None:
        return None
    mended = []
    for index, word in enumerate(argv):
        following = argv[index + 1] if index + 1 < len(argv) else ""
        if word == "--pipeline" and "=" not in following:
            mended.append("--pipeline=")
        else:
            mended.append(word)
    return mended


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

    run = commands.add_parser("run", help="assemble and run a program")
    run.add_argument("files", nargs="+", help="source files of one program")
    run.add_argument("-x", "--xlen", type=int, choices=(32, 64), default=32,
                     help="width of the registers (default: 32)")
    run.add_argument("-m", "--mem-config", choices=tuple(CONFIGS), default="Default",
                     help="memory configuration (default: Default)")
    run.add_argument("--self-modifying", action="store_true",
                     help="let the program read and write its own text")
    run.add_argument("--steps", type=int, default=None, metavar="N",
                     help="stop after N turns of the loop (default: no limit)")
    run.add_argument("-r", "--registers", default="", metavar="NAMES",
                     help="print these registers at the end, e.g. a0,t1,f2,fcsr")
    run.add_argument("--memory", action="append", default=[], metavar="LOW-HIGH",
                     help="print this range of memory at the end; may be repeated")
    run.add_argument("-c", "--instruction-count", action="store_true",
                     help="print how many instructions were carried out")
    run.add_argument("-f", "--format", choices=VALUE_FORMATS, default="hex",
                     help="how printed values look (default: hex)")
    run.add_argument("--break", dest="breakpoints", default="", metavar="ADDRESSES",
                     help="stop before the instruction at any of these addresses")
    run.add_argument("--stats", action="store_true",
                     help="count what the run was made of and print it at the end")
    run.add_argument("--cache", action="append", default=[], metavar="[SIDE:]OPTIONS",
                     help="watch the accesses with a cache; SIDE is data (the "
                          "default), instructions or unified, and the options are "
                          "block_bytes, sets, ways, replacement, seed, write_back, "
                          "write_allocate, log, sample; may be given once per side")
    run.add_argument("--pipeline", nargs="?", const="", metavar="OPTIONS",
                     help="time the run on a pipeline of five stages; the options are "
                          "forwarding, one_port, penalty, trap_penalty, diagram, "
                          "predictor (never, always or table), entries, bits, taken, "
                          "and a latency per kind of instruction, e.g. divide=10. "
                          "Options always hold an \"=\", so a file name after the flag "
                          "is taken for a file")
    run.add_argument("--callstack", action="store_true",
                     help="follow which call the run is inside (a guess from the "
                          "convention, see docs/analysis.md)")
    run.add_argument("--device", action="append", default=[], metavar="NAME[:OPTIONS]",
                     help=f"attach a device ({', '.join(device_names())}); options as "
                          "key=value separated by commas, e.g. "
                          "keyboard:delay=10,keys=input.txt or disk:file=blocks.img; "
                          "may be repeated")
    run.add_argument("--args", nargs="*", default=[], metavar="ARG",
                     help="arguments of the program itself; comes last of all, because "
                          "everything after it belongs to the program")
    run.add_argument("-w", "--warnings-are-errors", action="store_true",
                     help="a warning makes the program fail")
    run.add_argument("--no-pseudo", action="store_true", help="forbid pseudo-instructions")
    run.add_argument("--start-at-main", action="store_true",
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


# -------------------------------------------------------------------- run


def _run(arguments, out, errors, reader) -> int:
    """Assemble a program and run it. The program writes to the same streams and
    reads from the same input as the command line itself."""
    config = CONFIGS[arguments.mem_config]
    program = assemble(arguments.files, Options(
        xlen=arguments.xlen, config=config, pseudo=not arguments.no_pseudo,
        warnings_are_errors=arguments.warnings_are_errors,
        start_at_main=arguments.start_at_main))
    for diagnostic in program.diagnostics:
        print(_message(diagnostic), file=errors)
    if program.failed:
        return 1

    try:
        breakpoints = frozenset(address(text) for text in arguments.breakpoints.split(",")
                                if text)
        names = [name for name in arguments.registers.split(",") if name]
        ranges = [_range(text) for text in arguments.memory]
        for name in names:
            _register_value(None, name)  # the names are checked before the run
    except ValueError as problem:
        print(problem, file=errors)
        return 1

    try:
        bus, afterwards = _devices(arguments.device, out, reader)
    except (ValueError, TypeError, OSError) as problem:
        print(problem, file=errors)
        return 1

    # A plain run keeps no journal: there is nobody to look at it (user decision
    # 2026-10-05); a debugging session asks for one.
    world = ConsoleIO(out=out, errors=errors, reader=reader)
    machine = Machine(RunOptions(xlen=arguments.xlen, config=config,
                                 self_modifying=arguments.self_modifying),
                      bus=bus, io=world)
    if bus is not None:
        bus.connect(machine)
    simulator = Simulator(machine)
    simulator.load(program, arguments.args)
    try:
        watchers = _watchers(arguments, machine)
    except (ValueError, TypeError) as problem:
        print(problem, file=errors)
        return 1
    stop = simulator.run(max_steps=arguments.steps, breakpoints=breakpoints,
                         watch=watchers.saw if watchers else None)
    for finish in afterwards:
        finish()

    _report(stop, program, arguments.steps, errors)
    if not world.fresh and (arguments.instruction_count or names or ranges or watchers):
        print(file=out)  # a program that printed no newline keeps its own line
    if arguments.instruction_count:
        print(f"instructions\t{simulator.count}", file=out)
    for name in names:
        value, bits = _register_value(machine, name)
        print(f"{name}\t{_value(value, bits, arguments.format)}", file=out)
    for low, high in ranges:
        _memory(machine, low, high, arguments.format, out)
    if watchers:
        watchers.told(program, out)
    if stop.reason is StopReason.EXCEPTION:
        return 1
    return stop.code


class Watchers:
    """The models of `pyrars.analysis` a run was asked for.

    They are handed what the run did - every turn from the loop, and the accesses
    of memory through a subscription - and they touch nothing of it (INV-P).
    """

    def __init__(self, arguments, machine: Machine) -> None:
        self.statistics = Statistics() if arguments.stats else None
        self.caches, self.fetches = _caches(arguments.cache, machine)
        self.pipeline = _pipeline(arguments.pipeline)
        self.callstack = CallStack() if arguments.callstack else None
        self.machine = machine

    def __bool__(self) -> bool:
        return any((self.statistics, self.caches, self.pipeline, self.callstack))

    def saw(self, turn) -> None:
        """One turn of the loop."""
        if self.statistics is not None:
            self.statistics.saw(turn)
        if self.pipeline is not None:
            self.pipeline.saw(turn)
        if self.callstack is not None:
            self.callstack.saw(turn, sp=self.machine.x.read(2))
        if self.fetches:
            self.caches.fetch(turn.pc)

    def told(self, program: AssembledProgram, out) -> None:
        """What the models have to say, one `name<tab>value` to a line."""
        if self.statistics is not None:
            _said(out, "instructions", self.statistics.instructions)
            _said(out, "turns", self.statistics.turns)
            for name, many in self.statistics.kinds().items():
                _said(out, f"kind.{name}", many)
            for name, many in self.statistics.categories().items():
                _said(out, f"category.{name.lower()}", many)
            if self.statistics.by_kind.get(Kind.BRANCH):
                _said(out, "branches.taken", self.statistics.taken)
                _said(out, "branches.not-taken", self.statistics.not_taken)
        if self.caches is not None:
            for side, cache in self.caches.each().items():
                for name, value in (("accesses", cache.accesses), ("hits", cache.hits),
                                    ("misses", cache.misses),
                                    ("rate", round(cache.hit_rate, 4)),
                                    ("writebacks", cache.writebacks),
                                    ("through", cache.through)):
                    _said(out, f"{side}.{name}", value)
        if self.pipeline is not None:
            _said(out, "pipeline.cycles", self.pipeline.cycles)
            _said(out, "pipeline.instructions", self.pipeline.instructions)
            _said(out, "pipeline.cpi", round(self.pipeline.cpi, 4))
            _said(out, "pipeline.lost", self.pipeline.lost)
            for cause, many in sorted(self.pipeline.stalls.items()):
                _said(out, f"pipeline.lost.{cause}", many)
            _said(out, "pipeline.branches", self.pipeline.branches)
            _said(out, "pipeline.wrong", self.pipeline.mispredictions)
            _said(out, "pipeline.guesser", self.pipeline.predictor.name)
            for row in self.pipeline.diagram:
                stages = " ".join(str(cycle) for cycle in row.starts)
                print(f"pipeline.row\t0x{row.pc:08x}\t{row.mnemonic}\t{stages}", file=out)
        if self.callstack is not None:
            stack = self.callstack
            for name, value in (("calls", stack.calls), ("returns", stack.returns),
                                ("deepest", stack.deepest), ("depth", stack.depth),
                                ("unmatched", stack.unmatched),
                                ("confused", stack.confused), ("beyond", stack.beyond)):
                _said(out, f"callstack.{name}", value)
            for frame in stack.frames:
                where = "?" if frame.sp is None else f"0x{frame.sp:08x}"
                print(f"callstack.frame\t{_named(program, frame.called)}\t"
                      f"0x{frame.called_from:08x}\t{where}", file=out)


def _said(out, name: str, value) -> None:
    print(f"{name}\t{value}", file=out)


def _named(program: AssembledProgram, address: int) -> str:
    """The name of an address, where the program gave it one."""
    for name, place in program.symbols.items():
        if place == address:
            return name
    return f"0x{address:08x}"


def _watchers(arguments, machine: Machine) -> Watchers:
    return Watchers(arguments, machine)


CACHE_SIDES = ("data", "instructions", "unified")


def _asked_of_a_cache(request: str) -> tuple[str, dict[str, object]]:
    """"instructions:sets=16" as the side of the cache and what was asked of it. A
    request that names no side is about the cache of the data."""
    side, sign, rest = request.partition(":")
    if sign and side.strip() in CACHE_SIDES:
        return side.strip(), _options(rest, request)
    return "data", _options(request, request)


def _caches(requests: Sequence[str], machine: Machine):
    """The caches a run was asked for, and whether the fetches reach one.

    They watch the data segment of the memory. The area of the devices is never
    watched: the registers of a device are not the kind of thing a cache may keep.
    """
    if not requests:
        return None, False
    sides: dict[str, cache_model.Settings] = {}
    for request in requests:
        side, options = _asked_of_a_cache(request)
        if side in sides:
            raise ValueError(f'"{request}": the {side} cache was asked for twice')
        try:
            sides[side] = cache_model.Settings(**options)
        except TypeError as problem:
            raise ValueError(f'"{request}": {problem}') from None
    if "unified" in sides and len(sides) > 1:
        raise ValueError("a cache for everything and a cache of one side cannot be "
                         "asked for together")
    if "unified" in sides:
        caches = cache_model.Caches(data=sides["unified"])
        fetches = True
    else:
        caches = cache_model.Caches(data=sides.get("data", cache_model.Settings()),
                                    instructions=sides.get("instructions"))
        fetches = caches.split
    config = machine.options.config
    machine.memory.subscribe(Access.READ, lambda access: caches.read(access.address),
                             config.data_segment_base, config.data_segment_limit)
    machine.memory.subscribe(Access.WRITE, lambda access: caches.write(access.address),
                             config.data_segment_base, config.data_segment_limit)
    return caches, fetches


def _pipeline(request: str | None) -> Pipeline | None:
    """The pipeline a run was asked for, with its guesser."""
    if request is None:
        return None
    options = _options(request, f"--pipeline {request}")
    # The command line draws no diagram unless it was asked for one: a run of a
    # million instructions would bury everything else under it.
    options.setdefault("diagram", 0)
    latency = {}
    for which in Kind:
        name = which.name.lower()
        if name in options:
            latency[which] = options.pop(name)
    guesser = _guesser(options)
    try:
        settings = PipelineSettings(latency=latency, **options)
    except TypeError as problem:
        raise ValueError(f'"--pipeline {request}": {problem}') from None
    return Pipeline(settings, guesser)


def _guesser(options: dict):
    """How the machine of the model guesses where a branch goes."""
    which = options.pop("predictor", "never")
    entries = options.pop("entries", 16)
    bits = options.pop("bits", 1)
    taken = options.pop("taken", False)
    if which == "never":
        return predictors.Static(False)
    if which == "always":
        return predictors.Static(True)
    if which == "table":
        return predictors.History(entries=entries, bits=bits, taken=taken)
    raise ValueError(f'"{which}": a branch is guessed at by never, always or table')


# What a device needs of the world outside, which the device itself never touches:
# where the keys of a keyboard come from, and the file a disk holds.
OUTSIDE = {"keyboard": "keys", "disk": "file"}


def _devices(requests: Sequence[str], out, reader):
    """Build the devices a run was asked for, and what to do when it is over.

    The devices know nothing of files: a keyboard is given a text to type and a
    disk an image of bytes, and putting the image back is one of the things left to
    do afterwards.
    """
    if not requests:
        return None, ()
    bus = DeviceBus()
    afterwards = []
    for request in requests:
        name, options = _asked_for(request)
        outside = options.pop(OUTSIDE.get(name, ""), None)
        try:
            device = make(name, **options)
        except TypeError as problem:  # an option the device has not got
            raise ValueError(f'"{request}": {problem}') from None
        bus.add(device)
        if name == "keyboard":
            if outside is not None:
                letters = iter(_text_of(str(outside), reader))
                device.feed(lambda: next(letters, None))
            afterwards.append(_display(device, out))
        elif name == "disk" and outside is not None:
            afterwards.append(_image(device, str(outside)))
    return bus, afterwards


def _asked_for(request: str) -> tuple[str, dict[str, object]]:
    """"keyboard:delay=10,keys=in.txt" as a name and what was asked of it."""
    name, _, rest = request.partition(":")
    return name.strip(), _options(rest, request)


def _options(text: str, request: str) -> dict[str, object]:
    """"delay=10,keys=in.txt" as what was asked for."""
    options: dict[str, object] = {}
    for piece in text.split(",") if text else ():
        key, sign, value = piece.partition("=")
        if not sign:
            raise ValueError(f'"{request}": an option is key=value')
        options[key.strip()] = _said_as(value.strip())
    return options


def _said_as(text: str) -> object:
    """A number, a yes or no, or a text, as it was written."""
    if text in ("yes", "true"):
        return True
    if text in ("no", "false"):
        return False
    try:
        return int(text, 0)
    except ValueError:
        return text


def _text_of(path: str, reader) -> str:
    """The text a keyboard is to type: a file, or the standard input for "-"."""
    return reader.read() if path == "-" else Path(path).read_text()


def _display(device, out) -> Callable[[], None]:
    """Show what the display of a keyboard shows.

    While it scrolls, every character goes out as it appears, which is the console
    answering for the window of a tool. In the mode where a character goes where it
    is told, the picture of it is printed when the run is over, because a terminal
    cannot take back what has already left it.
    """
    gone = [0]  # how much of the scrolling text has gone out

    def changed() -> None:
        if device.told_where:
            return
        text = device.text
        if len(text) > gone[0]:
            out.write(text[gone[0]:])
            gone[0] = len(text)

    device.subscribe(changed)

    def finish() -> None:
        if device.told_where:
            out.write(device.shown() + "\n")

    return finish


def _image(device, path: str) -> Callable[[], None]:
    """Put the file on the disk, and give back what will write it back."""
    place = Path(path)
    if place.exists():
        device.load(place.read_bytes())
    return lambda: place.write_bytes(device.saved())


def _report(stop: Stop, program: AssembledProgram, limit: int | None, errors) -> None:
    """Why the run ended, in the words of RARS where it has them."""
    print(file=errors)
    if stop.reason is StopReason.EXCEPTION:
        print(f"{_where(program, stop.address)}Runtime exception at "
              f"0x{stop.address:08x}: {stop.message}", file=errors)
        print("\nSimulation terminated due to errors.", file=errors)
    elif stop.reason is StopReason.MAX_STEPS:
        print(f"Program terminated when maximum step limit {limit} reached.", file=errors)
    elif stop.reason is StopReason.BREAKPOINT:
        print(f"Program stopped at a breakpoint 0x{stop.address:08x}", file=errors)
    else:
        print(REPORTS[stop.reason], file=errors)


def _where(program: AssembledProgram, address: int) -> str:
    """\"Error in f.s line 7: \" for an address of the text segment.

    The second and later words of an expanded pseudo-instruction carry no place of
    their own, so the line is the one of the last word that carries one, as RARS
    reports it too.
    """
    loc: SourceLoc | None = None
    for entry in program.text:
        if entry.address > address:
            break
        if entry.loc is not None:
            loc = entry.loc
    if loc is None:
        return "Error: "
    return f"Error in {loc.file} line {loc.line}: "


def _range(request: str) -> tuple[int, int]:
    parts = request.split("-")
    if len(parts) != 2:
        raise ValueError(f'"{request}": expected LOW-HIGH, e.g. 0x10010000-0x10010020')
    low, high = (address(part) for part in parts)
    if high < low:
        raise ValueError(f'"{request}": the first address must be the lower one')
    return low, high


def _register_value(machine: Machine | None, name: str) -> tuple[int, int]:
    """The value of a register by name and how many bits it holds: `x0`..`x31` or an
    ABI name like `t0`, `f0`..`f31` or an ABI name like `fa0`, and the control
    registers by name. A floating point register is 64 bits wide in both widths of
    the machine, and its bits are printed as they lie. A machine of None only checks
    the name, which is what a run does before it starts.

    Raises ValueError for a name nobody has.
    """
    bits = 32 if machine is None else machine.xlen
    number = _number_of(name, "x", X_NAMES, X_ALIASES)
    if number is not None:
        return (0 if machine is None else machine.x.read(number)), bits
    number = _number_of(name, "f", F_NAMES, {})
    if number is not None:
        return (0 if machine is None else machine.f.raw(number)), 64
    if name in CSRS:
        return (0 if machine is None else machine.csr.read(CSRS[name])), bits
    raise ValueError(f'"{name}": no register of that name')


def _number_of(name: str, letter: str, names: tuple[str, ...],
               aliases: dict[str, int]) -> int | None:
    """The number of a register of one file, or None when the name is not of it."""
    if name in aliases:
        return aliases[name]
    if name in names:
        return names.index(name)
    if name.startswith(letter) and name[1:].isdigit():
        number = int(name[1:])
        return number if number < len(names) else None
    return None


def _value(value: int, bits: int, form: str) -> str:
    """One value of `bits` bits, as the chosen format writes it. A register of a
    64-bit machine therefore shows sixteen hexadecimal digits, where RARS prints
    the low eight of any register (DEV-47); a word of memory is four bytes in both
    widths."""
    if form == "hex":
        return f"0x{value:0{bits // 4}x}"
    if form == "dec":
        return str(value - (1 << bits) if value >> (bits - 1) else value)
    return _ascii(value, bits // 8)


def _ascii(value: int, width: int) -> str:
    """The bytes of a value as characters, the highest first, each in three columns
    and an unprintable one as a full stop - the way RARS writes them."""
    letters = []
    for index in reversed(range(width)):
        byte = (value >> (8 * index)) & 0xFF
        letters.append(f"{chr(byte) if 32 <= byte < 127 else '.':>3}")
    return "".join(letters)


def _memory(machine: Machine, low: int, high: int, form: str, out) -> None:
    """A range of memory, four words to a line, as RARS prints it."""
    addresses = range(low - low % 4, high + 1, 4)
    for start in range(0, len(addresses), 4):
        row = addresses[start:start + 4]
        values = (_value(machine.memory.peek(place, 4), 32, form) for place in row)
        print(f"Mem[0x{row[0]:08x}]\t" + "\t".join(values), file=out)


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
