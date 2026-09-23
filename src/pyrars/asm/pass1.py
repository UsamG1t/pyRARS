"""Pass 1: addresses, symbols and the layout of the data segment.

Every statement of the program is placed: an instruction gets an address and a
size (a pseudo-instruction may take several words), a data directive reserves
bytes, and every label becomes a symbol. Values that are still unknown - a
label defined further down - stay as expressions and are written by pass 2;
values that decide a size (`.align`, `.space`, the variant of a pseudo
instruction) must be known here.

Segments (user decision 2026-09-23): `.data`, `.rodata` and `.bss` share one
area that starts at the data base of the memory configuration, each section
continuing where the previous one stopped; `.extern` symbols live in their own
area. The ranges of the sections are recorded, so that a later stage can show
them or make `.rodata` read-only.

Alignment: `.byte` 1, `.half`/`.2byte`/`.short` 2, `.word`/`.4byte`/`.long`
and `.float` 4, `.dword`/`.quad`/`.8byte` and `.double` 8 (DEV-27: RARS aligns
`.dword` on 4, although it writes 8 bytes). `.align 0` switches automatic
alignment off until the next section directive.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from pyrars.asm import pseudo
from pyrars.asm.directives import DIRECTIVES
from pyrars.asm.expressions import ExprError, LocalRef, Symbol, Value, evaluate
from pyrars.asm.lexer import ESCAPES, Kind, Token
from pyrars.asm.operands import Operand, OperandError, expression, match_operands
from pyrars.asm.parser import Statement, parse_statement
from pyrars.asm.pseudo import Candidate
from pyrars.asm.source import SourceLine
from pyrars.isa.instructions import INSTRUCTIONS, find
from pyrars.isa.memory import DEFAULT, MemoryConfig
from pyrars.isa.program import DataItem, Diagnostic, SourceLoc
from pyrars.isa.spec import Instr

# ------------------------------------------------------------------- results


@dataclass(frozen=True)
class Placed:
    """An instruction with its address; `candidates` is empty for a basic one."""

    statement: Statement
    address: int
    size: int  # bytes
    order: int  # position in the program, for numeric label references
    instr: Instr | None
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class DataValue:
    """A number of the data segment; pass 2 evaluates it and writes the bytes."""

    address: int
    size: int  # bytes
    operand: Operand
    float_value: bool  # .float and .double keep a real number
    order: int
    directive: str
    loc: SourceLoc


@dataclass(frozen=True)
class NumericLabel:
    """A label written as a number: "1:" (DEV-4)."""

    number: int
    order: int
    address: int
    segment: str


@dataclass
class Symbols:
    """Symbols of one program file."""

    values: dict[str, Value] = field(default_factory=dict)
    globals: set[str] = field(default_factory=set)
    constants: set[str] = field(default_factory=set)  # defined by .equ, may be redefined
    numeric: list[NumericLabel] = field(default_factory=list)

    def resolver(self):
        """A resolve function for expressions.evaluate over the symbols known now."""
        def resolve(reference: Symbol | LocalRef) -> Value:
            if isinstance(reference, LocalRef):
                raise ExprError(reference.column, "Numeric labels are resolved in pass 2")
            if reference.name not in self.values:
                raise ExprError(reference.column,
                                f'Symbol "{reference.name}" not found in symbol table.')
            return self.values[reference.name]
        return resolve


@dataclass(frozen=True)
class Pass1:
    """What pass 1 knows: where everything goes."""

    config: MemoryConfig
    xlen: int
    text: tuple[Placed, ...]
    chunks: tuple[tuple[int, bytes], ...]  # bytes already known (strings, padding)
    values: tuple[DataValue, ...]  # numbers written by pass 2
    layout: tuple[DataItem, ...]
    sections: tuple[tuple[str, int, int], ...]  # (name, first address, address after)
    symbols: Symbols
    diagnostics: tuple[Diagnostic, ...]


# --------------------------------------------------------------- directives

_SIZES = {".byte": 1, ".2byte": 2, ".half": 2, ".short": 2, ".4byte": 4, ".word": 4,
          ".long": 4, ".8byte": 8, ".dword": 8, ".quad": 8}
_FLOAT_SIZES = {".float": 4, ".double": 8}
_STRINGS = (".ascii", ".asciz", ".string")
_SECTIONS = {".text": "text", ".data": "data", ".rodata": "rodata", ".bss": "bss",
             ".sdata": "data"}  # .sdata: RARS puts small data in the data segment
_LEB128 = (".sleb128", ".uleb128")
_EXTENSIONS = frozenset(i.ext.lower() for i in INSTRUCTIONS) | {"i"}
_NO_EFFECT = ("norvc", "nopic", "relax", "norelax")


def run(lines: Sequence[SourceLine], xlen: int = 32, config: MemoryConfig = DEFAULT) -> Pass1:
    """Place the statements of a program file (see the module docstring)."""
    state = _Pass1(xlen, config)
    for line in lines:
        state.line(line)
    return state.finish()


class _Pass1:
    def __init__(self, xlen: int, config: MemoryConfig) -> None:
        self.xlen = xlen
        self.config = config
        self.symbols = Symbols()
        self.text: list[Placed] = []
        self.chunks: list[tuple[int, bytes]] = []
        self.values: list[DataValue] = []
        self.layout: list[DataItem] = []
        self.sections: list[tuple[str, int, int]] = []
        self.diagnostics: list[Diagnostic] = []
        self.section = "text"
        self.pointers = {"text": config.text_base, "data": config.data_base}
        self.extern = config.extern_base
        self.auto_align = True
        self.options: list[None] = []  # depth of .option push
        self.order = 0
        self.globals_declared: list[tuple[str, SourceLoc]] = []
        self.section_start = config.text_base

    # ------------------------------------------------------------- helpers

    def error(self, loc: SourceLoc, message: str, kind: str = "Error") -> None:
        self.diagnostics.append(Diagnostic(kind, loc, message))

    def warning(self, loc: SourceLoc, message: str) -> None:
        self.error(loc, message, "Warning")

    @property
    def in_text(self) -> bool:
        return self.section == "text"

    @property
    def address(self) -> int:
        return self.pointers["text" if self.in_text else "data"]

    @address.setter
    def address(self, value: int) -> None:
        self.pointers["text" if self.in_text else "data"] = value

    def segment(self) -> str:
        """Segment of a label defined here, as an expression value sees it."""
        return "text" if self.in_text else "data"

    def next_order(self) -> int:
        self.order += 1
        return self.order

    def value_of(self, operand: Operand, loc: SourceLoc) -> int | None:
        """Number of an operand that must be known now; None after an error."""
        if isinstance(operand.value, int):
            return operand.value
        try:
            value = evaluate(operand.value, self.symbols.resolver())
        except ExprError as e:
            self.error(replace(loc, column=e.column), e.message)
            return None
        if value.segment is not None:
            self.error(replace(loc, column=operand.column),
                       f'"{operand.text}": operand is of incorrect type')
            return None
        return value.number

    # --------------------------------------------------------------- lines

    def line(self, line: SourceLine) -> None:
        statement, errors = parse_statement(line)
        self.diagnostics.extend(errors)
        if statement is None:
            return
        self.prealign(statement)
        for label in statement.labels:
            self.define_label(label, line)
        if statement.name is None:
            return
        name = statement.name.text.lower()
        if statement.name.kind is Kind.DIRECTIVE:
            self.directive(statement, name)
        elif name.startswith(".") and name not in DIRECTIVES:
            self.warning(line.loc(statement.name.column),
                         f"pyRARS does not recognize the {statement.name.text} directive.  Ignored.")
        else:
            self.instruction(statement, line)

    def prealign(self, statement: Statement) -> None:
        """Align before the labels of a data line, so that a label has the address
        of its data (RARS: verified by running the jar)."""
        if statement.name is None or self.in_text or not self.auto_align:
            return
        name = statement.name.text.lower()
        size = _SIZES.get(name) or _FLOAT_SIZES.get(name)
        if size is not None:
            self.align_to(size)

    def define_label(self, label: Token, line: SourceLine) -> None:
        loc = line.loc(label.column)
        if label.kind is Kind.INTEGER:  # a numeric label "1:" (DEV-4)
            self.symbols.numeric.append(
                NumericLabel(label.value, self.next_order(), self.address, self.segment()))
            return
        if label.text in self.symbols.values:
            self.error(loc, f'label "{label.text}" already defined')
            return
        self.symbols.values[label.text] = Value(self.address, self.segment())

    def instruction(self, statement: Statement, line: SourceLine) -> None:
        loc = line.loc(statement.name.column)
        instr = find(statement.name.text.lower(), self.xlen)
        error = None
        if instr is not None:
            try:
                match_operands(statement, instr)
            except OperandError as e:
                error = e
            else:
                self.place(statement, 4, instr, ())
                return
        try:
            candidates = pseudo.match(statement, self.xlen)
        except OperandError as e:
            candidates, error = [], error or e
        if candidates:
            size = self.pseudo_size(candidates, statement, line)
            self.place(statement, 4 * size, None, tuple(candidates))
            return
        if error is not None:
            self.error(line.loc(error.column), error.message)
        else:
            self.error(loc, f'"{statement.name.text}" is not a recognized operator')

    def pseudo_size(self, candidates: list[Candidate], statement: Statement,
                    line: SourceLine) -> int:
        try:
            return pseudo.size(candidates, self.symbols.resolver())
        except (OperandError, ExprError) as e:
            self.error(line.loc(e.column), e.message)
            return max(len(c.pseudo.templates) for c in candidates)

    def place(self, statement: Statement, size: int, instr: Instr | None,
              candidates: tuple[Candidate, ...]) -> None:
        if not self.in_text:
            self.error(statement.line.loc(statement.name.column),
                       f'"{statement.name.text}" instruction cannot appear in data segment')
            return
        self.text.append(Placed(statement, self.address, size, self.next_order(), instr, candidates))
        self.address += size

    # ---------------------------------------------------------- directives

    def directive(self, statement: Statement, name: str) -> None:
        line = statement.line
        loc = line.loc(statement.name.column)
        if name in (".eqv", ".macro", ".end_macro", ".endm", ".include"):
            return  # done by the source stage
        if name in _SECTIONS or name == ".section":
            self.switch_section(statement, name, loc)
        elif name in _SIZES or name in _FLOAT_SIZES:
            self.data_values(statement, name, loc)
        elif name in _STRINGS:
            self.strings(statement, name, loc)
        elif name in _LEB128:
            self.leb128(statement, name, self.numbers(statement), loc)
        elif name in (".space", ".zero"):
            self.space(name, self.numbers(statement), loc)
        elif name in (".align", ".p2align", ".balign"):
            self.align_directive(name, self.numbers(statement), loc)
        elif name in (".globl", ".global"):
            self.declare_global(statement, loc)
        elif name == ".local":
            for token in self.names(statement):
                self.symbols.globals.discard(token.text)
        elif name == ".extern":
            self.extern_symbol(statement, self.numbers(statement), loc)
        elif name in (".comm", ".common"):
            self.common(statement, self.numbers(statement), loc)
        elif name == ".equ":
            self.equ(statement, self.numbers(statement), loc)
        elif name == ".option":
            self.option(statement, loc)
        elif name == ".insn":
            self.error(loc, '".insn" is not supported yet')
        else:
            self.error(loc, f'"{statement.name.text}" directive is invalid or not implemented')

    def numbers(self, statement: Statement) -> list[Operand]:
        """Operand groups of a directive as expressions; a wrong one is reported."""
        result = []
        for tokens in statement.operands:
            text = statement.line.expanded[tokens[0].column - 1:tokens[-1].end - 1]
            try:
                result.append(Operand(expression(tokens), text, tokens[0].column))
            except OperandError as e:
                self.error(statement.line.loc(e.column), e.message)
                result.append(Operand(0, text, tokens[0].column))
        return result

    def names(self, statement: Statement, count: int | None = None) -> list[Token]:
        """The first `count` operands as symbol names (a name may be a mnemonic)."""
        names = []
        for tokens in statement.operands[:count]:
            if len(tokens) == 1 and tokens[0].kind in (Kind.IDENTIFIER, Kind.OPERATOR):
                names.append(tokens[0])
            else:
                self.error(statement.line.loc(tokens[0].column),
                           f'"{tokens[0].text}": a symbol name is expected')
        return names

    # ----------------------------------------------------------- segments

    def switch_section(self, statement: Statement, name: str, loc: SourceLoc) -> None:
        if name == ".section":
            section = self.section_name(statement, loc)
            if section is None:
                return
        else:
            section = _SECTIONS[name]
            if section != "text":
                self.auto_align = True  # a data section switches alignment back on (RARS)
            if statement.operands and section in ("text", "data"):  # ".data 0x10020000"
                address = self.value_of(self.numbers(statement)[0], loc)
                if address is not None:
                    self.pointers["text" if section == "text" else "data"] = address
        self.enter(section)

    def section_name(self, statement: Statement, loc: SourceLoc) -> str | None:
        """Section of a ".section" directive (DEV-28: ".section .text" works here)."""
        if not statement.operands:
            self.warning(loc, ".section without arguments is ignored")
            return None
        tokens = statement.operands[0]
        text = tokens[0].text
        if tokens[0].kind is Kind.QUOTED_STRING:
            text = text[1:-1]
        if text.lower() in _SECTIONS:
            return _SECTIONS[text.lower()]
        self.warning(loc, f'section name "{text}" is ignored')
        return None

    def enter(self, section: str) -> None:
        if section == self.section:
            return
        self.sections.append((self.section, self.section_start, self.address))
        self.section = section
        self.section_start = self.address

    # -------------------------------------------------------------- data

    def align_to(self, alignment: int, pad: int = 0) -> None:
        remainder = self.address % alignment
        if remainder:
            self.pad(alignment - remainder, pad)

    def pad(self, count: int, value: int = 0) -> None:
        if value:
            self.chunks.append((self.address, bytes([value & 0xFF]) * count))
        self.address += count

    def data_values(self, statement: Statement, name: str, loc: SourceLoc) -> None:
        size = _SIZES.get(name) or _FLOAT_SIZES[name]
        if self.in_text:
            self.error(loc, f'"{statement.name.text}" directive cannot appear in text segment')
            return
        if not statement.operands:
            self.error(loc, f'"{statement.name.text}" directive needs a value')
            return
        for tokens in statement.operands:
            operand = self.data_operand(statement, tokens, name in _FLOAT_SIZES)
            if self.auto_align:
                self.align_to(size)
            loc_of = statement.line.loc(operand.column)
            self.values.append(DataValue(self.address, size, operand, name in _FLOAT_SIZES,
                                         self.next_order(), name, loc_of))
            self.layout.append(DataItem(self.address, size, name, loc_of))
            self.address += size

    def data_operand(self, statement: Statement, tokens: Sequence[Token], real: bool) -> Operand:
        """One value of a data directive; .float and .double also take a real literal."""
        text = statement.line.expanded[tokens[0].column - 1:tokens[-1].end - 1]
        sign, rest = 1, tokens
        if real and tokens[0].kind is Kind.EXPR_OP and tokens[0].text in "+-" and len(tokens) > 1:
            sign, rest = (-1 if tokens[0].text == "-" else 1), tokens[1:]
        if real and len(rest) == 1 and rest[0].kind is Kind.REAL_NUMBER:
            return Operand(sign * rest[0].value, text, tokens[0].column)
        try:
            return Operand(expression(tokens), text, tokens[0].column)
        except OperandError as e:
            self.error(statement.line.loc(e.column), e.message)
            return Operand(0, text, tokens[0].column)

    def strings(self, statement: Statement, name: str, loc: SourceLoc) -> None:
        if self.in_text:
            self.error(loc, f'"{statement.name.text}" directive cannot appear in text segment')
            return
        for tokens in statement.operands:
            token = tokens[0]
            if len(tokens) != 1 or token.kind is not Kind.QUOTED_STRING:
                self.error(statement.line.loc(token.column),
                           f'"{token.text}" is not a valid character string')
                continue
            data = _decode(token.text[1:-1]) + (b"\0" if name != ".ascii" else b"")
            self.chunks.append((self.address, data))
            self.layout.append(DataItem(self.address, len(data), name,
                                        statement.line.loc(token.column)))
            self.address += len(data)

    def leb128(self, statement: Statement, name: str, operands: list[Operand],
               loc: SourceLoc) -> None:
        """Variable length encoding: its size depends on the value, so it must be known."""
        if self.in_text:
            self.error(loc, f'"{statement.name.text}" directive cannot appear in text segment')
            return
        for operand in operands:
            number = self.value_of(operand, loc)
            if number is None:
                continue
            if number < 0 and name == ".uleb128":  # its encoding would never end
                self.error(replace(loc, column=operand.column),
                           f'"{operand.text}": operand is out of range')
                continue
            data = _leb128(number, signed=name == ".sleb128")
            self.chunks.append((self.address, data))
            self.layout.append(DataItem(self.address, len(data), name,
                                        statement.line.loc(operand.column)))
            self.address += len(data)

    def space(self, name: str, operands: list[Operand], loc: SourceLoc) -> None:
        if self.in_text:
            self.error(loc, f'"{name}" directive cannot appear in text segment')
            return
        if not operands:
            self.error(loc, f'"{name}" directive needs a number of bytes')
            return
        count = self.value_of(operands[0], loc)
        if count is None:
            return
        if count < 0:
            self.error(loc, f'"{operands[0].text}": operand is out of range')
            return
        self.layout.append(DataItem(self.address, count, name, loc))
        self.pad(count)

    def align_directive(self, name: str, operands: list[Operand], loc: SourceLoc) -> None:
        if not operands:
            self.error(loc, f'"{name}" directive needs an alignment')
            return
        number = self.value_of(operands[0], loc)
        pad = self.value_of(operands[1], loc) or 0 if len(operands) > 1 else 0
        if number is None:
            return
        if name == ".align" and number == 0:  # switch automatic alignment off (RARS)
            self.auto_align = False
            return
        if number < 0 or (name != ".balign" and number > 32):
            self.error(loc, f'"{operands[0].text}": operand is out of range')
            return
        alignment = number if name == ".balign" else 1 << number
        if alignment < 1:
            self.error(loc, f'"{operands[0].text}": operand is out of range')
            return
        needed = -self.address % alignment
        if name == ".p2align" and len(operands) > 2:
            maximum = self.value_of(operands[2], loc)
            if maximum is not None and needed > maximum:
                return
        self.pad(needed, pad)

    # ------------------------------------------------------------ symbols

    def declare_global(self, statement: Statement, loc: SourceLoc) -> None:
        for token in self.names(statement):
            self.symbols.globals.add(token.text)
            self.globals_declared.append((token.text, statement.line.loc(token.column)))

    def extern_symbol(self, statement: Statement, operands: list[Operand],
                      loc: SourceLoc) -> None:
        names = self.names(statement, 1)
        if not names or len(operands) != 2:
            self.error(loc, '".extern" directive needs a symbol name and a size')
            return
        size = self.value_of(operands[1], loc)
        if size is None:
            return
        name = names[0].text
        if name in self.symbols.values:
            return  # the same symbol declared in another file of the program
        self.symbols.values[name] = Value(self.extern, "data")
        self.symbols.globals.add(name)
        self.extern += size

    def common(self, statement: Statement, operands: list[Operand], loc: SourceLoc) -> None:
        """".comm name, size[, align]": a global object in the data area."""
        names = self.names(statement, 1)
        if not names or len(operands) < 2:
            self.error(loc, f'"{statement.name.text}" directive needs a symbol name and a size')
            return
        size = self.value_of(operands[1], loc)
        alignment = self.value_of(operands[2], loc) if len(operands) > 2 else _natural(size or 0)
        if size is None or alignment is None or size < 0 or alignment < 1:
            self.error(loc, f'"{operands[1].text}": operand is out of range')
            return
        data = self.pointers["data"]
        data += -data % alignment
        self.symbols.values[names[0].text] = Value(data, "data")
        self.symbols.globals.add(names[0].text)
        self.layout.append(DataItem(data, size, statement.name.text.lower(), loc))
        self.pointers["data"] = data + size

    def equ(self, statement: Statement, operands: list[Operand], loc: SourceLoc) -> None:
        """".equ name, value": a constant, may be redefined (GNU as), no forward use."""
        names = self.names(statement, 1)
        if not names or len(operands) != 2:
            self.error(loc, '".equ" directive needs a name and a value')
            return
        name = names[0].text
        if name in self.symbols.values and name not in self.symbols.constants:
            self.error(statement.line.loc(names[0].column), f'label "{name}" already defined')
            return
        number = self.value_of(operands[1], loc)
        if number is None:
            return
        self.symbols.values[name] = Value(number)
        self.symbols.constants.add(name)

    # ------------------------------------------------------------- .option

    def option(self, statement: Statement, loc: SourceLoc) -> None:
        """Options of the asm manual; none of them changes what we assemble."""
        if not statement.operands:
            self.warning(loc, ".option without arguments is ignored")
            return
        words = ["".join(token.text for token in tokens) for tokens in statement.operands]
        name, rest = words[0].lower(), words[1:]
        if name == "push":
            self.options.append(None)
        elif name == "pop":
            if not self.options:
                self.error(loc, '".option pop": no ".option push" before it')
            else:
                self.options.pop()
        elif name == "rvc":
            self.error(loc, '".option rvc": the C extension is not supported')
        elif name == "pic":
            self.error(loc, '".option pic": position independent code is not supported')
        elif name == "arch":
            self.option_arch(rest, loc)
        elif name in _NO_EFFECT:
            self.warning(loc, f'".option {name}": has no effect on the assembled program')
        else:
            self.error(loc, f'".option {name}": unknown option')

    def option_arch(self, rest: list[str], loc: SourceLoc) -> None:
        for part in rest:
            if part.startswith("+"):
                extension = part[1:].lower().rstrip("0123456789p")
                if extension not in _EXTENSIONS:
                    self.error(loc, f'".option arch": extension "{extension}" is not supported')
                    return
        self.warning(loc, '".option arch": has no effect on the assembled program')

    # -------------------------------------------------------------- result

    def finish(self) -> Pass1:
        self.sections.append((self.section, self.section_start, self.address))
        for name, loc in self.globals_declared:
            if name not in self.symbols.values:
                self.error(loc, f'"{name}" declared global label but not defined.')
        return Pass1(self.config, self.xlen, tuple(self.text), tuple(self.chunks),
                     tuple(self.values), tuple(self.layout), tuple(self.sections),
                     self.symbols, tuple(self.diagnostics))


# ------------------------------------------------------------------ helpers


def _natural(size: int) -> int:
    """Default alignment of a common object: its size up to 4 bytes."""
    return 4 if size >= 4 else 2 if size >= 2 else 1


def _decode(text: str) -> bytes:
    r"""Bytes of a string literal: escapes of RARS (\n \t \r \\ \' \" \b \f \0),
    an unknown escape keeps its character; other characters are UTF-8."""
    result = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == "\\" and index + 1 < len(text):
            index += 1
            character = chr(ESCAPES.get(text[index], ord(text[index])))
        result.append(character)
        index += 1
    return "".join(result).encode()


def _leb128(number: int, signed: bool) -> bytes:
    """Little endian base 128 encoding (DWARF)."""
    if number < 0 and not signed:  # would never end: a negative number has no last byte
        raise ValueError(number)
    result = bytearray()
    while True:
        byte = number & 0x7F
        number >>= 7
        done = (number == 0 and (not signed or not byte & 0x40)) or \
               (signed and number == -1 and byte & 0x40)
        result.append(byte if done else byte | 0x80)
        if done:
            return bytes(result)
