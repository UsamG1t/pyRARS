"""Source stage: reads a program file into tokenized lines.

- `.include "file"` inserts the lines of the file (path relative to the
  including file); lines keep their own file name and line number.
- `.eqv symbol, text` defines a text substitution: in the following lines each
  IDENTIFIER equal to the symbol is replaced by the text and the line is
  tokenized again (RARS: Tokenizer.processIncludes, processEqv).
  The .eqv line itself stays in the output for the assembler passes.
- `.macro name %p` ... `.end_macro` defines a macro (see asm/macros.py); a call
  of it is replaced by its body, which is read like source text, so that the
  `.eqv` symbols and the `.include` files of the call point apply to it.

Approved deviations from RARS (skill §7):
  DEV-10 a label before .include is kept; .include is recognized only as the
         statement directive and nothing but a comment may follow the file
         name; a file may be included again (warning), only a real cycle is
         an error
  DEV-11 ".eqv A" without text is an error; an indirect cycle (.eqv X, Y and
         .eqv Y, X) is reported like a direct one instead of crashing; the
         .eqv text is taken from the source line, so literals like 'a' work
  DEV-17 macro parameters and labels are replaced by tokens, not by text search
  DEV-18 macro arguments and parameters are separated by commas; parentheses
         around them are not a macro call syntax
  DEV-19 an expansion loop is reported at the call of a macro that is already
         being expanded
  DEV-20 a macro body sees the .eqv symbols known at the call, not those of the
         whole file
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pyrars.asm.lexer import Kind, Token, tokenize_line
from pyrars.asm.macros import BodyLine, Macro, defined, find, parse_definition, substitute
from pyrars.isa.program import Diagnostic, SourceLoc


@dataclass(frozen=True)
class SourceLine:
    file: str  # the file the line comes from
    line: int  # 1-based line number in that file
    text: str  # the line as written
    expanded: str  # the line after .eqv substitution (== text if none)
    tokens: tuple[Token, ...]  # tokens of `expanded`
    calls: tuple[SourceLoc, ...] = ()  # macro calls that led to this line

    def loc(self, column: int) -> SourceLoc:
        return SourceLoc(self.file, self.line, column, self.calls)


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
    reader.finish()
    return reader.lines, reader.errors


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_lines(text: str) -> list[str]:
    """Lines separated by \\n, \\r\\n or \\r (read_text already unified them to \\n)."""
    lines = text.split("\n")
    if lines[-1] == "":  # a final newline does not start a line
        lines.pop()
    return lines


def is_label(tokens: Sequence[Token], index: int) -> bool:
    """tokens[index:index + 2] is a label: "name:" (a name may be a mnemonic) or "1:"."""
    if index + 1 >= len(tokens) or tokens[index + 1].kind is not Kind.COLON:
        return False
    name = tokens[index]
    return (name.kind in (Kind.IDENTIFIER, Kind.OPERATOR)
            or name.kind is Kind.INTEGER and name.text.isascii() and name.text.isdigit())


def statement_start(tokens: Sequence[Token]) -> int:
    """Index of the first token after the leading labels (DEV-15: any number of them)."""
    index = 0
    while is_label(tokens, index):
        index += 2
    return index


def labels(tokens: Sequence[Token]) -> Sequence[Token]:
    """The leading label names of a line, without their colons."""
    return tokens[:statement_start(tokens):2]


def _is_directive(tokens: Sequence[Token], index: int, name: str) -> bool:
    return (index < len(tokens) and tokens[index].kind is Kind.DIRECTIVE
            and tokens[index].text.lower() == name)


def _is_end_macro(tokens: Sequence[Token], index: int) -> bool:
    """.end_macro (RARS) or .endm (GNU as, D15) end a macro definition."""
    return _is_directive(tokens, index, ".end_macro") or _is_directive(tokens, index, ".endm")


def _arguments(tokens: Sequence[Token], text: str) -> list[str] | None:
    """Texts of the comma separated arguments of a macro call, None if one is missing."""
    groups: list[str] = []
    group: list[Token] = []
    for token in tokens:
        if token.kind is Kind.COMMENT:
            break
        if token.kind is not Kind.COMMA:
            group.append(token)
        elif group:
            groups.append(text[group[0].column - 1:group[-1].end - 1])
            group = []
        else:
            return None  # ",," or a leading comma: the parser reports it
    if group:
        groups.append(text[group[0].column - 1:group[-1].end - 1])
    elif groups:
        return None  # a trailing comma
    return groups


class _Reader:
    def __init__(self, operators: Collection[str]) -> None:
        self.operators = operators
        self.lines: list[SourceLine] = []
        self.errors: list[Diagnostic] = []
        self.equivalents: dict[str, str] = {}  # .eqv symbol -> text
        self.reading: list[Path] = []  # files being read, outermost first (resolved)
        self.included: set[Path] = set()  # files included so far (resolved)
        self.macros: list[Macro] = []  # macros defined so far
        self.defining: Macro | None = None  # the macro whose body is being read
        self.expanding: list[Macro] = []  # macros being expanded, outermost first
        self.calls: tuple[SourceLoc, ...] = ()  # the calls of `expanding`
        self.counter = 0  # number of expansions so far (suffix of the body labels)

    def error(self, file: str, line: int, column: int, message: str, kind: str = "Error") -> None:
        self.add_error(Diagnostic(kind, SourceLoc(file, line, column, self.calls), message))

    def add_error(self, diagnostic: Diagnostic) -> None:
        if diagnostic not in self.errors:
            self.errors.append(diagnostic)

    def tokenize(self, text: str, file: str, line: int) -> list[Token]:
        tokens, errors = tokenize_line(text, self.operators, file, line)
        for e in errors:
            self.add_error(replace(e, loc=replace(e.loc, calls=self.calls)))
        return tokens

    def add_line(self, line: SourceLine) -> None:
        """Keep a line: inside a .macro definition it belongs to the macro body."""
        if self.defining is None:
            self.lines.append(line)
            return
        self.defining.body.append(BodyLine(line.file, line.line, line.text))
        self.defining.labels.update(t.text for t in labels(line.tokens) if t.kind is Kind.IDENTIFIER)

    def read_lines(self, file: str, text: str) -> None:
        self.reading.append(Path(file).resolve())
        for number, line in enumerate(_split_lines(text), start=1):
            self.read_line(file, number, line)
        self.reading.pop()

    def read_line(self, file: str, number: int, text: str) -> None:
        tokens = self.tokenize(text, file, number)
        start = statement_start(tokens)
        if _is_directive(tokens, start, ".include"):
            self.keep_labels(file, number, text, tokens, start)
            self.include(file, number, tokens, start)
            return
        if self.defining is not None:
            self.read_body_line(file, number, text, tokens, start)
            return
        if _is_directive(tokens, start, ".macro"):
            self.keep_labels(file, number, text, tokens, start)
            self.begin_macro(file, number, tokens, start)
            return
        if _is_end_macro(tokens, start):
            self.end_macro(file, number, text, tokens, start)
            return
        if _is_directive(tokens, start, ".eqv"):
            self.define(file, number, text, tokens, start)
            expanded = text
        else:
            expanded, tokens = self.substitute(file, number, text, tokens)
            if self.call(file, number, expanded, tokens, start):
                return
        self.add_line(SourceLine(file, number, text, expanded, tuple(tokens), self.calls))

    def keep_labels(self, file: str, number: int, text: str,
                    tokens: list[Token], start: int) -> None:
        """Labels before a directive that replaces its line stay as a line (DEV-10)."""
        if start:
            head = text[:tokens[start].column - 1]
            self.add_line(SourceLine(file, number, head, head, tuple(tokens[:start]), self.calls))

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

    # -------------------------------------------------------------- macros

    def begin_macro(self, file: str, number: int, tokens: list[Token], start: int) -> None:
        macro, errors = parse_definition(tokens, start, SourceLoc(file, number, 0, self.calls))
        for column, message in errors:
            self.error(file, number, column, message)
        self.defining = macro

    def read_body_line(self, file: str, number: int, text: str,
                       tokens: list[Token], start: int) -> None:
        """A line of a macro body: kept as written until the macro is expanded."""
        if _is_directive(tokens, start, ".macro"):
            self.error(file, number, tokens[start].column, "Nested macros are not allowed")
            return
        if _is_end_macro(tokens, start):
            self.end_macro(file, number, text, tokens, start)
            return
        self.add_line(SourceLine(file, number, text, text, tuple(tokens)))

    def end_macro(self, file: str, number: int, text: str,
                  tokens: list[Token], start: int) -> None:
        directive = tokens[start]
        if [t for t in tokens[start + 1:] if t.kind is not Kind.COMMENT]:
            self.error(file, number, directive.column, "invalid text after .END_MACRO")
            return
        if self.defining is None:
            self.error(file, number, directive.column, ".END_MACRO without .MACRO")
            return
        self.keep_labels(file, number, text, tokens, start)
        self.macros.append(self.defining)
        self.defining = None

    def call(self, file: str, number: int, text: str, tokens: list[Token], start: int) -> bool:
        """Expand a macro call; False if the line is not one."""
        if start >= len(tokens) or tokens[start].kind is not Kind.IDENTIFIER:
            return False
        name = tokens[start]
        if not defined(self.macros, name.text):
            return False
        arguments = _arguments(tokens[start + 1:], text)
        if arguments is None:  # a missing operand: the parser reports it
            return False
        self.keep_labels(file, number, text, tokens, start)
        macro = find(self.macros, name.text, len(arguments))
        if macro is None:
            self.error(file, number, name.column,
                       f'forward reference or invalid parameters for macro "{name.text}"')
            return True
        self.expand(macro, file, number, name, dict(zip(macro.params, arguments)))
        return True

    def expand(self, macro: Macro, file: str, number: int, name: Token,
               arguments: dict[str, str]) -> None:
        """Read the body of the macro in place of its call (DEV-19: loops are an error)."""
        if macro in self.expanding:
            self.error(file, number, name.column,
                       "Detected a macro expansion loop (recursive reference). ")
            return
        counter = self.counter
        self.counter += 1
        outer = self.calls
        self.calls = outer + (SourceLoc(file, number, name.column),)
        self.expanding.append(macro)
        for body in macro.body:
            tokens = self.tokenize(body.text, body.file, body.line)
            text, unknown = substitute(body.text, tokens, arguments, macro.labels, counter)
            for token in unknown:
                self.error(body.file, body.line, token.column, "Unknown macro parameter")
            self.read_line(body.file, body.line, text)
        self.expanding.pop()
        self.calls = outer

    def finish(self) -> None:
        if self.defining is not None:
            self.add_error(Diagnostic("Error", self.defining.loc,
                                      "Macro started but not ended (no .end_macro directive)"))

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
