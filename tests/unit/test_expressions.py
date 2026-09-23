"""Expressions: GNU as operators, precedence, addresses (DEV-12)."""

import pytest

from pyrars.asm.expressions import ExprError, LocalRef, Symbol, Value, evaluate, parse
from pyrars.asm.lexer import tokenize_line

SYMBOLS = {
    "a": Value(0x1000, "text"),
    "b": Value(0x1010, "text"),
    "d": Value(0x2000, "data"),
    "N": Value(16),
    "j": Value(3),  # a symbol named like a mnemonic
}


def resolve(ref):
    if isinstance(ref, LocalRef):
        return Value(0x1100 if ref.forward else 0x0F00, "text")
    if ref.name not in SYMBOLS:
        raise ExprError(ref.column, f'Symbol "{ref.name}" not found in symbol table.')
    return SYMBOLS[ref.name]


def expr(text):
    tokens, errors = tokenize_line(text, {"j"})
    assert errors == []
    return parse(tokens)


def value(text):
    return evaluate(expr(text), resolve)


@pytest.mark.parametrize("text, result", [
    ("7", 7), ("-7", -7), ("+7", 7), ("- -3", 3), ("~0", -1), ("'a' + 1", 98),
    ("!0", 1), ("!5", 0), ("!-1", 0), ("!!7", 1), ("2 ! !0", 2 | ~1),  # unary ! is logical not
    ("4 - -4", 8), ("2 * -3", -6), ("-(1 + 2)", -3),
    ("2 + 3 * 4", 14), ("(2 + 3) * 4", 20),
    ("1 | 2 + 3", 6),  # GNU as: | binds tighter than + (C: 5)
    ("1 << 2 + 1", 5),  # GNU as: << binds tighter than + (C: 8)
    ("3 == 1 + 2", 2),  # == and + have equal precedence, left to right: (3 == 1) + 2
    ("1 + 2 == 3", -1),
    ("10 - 4 - 3", 3), ("64 / 4 / 2", 8),
    ("-5 / 2", -2), ("5 / -2", -2), ("-5 % 2", -1), ("7 % -3", 1),  # C truncation
    ("6 ! 1", 6 | ~1), ("12 & 10", 8), ("12 ^ 10", 6), ("12 | 3", 15),
    ("1 << 40", 1 << 40), ("-16 >> 2", -4),
    ("3 < 5", -1), ("5 < 3", 0), ("-1 < 0", -1), ("2 >= 2", -1), ("2 <> 2", 0), ("2 != 3", -1),
    ("2 && 0", 0), ("2 || 0", 1), ("0 || 0", 0), ("1 || 1 && 0", 1), ("0 && 1 || 1", 1),
    ("N * 4 - 1", 63), ("j + 1", 4),
])
def test_numbers(text, result):
    assert value(text) == Value(result)


@pytest.mark.parametrize("text, result", [
    ("a", Value(0x1000, "text")),
    ("a + 4", Value(0x1004, "text")),
    ("4 + a", Value(0x1004, "text")),
    ("a - 4", Value(0x0FFC, "text")),
    ("a + N * 2", Value(0x1020, "text")),
    ("b - a", Value(16)),  # distance between addresses of the same segment is a number
    ("(b - a) * 2", Value(32)),
    ("1b", Value(0x0F00, "text")),
    ("2f + 8", Value(0x1108, "text")),
])
def test_addresses(text, result):
    assert value(text) == result


@pytest.mark.parametrize("text, column, message", [
    ("a * 2", 3, '"*": invalid operation on an address'),
    ("a + b", 3, '"+": invalid operation on an address'),
    ("a - d", 3, '"-": invalid operation on an address'),
    ("4 - a", 3, '"-": invalid operation on an address'),
    ("-a", 1, '"-": invalid operation on an address'),
    ("!a", 1, '"!": invalid operation on an address'),
    ("a == b", 3, '"==": invalid operation on an address'),
    ("1 / 0", 3, '"/": division by zero'),
    ("1 % (2 - 2)", 3, '"%": division by zero'),
    ("1 << -1", 3, '"<<": negative shift count'),
    ("x + 1", 1, 'Symbol "x" not found in symbol table.'),
])
def test_evaluation_errors(text, column, message):
    with pytest.raises(ExprError) as error:
        value(text)
    assert (error.value.column, error.value.message) == (column, message)


@pytest.mark.parametrize("text, column, message", [
    ("1 +", 3, "Incomplete expression"),
    ("(1 + 2", 1, '"(": missing ")"'),
    ("1 2", 3, '"2": unexpected in expression'),
    ("t0 + 1", 1, '"t0": unexpected in expression'),
    ("1.5", 1, '"1.5": unexpected in expression'),
    ('"s"', 1, '"\\"s\\"": unexpected in expression'),
    ("1 + %hi(a)", 5, '"%hi": unexpected in expression'),
    ("%hi a", 5, '"a": unexpected in expression'),
])
def test_syntax_errors(text, column, message):
    with pytest.raises(ExprError) as error:
        expr(text)
    assert (error.value.column, error.value.message) == (column, message.replace('\\"', '"'))


def test_empty():
    with pytest.raises(ExprError):
        parse([])


@pytest.mark.parametrize("text, result", [
    ("%hi(0x12345FFF)", 0x12346),  # +0x800 carries into the upper part
    ("%lo(0x12345FFF)", -1),
    ("%hi(0x12345678)", 0x12345),
    ("%lo(0x12345678)", 0x678),
    ("%hi(a + 4)", 0x1),
    ("%lo(a + 4)", 4),
    ("%hi(-1)", 0),
    ("%lo(-1)", -1),
])
def test_hi_lo(text, result):
    assert value(text) == Value(result)


def test_symbols_are_names_and_local_refs():
    assert expr("j") == Symbol("j", 1)
    assert expr("3f") == LocalRef(3, True, 1)
