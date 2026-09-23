"""Pass 2: values, machine code and the data image.

Pass 1 knows where everything goes; pass 2 knows what it is. For every file
of the program it resolves the symbols (its own, the globals of the other
files, and the numeric labels by their position), expands the
pseudo-instructions, encodes the instructions and writes the data values.

A value that does not fit its data directive is truncated with the warning of
RARS. Two instructions at the same address are reported like RARS does.
"""

import struct
from collections.abc import Sequence
from dataclasses import dataclass, replace

from pyrars.asm import pseudo
from pyrars.asm.expressions import ExprError, LocalRef, Symbol, Value, evaluate
from pyrars.asm.insn import encode_insn
from pyrars.asm.operands import OperandError, field_value, match_operands
from pyrars.asm.pass1 import DataValue, Pass1, Placed
from pyrars.isa.codec import encode
from pyrars.isa.program import DataItem, Diagnostic, SourceLoc, TextEntry
from pyrars.isa.spec import Instr

_FLOAT_FORMATS = {4: "f", 8: "d"}


@dataclass(frozen=True)
class Assembled:
    """Result of pass 2 over all files of a program."""

    text: tuple[TextEntry, ...]
    data: dict[int, int]  # address -> byte
    layout: tuple[DataItem, ...]
    symbols: dict[str, int]
    globals: frozenset[str]
    diagnostics: tuple[Diagnostic, ...]


def run(files: Sequence[Pass1], pseudo_allowed: bool = True) -> Assembled:
    """Machine code and data of the program; `files` are the results of pass 1."""
    state = _Pass2(files, pseudo_allowed)
    state.run()
    return state.finish()


class _Pass2:
    def __init__(self, files: Sequence[Pass1], pseudo_allowed: bool) -> None:
        self.files = files
        self.pseudo_allowed = pseudo_allowed
        self.diagnostics: list[Diagnostic] = []
        self.entries: list[TextEntry] = []
        self.data: dict[int, int] = {}
        self.occupied: dict[int, SourceLoc] = {}  # text address -> where it came from
        self.globals: dict[str, Value] = {}
        self.symbols: dict[str, int] = {}

    def error(self, loc: SourceLoc, message: str, kind: str = "Error") -> None:
        self.diagnostics.append(Diagnostic(kind, loc, message))

    # ------------------------------------------------------------- symbols

    def collect_globals(self) -> None:
        for result in self.files:
            for name in sorted(result.symbols.globals):
                value = result.symbols.values.get(name)
                if value is None:
                    continue  # pass 1 reported it
                if name in self.globals:
                    where = result.symbols.where.get(name, SourceLoc("", 0, 0))
                    self.error(where, f'label "{name}" already defined')
                    continue
                self.globals[name] = value
        for result in self.files:
            for name, value in result.symbols.values.items():
                self.symbols.setdefault(name, value.number)

    def resolver(self, result: Pass1, order: int):
        """Resolve a symbol for a statement at this position of this file."""
        local = result.symbols

        def resolve(reference: Symbol | LocalRef) -> Value:
            if isinstance(reference, LocalRef):
                return self.numeric_label(local, reference, order)
            if reference.name in local.values:
                return local.values[reference.name]
            if reference.name in self.globals:
                return self.globals[reference.name]
            raise ExprError(reference.column,
                            f'Symbol "{reference.name}" not found in symbol table.')
        return resolve

    def numeric_label(self, local, reference: LocalRef, order: int) -> Value:
        """Nb is the nearest definition before this statement, Nf the nearest after (DEV-4)."""
        labels = [label for label in local.numeric if label.number == reference.number]
        if reference.forward:
            wanted = [label for label in labels if label.order > order]
        else:
            wanted = [label for label in reversed(labels) if label.order < order]
        if not wanted:
            where = "after" if reference.forward else "before"
            raise ExprError(reference.column,
                            f'Symbol "{reference.number}{"f" if reference.forward else "b"}" '
                            f"not found {where} this line.")
        return Value(wanted[0].address, wanted[0].segment)

    # ---------------------------------------------------------------- text

    def run(self) -> None:
        self.collect_globals()
        for result in self.files:
            for address, data in result.chunks:  # strings and padding of pass 1
                for offset, byte in enumerate(data):
                    self.data[address + offset] = byte
            for placed in result.text:
                self.instruction(result, placed)
            for value in result.values:
                self.data_value(result, value)

    def instruction(self, result: Pass1, placed: Placed) -> None:
        resolve = self.resolver(result, placed.order)
        statement = placed.statement
        loc = statement.line.loc(statement.name.column)
        try:
            words = self.words(placed, resolve)
        except (OperandError, ExprError) as e:
            self.error(replace(loc, column=e.column), e.message)
            words = [0] * (placed.size // 4)
        for number, word in enumerate(words):
            address = placed.address + 4 * number
            self.check_address(address, loc)
            self.entries.append(TextEntry(address, word, "",
                                          loc if number == 0 else None,
                                          statement.line.expanded if number == 0 else ""))

    def words(self, placed: Placed, resolve) -> list[int]:
        statement = placed.statement
        if placed.instr is not None:
            return [self.basic_word(placed.instr, statement, resolve, placed.address)]
        if placed.candidates:
            if not self.pseudo_allowed:
                raise OperandError(statement.name.column,
                                   "Extended (pseudo) instruction or format not permitted.  "
                                   "See Settings.")
            chosen = pseudo.choose(list(placed.candidates), resolve, placed.size // 4)
            return [encode(e.instr, e.fields) for e in pseudo.expand(chosen, resolve, placed.address)]
        return [encode_insn(statement, resolve, placed.address)]  # ".insn"

    def basic_word(self, instr: Instr, statement, resolve, address: int) -> int:
        fields = {name: field_value(instr, name, operand, resolve, address)
                  for name, operand in match_operands(statement, instr).items()}
        return encode(instr, fields)

    def check_address(self, address: int, loc: SourceLoc) -> None:
        first = self.occupied.get(address)
        if first is not None:
            self.error(replace(loc, column=0),
                       f"Duplicate text segment address: 0x{address:08x} already occupied by "
                       f"{first.file} line {first.line} (caused by use of .text operand)")
        else:
            self.occupied[address] = loc

    # ---------------------------------------------------------------- data

    def data_value(self, result: Pass1, value: DataValue) -> None:
        resolve = self.resolver(result, value.order)
        number = value.operand.value
        if not isinstance(number, (int, float)):
            try:
                number = evaluate(number, resolve).number
            except ExprError as e:
                self.error(replace(value.loc, column=e.column), e.message)
                return
        if value.float_value:
            data = _float_bytes(float(number), value.size)
        else:
            data = self.integer_bytes(int(number), value)
        for offset, byte in enumerate(data):
            self.data[value.address + offset] = byte

    def integer_bytes(self, number: int, value: DataValue) -> bytes:
        """The value in `size` bytes; one that does not fit is truncated (RARS)."""
        bits = 8 * value.size
        mask = (1 << bits) - 1
        if not -(1 << (bits - 1)) <= number <= mask:
            digits = 8 if value.size <= 4 else 16
            self.error(value.loc, f"value 0x{number & ((1 << 4 * digits) - 1):0{digits}x} is "
                                  f"out-of-range and truncated to 0x{number & mask:0{digits}x}",
                       "Warning")
        return (number & mask).to_bytes(value.size, "little")

    # -------------------------------------------------------------- result

    def finish(self) -> Assembled:
        layout = tuple(item for result in self.files for item in result.layout)
        return Assembled(tuple(self.entries), self.data, layout, self.symbols,
                         frozenset(self.globals), tuple(self.diagnostics))


def _float_bytes(number: float, size: int) -> bytes:
    return struct.pack("<" + _FLOAT_FORMATS[size], number)
