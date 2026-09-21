"""Lexer: splits one source line into tokens.

The token structure follows the RARS dialect (RARS: assembler/Tokenizer,
TokenTypes): delimiters, comments, strings, character literals, a sign
joining the following number, token kinds. Literal and name rules follow the
RISC-V assembler (asm manual; GNU as as reference). Approved deviations from
RARS:
  DEV-2  registers only by exact names: x0..x31, f0..f31, ABI names, fp
  DEV-4  numeric local label references "1b", "1f" (kind LOCAL_LABEL)
  DEV-5  integers: C/GNU literals with their exact value
  DEV-6  "+Inf" is +infinity
  DEV-7  a string ends at a quote preceded by an even number of backslashes
  DEV-8  "1f" is a label reference, not a real number
  D15    directives of the asm manual are recognized too; GNU macro parameters "\\name"
  DEV-9  no Java artifacts or RARS implementation hacks (skill D14): real
         numbers in C form without type suffixes, ASCII names, one token per
         malformed character literal, an exponent sign joins only a number
         ("base-4" is base - 4; RARS: invalid element "base-4")
.eqv substitution is not done here (see the source stage).
"""

import math
import re
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum, auto

from pyrars.asm.directives import DIRECTIVES
from pyrars.isa.program import Diagnostic, SourceLoc
from pyrars.isa.registers import CSRS, F_NAMES, ROUNDING_MODES, X_ALIASES, X_NAMES


class Kind(Enum):
    COMMENT = auto()
    DIRECTIVE = auto()
    OPERATOR = auto()  # instruction mnemonic (basic or pseudo)
    REGISTER_NAME = auto()  # "a0", "zero", "fp"
    REGISTER_NUMBER = auto()  # "x10"
    FP_REGISTER_NAME = auto()  # "fa0", "f10"
    CSR_NAME = auto()
    ROUNDING_MODE = auto()
    IDENTIFIER = auto()
    LOCAL_LABEL = auto()  # "1b", "1f" (DEV-4)
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    INTEGER = auto()
    REAL_NUMBER = auto()
    QUOTED_STRING = auto()  # text with its quotes, escapes not decoded
    PLUS = auto()
    MINUS = auto()
    COLON = auto()
    HI = auto()  # %hi
    LO = auto()  # %lo
    MACRO_PARAMETER = auto()  # "%name" (RARS) or "\\name" (GNU .macro)
    ERROR = auto()


@dataclass(frozen=True)
class Token:
    kind: Kind
    text: str  # a character literal is replaced by its code: 'a' -> "97" (as RARS)
    column: int  # 1-based column of the first character
    value: int | float | None = None  # INTEGER, REAL_NUMBER, registers, CSR, rounding mode, LOCAL_LABEL


def tokenize_line(text: str, operators: Collection[str],
                  file: str = "", line: int = 0) -> tuple[list[Token], list[Diagnostic]]:
    """Tokens of one source line and the errors found.

    operators - instruction mnemonics in lower case; they are matched ignoring case.
    file, line - where the line comes from, for the error messages.
    """
    lexer = _LineLexer(text, operators, file, line)
    lexer.run()
    return lexer.tokens, lexer.errors


# ---------------------------------------------------------------- literals

_INTEGER = re.compile(r"([+-]?)(?:0[xX]([0-9a-fA-F]+)|(0[0-7]*)|([1-9][0-9]*))")
_REAL = re.compile(r"""[+-]?(?:
      (?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?                     # 1.5  1.  .5  1.5e-3
    | [0-9]+[eE][+-]?[0-9]+                                               # 1e3
    | 0[xX](?:[0-9a-fA-F]+\.?|[0-9a-fA-F]*\.[0-9a-fA-F]+)[pP][+-]?[0-9]+  # 0x1.8p1
)""", re.X)
# A real number up to its exponent sign: "1.5e" in "1.5e-3", "0x1p" in "0x1p-2"
_MANTISSA = re.compile(r"[+-]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)[eE]|0[xX](?:[0-9a-fA-F]+\.?|[0-9a-fA-F]*\.[0-9a-fA-F]+)[pP])")
_LOCAL_LABEL = re.compile(r"([0-9]+)[bf]")
_NAME = re.compile(r"[A-Za-z_.$][A-Za-z0-9_.$]*")
_CHARACTER = re.compile(r"'(?:\\[0-7]{3}|\\.|[^'\\])'")  # 'c', '\e' or '\ooo'
# Escapes of character literals (RARS): \' \" \\ \n \t \b \r \f \0
_ESCAPES = {"'": 39, '"': 34, "\\": 92, "n": 10, "t": 9, "b": 8, "r": 13, "f": 12, "0": 0}


def parse_integer(text: str) -> int | None:
    """Value of an integer literal with an optional sign, or None.

    Decimal, octal with a leading 0, hexadecimal with 0x (GNU as "Integers").
    The value is exact; its range is checked where it is used.
    """
    match = _INTEGER.fullmatch(text)
    if not match:
        return None
    sign, hex_digits, octal, decimal = match.groups()
    if hex_digits is not None:
        value = int(hex_digits, 16)
    elif octal is not None:
        value = int(octal, 8)
    else:
        value = int(decimal)
    return -value if sign == "-" else value


def parse_real(text: str) -> float | None:
    """Value of a floating point literal in C form (asm manual), or None."""
    if not _REAL.fullmatch(text):
        return None
    return float.fromhex(text) if "x" in text.lower() else float(text)


def _character_code(literal: str) -> int | None:
    """Code of a literal matched by _CHARACTER, or None if the escape is unknown or > 255."""
    inner = literal[1:-1]
    if inner[0] != "\\":
        return ord(inner)
    if len(inner) == 4:
        code = int(inner[1:], 8)
        return code if code <= 255 else None
    return _ESCAPES.get(inner[1])


# ---------------------------------------------------------- classification

_X_REGISTERS = {f"x{n}": n for n in range(32)} | {name: n for n, name in enumerate(X_NAMES)} | X_ALIASES
_F_REGISTERS = {f"f{n}": n for n in range(32)} | {name: n for n, name in enumerate(F_NAMES)}
_SINGLE = {"(": Kind.LEFT_PAREN, ")": Kind.RIGHT_PAREN, ":": Kind.COLON, "+": Kind.PLUS, "-": Kind.MINUS}


def _classify(word: str, operators: Collection[str]) -> tuple[Kind, int | float | None]:
    """Kind and value of a word (RARS TokenTypes.matchTokenType order)."""
    if word == "%hi":
        return Kind.HI, None
    if word == "%lo":
        return Kind.LO, None
    if word in ROUNDING_MODES:
        return Kind.ROUNDING_MODE, ROUNDING_MODES[word]
    if (len(word) > 1 and word[0] == "%") or (word[0] == "\\" and _NAME.fullmatch(word[1:])):
        return Kind.MACRO_PARAMETER, None
    if word in _X_REGISTERS:
        kind = Kind.REGISTER_NUMBER if word[0] == "x" else Kind.REGISTER_NAME
        return kind, _X_REGISTERS[word]
    if word in _F_REGISTERS:
        return Kind.FP_REGISTER_NAME, _F_REGISTERS[word]
    if word in CSRS:
        return Kind.CSR_NAME, CSRS[word]
    integer = parse_integer(word)
    if integer is not None:
        return Kind.INTEGER, integer
    local = _LOCAL_LABEL.fullmatch(word)
    if local:
        return Kind.LOCAL_LABEL, int(local[1])
    if word in ("Inf", "NaN"):  # RARS words for infinity and not-a-number
        return Kind.REAL_NUMBER, math.inf if word == "Inf" else math.nan
    real = parse_real(word)
    if real is not None:
        return Kind.REAL_NUMBER, real
    if word[0] == "." and word.lower() in DIRECTIVES:
        return Kind.DIRECTIVE, None
    if word.lower() in operators:
        return Kind.OPERATOR, None
    if _NAME.fullmatch(word):
        return Kind.IDENTIFIER, None
    return Kind.ERROR, None


# ------------------------------------------------------------------ scanning


class _LineLexer:
    """Scans a line left to right; `chars` collects the current word, `start` is its column."""

    def __init__(self, text: str, operators: Collection[str], file: str, line: int) -> None:
        self.text = text
        self.operators = operators
        self.file = file
        self.line = line
        self.tokens: list[Token] = []
        self.errors: list[Diagnostic] = []
        self.chars: list[str] = []
        self.start = 1
        self.pos = 0

    def error(self, column: int, message: str) -> None:
        self.errors.append(Diagnostic("Error", SourceLoc(self.file, self.line, column), message))

    def add(self, kind: Kind, text: str, column: int, value: int | float | None = None) -> None:
        if kind is Kind.ERROR:
            self.error(column, f"{self.text}\nInvalid language element: {text}")
        self.tokens.append(Token(kind, text, column, value))

    def emit(self) -> None:
        """Classify and record the current word, if any."""
        if self.chars:
            word = "".join(self.chars)
            self.chars = []
            kind, value = _classify(word, self.operators)
            self.add(kind, word, self.start, value)

    def run(self) -> None:
        text = self.text
        while self.pos < len(text):
            c = text[self.pos]
            if c == "#":  # comment: the rest of the line
                self.emit()
                self.add(Kind.COMMENT, text[self.pos:], self.pos + 1)
                return
            if c in " \t,":
                self.emit()
            elif c in "+-":
                self.sign(c)
            elif c in ":()":
                self.emit()
                self.add(_SINGLE[c], c, self.pos + 1)
            elif c == '"':
                self.string()
            elif c == "'":
                self.character()
            else:
                if not self.chars:
                    self.start = self.pos + 1
                self.chars.append(c)
            self.pos += 1
        self.emit()

    def sign(self, c: str) -> None:
        """+ or -: part of a number, "-Inf"/"+Inf", or an operator token."""
        text, pos = self.text, self.pos
        next_is_digit = pos + 1 < len(text) and "0" <= text[pos + 1] <= "9"
        if next_is_digit and _MANTISSA.fullmatch("".join(self.chars)):  # exponent: 1.2e-5
            self.chars.append(c)
            return
        self.emit()
        if text[pos + 1:pos + 4] == "Inf":
            self.add(Kind.REAL_NUMBER, c + "Inf", pos + 1, -math.inf if c == "-" else math.inf)
            self.pos += 3
            return
        after_name = bool(self.tokens) and self.tokens[-1].kind in (Kind.IDENTIFIER, Kind.LOCAL_LABEL)
        if after_name or not next_is_digit:  # binary operator: label+4, a - b
            self.add(_SINGLE[c], c, pos + 1)
        else:  # the sign starts a number
            self.start = pos + 1
            self.chars = [c]

    def string(self) -> None:
        """A string: up to a quote preceded by an even number of backslashes (DEV-7)."""
        self.emit()
        text, start = self.text, self.pos
        end = start + 1
        while end < len(text) and not (text[end] == '"' and _even_backslashes_before(text, end)):
            end += 1
        if end == len(text):
            self.error(start + 1, "String is not terminated.")
            end -= 1
        self.add(Kind.QUOTED_STRING, text[start:end + 1], start + 1)
        self.pos = end

    def character(self) -> None:
        """A character literal becomes an INTEGER token with its code as text (RARS).

        Anything else starting with a quote is one ERROR token up to the next
        delimiter (DEV-9).
        """
        self.emit()
        text, start = self.text, self.pos
        match = _CHARACTER.match(text, start)
        code = _character_code(match[0]) if match else None
        if code is not None:
            self.add(Kind.INTEGER, str(code), start + 1, code)
            self.pos = match.end() - 1
            return
        end = match.end() if match else start + 1
        while end < len(text) and text[end] not in " \t,#":
            end += 1
        self.add(Kind.ERROR, text[start:end], start + 1)
        self.pos = end - 1


def _even_backslashes_before(text: str, pos: int) -> bool:
    count = 0
    while text[pos - 1 - count] == "\\":  # stops at the opening quote at the latest
        count += 1
    return count % 2 == 0
