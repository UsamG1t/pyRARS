"""Integer expressions of operands and directive arguments (DEV-12).

Rules of GNU as ("Expressions", "Infix Ops", "Prefix Ops"):
- operands: integers (character literals are integers), symbols (labels,
  .equ constants), numeric local label references 1b/1f, parentheses;
- prefix operators - ~ ! + (GNU as gas/expr.c operand(): - negation,
  ~ bitwise not, ! logical not: !0 = 1, !x = 0, + nothing);
- binary operators, from the lowest to the highest precedence, equal
  precedence evaluated left to right:
      ||
      &&
      + - == <> != < > >= <=   (comparisons: signed, true = -1, false = 0)
      | & ^ !                  (a ! b = a | ~b)
      * / % << >>              (/ and % truncate like C)
- a value is a number or an address in a segment; an address allows only
  address + number, number + address, address - number and
  address - address of the same segment (a number);
- %hi(expr) / %lo(expr) may be the whole operand (RARS, asm manual).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pyrars.asm.lexer import Kind, Token


@dataclass(frozen=True)
class Value:
    number: int
    segment: str | None = None  # None: a plain number; else an address in this segment


class ExprError(Exception):
    def __init__(self, column: int, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


@dataclass(frozen=True)
class Number:
    value: int
    column: int


@dataclass(frozen=True)
class Symbol:
    name: str
    column: int


@dataclass(frozen=True)
class LocalRef:
    """Numeric local label reference: `1b` (backward) or `1f` (forward)."""

    number: int
    forward: bool
    column: int


@dataclass(frozen=True)
class Unary:
    op: str
    operand: "Expr"
    column: int


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Expr"
    right: "Expr"
    column: int


@dataclass(frozen=True)
class Reloc:
    """%hi(expr) or %lo(expr)."""

    function: str  # "hi" or "lo"
    operand: "Expr"
    column: int


type Expr = Number | Symbol | LocalRef | Unary | Binary | Reloc

# Binary operators by precedence, the lowest first.
_LEVELS = (
    ("||",),
    ("&&",),
    ("+", "-", "==", "<>", "!=", "<", ">", ">=", "<="),
    ("|", "&", "^", "!"),
    ("*", "/", "%", "<<", ">>"),
)


def parse(tokens: Sequence[Token]) -> Expr:
    """Expression of the tokens (all of them); raises ExprError."""
    if not tokens:
        raise ExprError(0, "Missing expression")
    parser = _Parser(tokens)
    if tokens[0].kind in (Kind.HI, Kind.LO):
        expr = parser.reloc()
    else:
        expr = parser.binary(0)
    if parser.pos < len(tokens):
        parser.unexpected()
    return expr


class _Parser:
    def __init__(self, tokens: Sequence[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def unexpected(self) -> None:
        token = self.peek()
        if token is None:
            raise ExprError(self.tokens[-1].column, "Incomplete expression")
        raise ExprError(token.column, f'"{token.text}": unexpected in expression')

    def expect(self, kind: Kind) -> Token:
        token = self.peek()
        if token is None or token.kind is not kind:
            self.unexpected()
        self.pos += 1
        return token

    def reloc(self) -> Reloc:
        function = self.tokens[self.pos]  # HI or LO
        self.pos += 1
        self.expect(Kind.LEFT_PAREN)
        operand = self.binary(0)
        self.expect(Kind.RIGHT_PAREN)
        return Reloc("hi" if function.kind is Kind.HI else "lo", operand, function.column)

    def binary(self, level: int) -> Expr:
        if level == len(_LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while (token := self.peek()) and token.kind is Kind.EXPR_OP and token.text in _LEVELS[level]:
            self.pos += 1
            left = Binary(token.text, left, self.binary(level + 1), token.column)
        return left

    def unary(self) -> Expr:
        token = self.peek()
        if token is not None and token.kind is Kind.EXPR_OP and token.text in ("-", "~", "!", "+"):
            self.pos += 1
            return Unary(token.text, self.unary(), token.column)
        return self.primary()

    def primary(self) -> Expr:
        token = self.peek()
        if token is None:
            self.unexpected()
        self.pos += 1
        if token.kind is Kind.INTEGER:
            return Number(token.value, token.column)
        if token.kind in (Kind.IDENTIFIER, Kind.OPERATOR):  # a label may be named like a mnemonic
            return Symbol(token.text, token.column)
        if token.kind is Kind.LOCAL_LABEL:
            return LocalRef(token.value, token.text.endswith("f"), token.column)
        if token.kind is Kind.LEFT_PAREN:
            expr = self.binary(0)
            if self.peek() is None or self.peek().kind is not Kind.RIGHT_PAREN:
                raise ExprError(token.column, '"(": missing ")"')
            self.pos += 1
            return expr
        self.pos -= 1
        self.unexpected()


# ---------------------------------------------------------------- evaluation


def evaluate(expr: Expr, resolve: Callable[[Symbol | LocalRef], Value]) -> Value:
    """Value of expr; resolve gives the value of a symbol or local label reference
    (or raises ExprError, e.g. for an undefined symbol)."""
    match expr:
        case Number(value):
            return Value(value)
        case Symbol() | LocalRef():
            return resolve(expr)
        case Unary(op, operand, column):
            value = evaluate(operand, resolve)
            if op == "+":
                return value
            number = _absolute(value, op, column)
            if op == "!":
                return Value(int(number == 0))
            return Value(-number if op == "-" else ~number)
        case Binary(op, left, right, column):
            return _binary(op, evaluate(left, resolve), evaluate(right, resolve), column)
        case Reloc(function, operand, column):
            number = evaluate(operand, resolve).number
            if function == "hi":
                return Value(((number + 0x800) >> 12) & 0xFFFFF)
            return Value(((number & 0xFFF) ^ 0x800) - 0x800)
    raise TypeError(expr)


def _absolute(value: Value, op: str, column: int) -> int:
    if value.segment is not None:
        raise ExprError(column, f'"{op}": invalid operation on an address')
    return value.number


def _binary(op: str, a: Value, b: Value, column: int) -> Value:
    if op == "+" and (a.segment is None or b.segment is None):
        return Value(a.number + b.number, a.segment or b.segment)
    if op == "-" and b.segment is None:
        return Value(a.number - b.number, a.segment)
    if op == "-" and a.segment == b.segment:
        return Value(a.number - b.number)
    x, y = _absolute(a, op, column), _absolute(b, op, column)
    match op:
        case "*":
            return Value(x * y)
        case "/" | "%":
            if y == 0:
                raise ExprError(column, f'"{op}": division by zero')
            quotient = abs(x) // abs(y) * (1 if (x < 0) == (y < 0) else -1)
            return Value(quotient if op == "/" else x - y * quotient)
        case "<<" | ">>":
            if y < 0:
                raise ExprError(column, f'"{op}": negative shift count')
            return Value(x << y if op == "<<" else x >> y)
        case "|":
            return Value(x | y)
        case "&":
            return Value(x & y)
        case "^":
            return Value(x ^ y)
        case "!":
            return Value(x | ~y)
        case "&&":
            return Value(int(bool(x) and bool(y)))
        case "||":
            return Value(int(bool(x) or bool(y)))
    comparisons = {"==": x == y, "<>": x != y, "!=": x != y, "<": x < y, ">": x > y, ">=": x >= y, "<=": x <= y}
    return Value(-1 if comparisons[op] else 0)
