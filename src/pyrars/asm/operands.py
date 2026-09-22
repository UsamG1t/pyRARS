"""Operands of an instruction statement, matched against a basic instruction.

Instr.syntax is split at commas into groups: a field name ("rd", "imm") or
the memory form "imm(rs1)" (an empty offset means 0). Registers, rounding
modes, CSR names and fence sets become numbers here; immediates stay
expressions until the assembler knows the symbols (field_value).

Messages follow RARS (DEV-14: "Expected:" shows the syntax with field names);
ranges are strict (DEV-13); fence sets may be letters (DEV-3).
"""

import re
from dataclasses import dataclass

from pyrars.asm.expressions import Expr, ExprError, evaluate, parse
from pyrars.asm.lexer import Kind, Token
from pyrars.asm.parser import Statement
from pyrars.isa.formats import B
from pyrars.isa.spec import Csr, Instr, Offset, Reg, RoundingMode, SImm

_X_REGISTER = (Kind.REGISTER_NAME, Kind.REGISTER_NUMBER)
_NOT_EXPRESSION = (*_X_REGISTER, Kind.FP_REGISTER_NAME, Kind.CSR_NAME, Kind.ROUNDING_MODE, Kind.QUOTED_STRING)
_FENCE_SET = re.compile(r"i?o?r?w?")
_FENCE_BITS = {"i": 8, "o": 4, "r": 2, "w": 1}


@dataclass(frozen=True)
class Operand:
    value: int | Expr  # a number, or an expression to evaluate
    text: str  # source text of the operand
    column: int


class OperandError(Exception):
    def __init__(self, column: int, message: str) -> None:
        super().__init__(message)
        self.column = column
        self.message = message


def expected(instr: Instr) -> str:
    return f"{instr.mnemonic} {instr.syntax}".rstrip()


def match_operands(statement: Statement, instr: Instr) -> dict[str, Operand]:
    """Operands of the statement by field name; raises OperandError."""
    name = statement.name
    patterns = [re.findall(r"[a-z][a-z0-9]*|[()]", group) for group in instr.syntax.split(",")] \
        if instr.syntax else []
    groups = statement.operands

    def format_error(too: str) -> OperandError:
        return OperandError(name.column, f'"{name.text}": Too {too} or incorrectly formatted operands. '
                                         f"Expected: {expected(instr)}")

    if len(groups) != len(patterns):
        raise format_error("few" if len(groups) < len(patterns) else "many")
    operands = {}
    for pattern, tokens in zip(patterns, groups):
        text = statement.line.expanded[tokens[0].column - 1:tokens[-1].end - 1]
        if len(pattern) == 4:  # imm ( rs1 )
            if len(tokens) < 3 or tokens[-3].kind is not Kind.LEFT_PAREN or tokens[-1].kind is not Kind.RIGHT_PAREN:
                raise format_error("few")
            base = tokens[-2]
            if base.kind not in _X_REGISTER:
                raise _incorrect_type(base)
            offset = tokens[:-3]
            operands[pattern[0]] = Operand(_expression(offset) if offset else 0, text, tokens[0].column)
            operands[pattern[2]] = Operand(base.value, base.text, base.column)
        else:
            operands[pattern[0]] = _single(instr, pattern[0], tokens, text, format_error)
    return operands


def _incorrect_type(token: Token) -> OperandError:
    return OperandError(token.column, f'"{token.text}": operand is of incorrect type')


def _expression(tokens: tuple[Token, ...]) -> Expr:
    if len(tokens) == 1 and tokens[0].kind in _NOT_EXPRESSION:
        raise _incorrect_type(tokens[0])
    try:
        return parse(tokens)
    except ExprError as e:
        raise OperandError(e.column, e.message) from None


def _single(instr: Instr, name: str, tokens: tuple[Token, ...], text: str, format_error) -> Operand:
    kind = instr.format.fields[name].kind
    token = tokens[0]
    if kind is Reg or kind is RoundingMode:
        if len(tokens) > 1:
            raise format_error("many")
        if kind is RoundingMode:
            wanted = (Kind.ROUNDING_MODE,)
        else:
            wanted = (Kind.FP_REGISTER_NAME,) if instr.is_fp(name) else _X_REGISTER
        if token.kind not in wanted:
            raise _incorrect_type(token)
        return Operand(token.value, text, token.column)
    if kind is Csr and len(tokens) == 1 and token.kind is Kind.CSR_NAME:
        return Operand(token.value, text, token.column)
    if name in ("pred", "succ") and len(tokens) == 1 and token.kind is Kind.IDENTIFIER \
            and _FENCE_SET.fullmatch(token.text):
        return Operand(sum(_FENCE_BITS[c] for c in token.text), text, token.column)
    return Operand(_expression(tokens), text, token.column)


def field_value(instr: Instr, name: str, operand: Operand, resolve, pc: int) -> int:
    """Value of the field `name` for an operand; raises OperandError or ExprError.

    resolve - gives the Value of a symbol or local label reference (see expressions.evaluate)
    pc - address of the instruction (for branch and jump offsets)
    """
    field = instr.format.fields[name]
    if isinstance(operand.value, int):
        return operand.value
    value = evaluate(operand.value, resolve)
    if field.kind is Offset:  # a branch or jump target: an address
        if value.segment is None:
            raise OperandError(operand.column, f'"{operand.text}": operand is of incorrect type')
        number = value.number - pc
        try:
            field.check(number)
        except ValueError:
            message = ("Branch target word address beyond 12-bit range" if instr.format is B
                       else "Jump target word address beyond 20-bit range")  # Offset exists only in B and J
            raise OperandError(operand.column, message) from None
        return number
    if value.segment is not None:
        raise OperandError(operand.column, f'"{operand.text}": operand is of incorrect type')
    try:
        field.check(value.number)
    except ValueError:
        if field.kind is SImm and field.width == 12 and 2048 <= value.number <= 4095:
            message = "Unsigned value is too large to fit into a sign-extended immediate"
        else:
            message = "operand is out of range"
        raise OperandError(operand.column, f'"{operand.text}": {message}') from None
    return value.number
