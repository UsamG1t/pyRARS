"""pyrars.asm.lexer reads literals and reports lexical errors as RARS does.

1. Literal values: RARS stores each literal with .dword / .double; the stored
   words must equal our token values.
2. Lexical errors: same line, column and text as RARS (RARS tokenizes every
   line twice and prints each error twice; duplicates are dropped).
3. Approved deviations DEV-5..DEV-9: RARS still behaves as recorded in the
   skill, so our different result is deliberate.
"""

import math
import struct

import pytest

from pyrars.asm.lexer import Kind, tokenize_line
from pyrars.isa.instructions import INSTRUCTIONS

pytestmark = pytest.mark.devel

OPERATORS = {i.mnemonic for i in INSTRUCTIONS}

INTEGERS = [
    "0", "7", "-7", "+7", "2147483647", "-2147483648", "2147483648", "-2147483649",
    "010", "0777", "4294967295", "0x7ff", "0X7FF", "-0x800", "0x7FFFFFFF",
    "-0xFFFFFFFF", "+0xFFFFFFFF", "0x0FFFFFFFF", "0xFFFFFFFFFFFFFFFF", "0x7FFFFFFFFFFFFFFF",
    "9223372036854775807", "-9223372036854775808",
    "'a'", "' '", "'#'", r"'\''", r"'\"'", r"'\\'", r"'\n'", r"'\t'", r"'\b'", r"'\r'",
    r"'\f'", r"'\0'", r"'\101'", r"'\377'",
]

REALS = [
    "1.5", ".5", "5.", "1e3", "1e+3", "1.5e-3", "-2.5", "1E10", "08.5", "0x1.8p1", "0x1p2",
    "3.141592653589793", "1e-320", "1.7976931348623157e308", "Inf", "-Inf", "NaN",
]


def data_words(rars, tmp_path, lines):
    source = tmp_path / "data.s"
    source.write_text(".data\n" + "\n".join(lines) + "\n")
    result = rars.assemble([source])
    assert result.messages == []
    return result.data


def token_value(text):
    tokens, errors = tokenize_line(".dword " + text, OPERATORS)
    assert errors == []
    return tokens[1].value


def words_of(bits64):
    return [bits64 & 0xFFFFFFFF, (bits64 >> 32) & 0xFFFFFFFF]


def test_integer_literals(rars, tmp_path):
    words = data_words(rars, tmp_path, [f".dword {text}" for text in INTEGERS])
    for n, text in enumerate(INTEGERS):
        assert words[2 * n:2 * n + 2] == words_of(token_value(text)), text


def test_real_literals(rars, tmp_path):
    words = data_words(rars, tmp_path, [f".double {text}" for text in REALS])
    for n, text in enumerate(REALS):
        bits = struct.unpack("<Q", struct.pack("<d", token_value(text)))[0]
        assert words[2 * n:2 * n + 2] == words_of(bits), text


ERROR_LINES = [
    ".word 1.2.3",
    ".word %",
    ".word 'ab'",
    r".word '\q'",
    r".word '\400'",
    "\t.word 1e",
    "addi t0, t0, 1 ^",
    ".word 0x",
    ".word 1, 2 ~ 3",
    '.asciz "open',
]


def test_lexical_errors(rars, tmp_path):
    source = tmp_path / "errors.s"
    source.write_text("\n".join(ERROR_LINES) + "\n")

    result = rars.assemble([source])

    theirs = sorted({(m.line, m.column, m.text) for m in result.messages})
    ours = []
    for number, line in enumerate(ERROR_LINES, start=1):
        ours += [(e.loc.line, e.loc.column, e.message)
                 for e in tokenize_line(line, OPERATORS, str(source), number)[1]]
    assert sorted(ours) == theirs
    assert {m.kind for m in result.messages} == {"Error"}


def bits(real):
    return struct.unpack("<Q", struct.pack("<d", real))[0]


def rars_messages(rars, tmp_path, text):
    source = tmp_path / "dev.s"
    source.write_text(text)
    return sorted({(m.line, m.column, m.text) for m in rars.assemble([source]).messages})


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    # DEV-5: RARS reads "-010" as -10, overflows "9999999999", wraps 8-digit hex to 32 bits
    words = data_words(rars, tmp_path, [".dword -010", ".dword 9999999999", ".dword 0xFFFFFFFF"])
    assert words[:6] == (words_of(-10 & (2**64 - 1)) + words_of(9999999999 & 0xFFFFFFFF)
                         + words_of(2**64 - 1))
    assert (token_value("-010"), token_value("9999999999"), token_value("0xFFFFFFFF")) == (
        -8, 9999999999, 0xFFFFFFFF)

    # DEV-6: RARS stores "+Inf" as -infinity
    assert data_words(rars, tmp_path, [".double +Inf"])[:2] == words_of(bits(-math.inf))
    assert token_value("+Inf") == math.inf

    # DEV-8: RARS reads "1f" as the real number 1.0
    assert data_words(rars, tmp_path, [".double 1f"])[:2] == words_of(bits(1.0))
    assert tokenize_line("1f", OPERATORS)[0][0].kind is Kind.LOCAL_LABEL

    # DEV-7: RARS does not see the end of "a\\"
    assert rars_messages(rars, tmp_path, '.data\n.asciz "a\\\\"\n') == [(2, 8, "String is not terminated.")]
    assert tokenize_line(r'.asciz "a\\"', OPERATORS)[1] == []


def test_rars_java_artifacts_we_drop(rars, tmp_path):  # DEV-9
    # Java Double.parseDouble: "08" and type suffixes are reals in RARS
    assert data_words(rars, tmp_path, [".double 08", ".double 1.5f"])[:4] == (
        words_of(bits(8.0)) + words_of(bits(1.5)))
    assert [tokenize_line(w, OPERATORS)[0][0].kind for w in ("08", "1.5f")] == [Kind.ERROR, Kind.ERROR]

    # Java Character.isLetter: non-ASCII labels
    assert rars_messages(rars, tmp_path, ".data\néclair: .word 1\n") == []
    assert tokenize_line("éclair", OPERATORS)[0][0].kind is Kind.ERROR

    # RARS character literal look-ahead: '' is reported as two quotes
    assert rars_messages(rars, tmp_path, ".data\n.word ''\n") == [
        (2, 7, ".word ''\nInvalid language element: '"), (2, 8, ".word ''\nInvalid language element: '")]
    assert [(e.loc.column, e.message) for e in tokenize_line(".word ''", OPERATORS)[1]] == [
        (7, ".word ''\nInvalid language element: ''")]

    # RARS exponent check looks at one character: "base-4" becomes one invalid word
    assert rars_messages(rars, tmp_path, ".data\nbase: .word 1\n.text\nla t0, base-4\n") == [
        (4, 8, "la t0, base-4\nInvalid language element: base-4")]
    assert [t.text for t in tokenize_line("la t0, base-4", OPERATORS | {"la"})[0]] == ["la", "t0", "base", "-", "4"]
    # ... and does not know the binary exponent of a hex real: "0x1p-2"
    assert rars_messages(rars, tmp_path, ".data\n.double 0x1p-2\n") == [
        (2, 9, ".double 0x1p-2\nInvalid language element: 0x1p")]
    assert token_value("0x1p-2") == 0.25
