"""Source stage: reads a program file into tokenized lines.

- `.include "file"` inserts the lines of the file (path relative to the
  including file); lines keep their own file name and line number.
- `.eqv symbol, text` defines a text substitution: in the following lines each
  IDENTIFIER equal to the symbol is replaced by the text and the line is
  tokenized again (RARS: Tokenizer.processIncludes, processEqv).
  The .eqv line itself stays in the output for the assembler passes.

Approved deviations from RARS (skill §7):
  DEV-10 a label before .include is kept; .include is recognized only as the
         statement directive and nothing but a comment may follow the file
         name; a file may be included again (warning), only a real cycle is
         an error
  DEV-11 ".eqv A" without text is an error; an indirect cycle (.eqv X, Y and
         .eqv Y, X) is reported like a direct one instead of crashing; the
         .eqv text is taken from the source line, so literals like 'a' work
"""

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from pyrars.asm.lexer import Kind, Token, tokenize_line
from pyrars.isa.program import Diagnostic, SourceLoc


@dataclass(frozen=True)
class SourceLine:
    file: str  # the file the line comes from
    line: int  # 1-based line number in that file
    text: str  # the line as written
    expanded: str  # the line after .eqv substitution (== text if none)
    tokens: tuple[Token, ...]  # tokens of `expanded`


def read_source(path: str, operators: Collection[str]) -> tuple[list[SourceLine], list[Diagnostic]]:
    """Lines of a program file with its .include files inserted and .eqv applied.

    operators - instruction mnemonics in lower case (see lexer.tokenize_line).
    """
    reader = _Reader(operators)
    try:
        text = _read(Path(path))
    except (OSError, UnicodeDecodeError):
        return [], [Diagnostic("Error", None, f"Error reading file {path}")]
    reader.read_lines(path, text)
    return reader.lines, reader.errors


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_lines(text: str) -> list[str]:
    """Lines separated by \\n, \\r\\n or \\r (read_text already unified them to \\n)."""
    lines = text.split("\n")
    if lines[-1] == "":  # a final newline does not start a line
        lines.pop()
    return lines


def is_label(tokens: list[Token], index: int) -> bool:
    """tokens[index:index + 2] is a label: "name:" (a name may be a mnemonic) or "1:"."""
    if index + 1 >= len(tokens) or tokens[index + 1].kind is not Kind.COLON:
        return False
    name = tokens[index]
    return (name.kind in (Kind.IDENTIFIER, Kind.OPERATOR)
            or name.kind is Kind.INTEGER and name.text.isascii() and name.text.isdigit())


def statement_start(tokens: list[Token]) -> int:
    """Index of the first token after the leading labels (DEV-15: any number of them)."""
    index = 0
    while is_label(tokens, index):
        index += 2
    return index


def _is_directive(tokens: list[Token], index: int, name: str) -> bool:
    return (index < len(tokens) and tokens[index].kind is Kind.DIRECTIVE
            and tokens[index].text.lower() == name)


class _Reader:
    def __init__(self, operators: Collection[str]) -> None:
        self.operators = operators
        self.lines: list[SourceLine] = []
        self.errors: list[Diagnostic] = []
        self.equivalents: dict[str, str] = {}  # .eqv symbol -> text
        self.reading: list[Path] = []  # files being read, outermost first (resolved)
        self.included: set[Path] = set()  # files included so far (resolved)

    def error(self, file: str, line: int, column: int, message: str, kind: str = "Error") -> None:
        diagnostic = Diagnostic(kind, SourceLoc(file, line, column), message)
        if diagnostic not in self.errors:
            self.errors.append(diagnostic)

    def tokenize(self, text: str, file: str, line: int) -> list[Token]:
        tokens, errors = tokenize_line(text, self.operators, file, line)
        for e in errors:
            if e not in self.errors:
                self.errors.append(e)
        return tokens

    def read_lines(self, file: str, text: str) -> None:
        self.reading.append(Path(file).resolve())
        for number, line in enumerate(_split_lines(text), start=1):
            self.read_line(file, number, line)
        self.reading.pop()

    def read_line(self, file: str, number: int, text: str) -> None:
        tokens = self.tokenize(text, file, number)
        start = statement_start(tokens)
        if _is_directive(tokens, start, ".include"):
            if start:  # the label stays (DEV-10)
                self.lines.append(SourceLine(file, number, text, text, tuple(tokens[:start])))
            self.include(file, number, tokens, start)
            return
        if _is_directive(tokens, start, ".eqv"):
            self.define(file, number, text, tokens, start)
            expanded = text
        else:
            expanded, tokens = self.substitute(file, number, text, tokens)
        self.lines.append(SourceLine(file, number, text, expanded, tuple(tokens)))

    # ------------------------------------------------------------ .include

    def include(self, file: str, number: int, tokens: list[Token], start: int) -> None:
        directive = tokens[start]
        operands = [t for t in tokens[start + 1:] if t.kind is not Kind.COMMENT]
        if not operands or operands[0].kind is not Kind.QUOTED_STRING:
            self.error(file, number, directive.column, 'The ".include" directive needs a file name in quotes')
            return
        name = operands[0]
        if len(operands) > 1:
            self.error(file, number, operands[1].column, 'Unexpected text after the ".include" file name')
            return
        path = Path(file).parent / name.text[1:-1]
        resolved = path.resolve()
        if resolved in self.reading:
            self.error(file, number, name.column, f"Recursive include of file {path}")
            return
        if resolved in self.included:
            self.error(file, number, name.column,
                       f"Repeated include of {path}. The convention for included files may be violated",
                       kind="Warning")
        try:
            text = _read(path)
        except (OSError, UnicodeDecodeError):
            self.error(file, number, name.column, f"Error reading include file {path}")
            return
        self.included.add(resolved)
        self.read_lines(str(path), text)

    # ---------------------------------------------------------------- .eqv

    def define(self, file: str, number: int, text: str, tokens: list[Token], start: int) -> None:
        directive = tokens[start]
        operands = [t for t in tokens[start + 1:] if t.kind is not Kind.COMMENT]
        if len(operands) > 1 and operands[1].kind is Kind.COMMA:  # .eqv symbol, text
            del operands[1]
        if len(operands) < 2:
            self.error(file, number, directive.column, "Too few operands for .eqv directive")
            return
        symbol = operands[0]
        if symbol.kind is not Kind.IDENTIFIER:
            self.error(file, number, directive.column, "Malformed .eqv directive")
            return
        comment = tokens[-1].column - 1 if tokens[-1].kind is Kind.COMMENT else len(text)
        expression = text[operands[1].column - 1:comment].rstrip(" \t,")
        if self.refers_to(expression, symbol.text, file, number):
            self.error(file, number, directive.column,
                       f"Cannot substitute {symbol.text} for itself in .eqv directive")
            return
        if self.equivalents.get(symbol.text, expression) != expression:
            self.error(file, number, symbol.column, f'"{symbol.text}" is already defined')
            return
        self.equivalents[symbol.text] = expression

    def refers_to(self, expression: str, symbol: str, file: str, number: int) -> bool:
        """The expression, expanded through the current .eqv symbols, contains symbol."""
        pending, seen = [expression], set()
        while pending:
            for token in tokenize_line(pending.pop(), self.operators, file, number)[0]:
                if token.kind is Kind.IDENTIFIER:
                    if token.text == symbol:
                        return True
                    if token.text in self.equivalents and token.text not in seen:
                        seen.add(token.text)
                        pending.append(self.equivalents[token.text])
        return False

    def substitute(self, file: str, number: int, text: str,
                   tokens: list[Token]) -> tuple[str, list[Token]]:
        """Replace .eqv symbols one at a time, tokenizing the line again after each."""
        while True:
            token = next((t for t in tokens
                          if t.kind is Kind.IDENTIFIER and t.text in self.equivalents), None)
            if token is None:
                return text, tokens
            start = token.column - 1
            text = text[:start] + self.equivalents[token.text] + text[start + len(token.text):]
            tokens = self.tokenize(text, file, number)
