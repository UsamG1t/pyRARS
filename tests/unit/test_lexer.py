"""Lexer rules: RARS token kinds, RISC-V/GNU literal and operand rules, approved deviations (DEV-*)."""

import math

import pytest

from pyrars.asm.lexer import Kind, parse_integer, parse_real, tokenize_line

OPERATORS = {"addi", "lw", "beq", "la", "li", "j"}
K = Kind


def tokens(line):
    result, errors = tokenize_line(line, OPERATORS)
    assert errors == [], errors
    return result


def kinds(line):
    return [(t.kind, t.text) for t in tokens(line)]


def test_statement():
    assert kinds("main:  addi t0, x5,-4  # add") == [
        (K.IDENTIFIER, "main"), (K.COLON, ":"), (K.OPERATOR, "addi"), (K.REGISTER_NAME, "t0"),
        (K.COMMA, ","), (K.REGISTER_NUMBER, "x5"), (K.COMMA, ","), (K.EXPR_OP, "-"), (K.INTEGER, "4"),
        (K.COMMENT, "# add"),
    ]


def test_columns_are_1_based_and_count_a_tab_as_one():
    assert [t.column for t in tokens("\tlw a0, 8(sp)")] == [2, 5, 7, 9, 10, 11, 13]


def test_memory_operand_and_hi_lo():
    assert kinds("lw a0, %lo(x)(sp)") == [
        (K.OPERATOR, "lw"), (K.REGISTER_NAME, "a0"), (K.COMMA, ","), (K.LO, "%lo"), (K.LEFT_PAREN, "("),
        (K.IDENTIFIER, "x"), (K.RIGHT_PAREN, ")"), (K.LEFT_PAREN, "("), (K.REGISTER_NAME, "sp"),
        (K.RIGHT_PAREN, ")"),
    ]


# -------------------------------------------------------- expression operators


def test_every_expression_operator():  # DEV-12, DEV-16
    ops = "<< >> <= >= == != <> && || + - * / % < > | & ^ ! ~"
    assert kinds(ops) == [(K.EXPR_OP, op) for op in ops.split()]


def test_operators_without_blanks():
    assert kinds("a+4*(b-1)<<2") == [
        (K.IDENTIFIER, "a"), (K.EXPR_OP, "+"), (K.INTEGER, "4"), (K.EXPR_OP, "*"), (K.LEFT_PAREN, "("),
        (K.IDENTIFIER, "b"), (K.EXPR_OP, "-"), (K.INTEGER, "1"), (K.RIGHT_PAREN, ")"), (K.EXPR_OP, "<<"),
        (K.INTEGER, "2"),
    ]


def test_a_sign_is_always_an_operator():  # DEV-16: RARS joins "-4" into one number
    assert kinds("-4 4-4 -x") == [
        (K.EXPR_OP, "-"), (K.INTEGER, "4"), (K.INTEGER, "4"), (K.EXPR_OP, "-"), (K.INTEGER, "4"),
        (K.EXPR_OP, "-"), (K.IDENTIFIER, "x"),
    ]
    assert kinds("-Inf") == [(K.EXPR_OP, "-"), (K.REAL_NUMBER, "Inf")]


def test_percent_before_a_letter_starts_a_word():
    assert kinds("%hi %arg 10%3 a%b %(1)") == [
        (K.HI, "%hi"), (K.MACRO_PARAMETER, "%arg"), (K.INTEGER, "10"), (K.EXPR_OP, "%"), (K.INTEGER, "3"),
        (K.IDENTIFIER, "a"), (K.EXPR_OP, "%"), (K.IDENTIFIER, "b"), (K.EXPR_OP, "%"), (K.LEFT_PAREN, "("),
        (K.INTEGER, "1"), (K.RIGHT_PAREN, ")"),
    ]


def test_exponent_sign_stays_in_the_number():
    assert kinds("1.5e-3 1e+3 0x1p-2") == [(K.REAL_NUMBER, "1.5e-3"), (K.REAL_NUMBER, "1e+3"),
                                            (K.REAL_NUMBER, "0x1p-2")]


def test_sign_after_a_name_ending_with_e_is_an_operator():  # DEV-9: RARS reads "base-4" as one word
    assert kinds("la t0, base-4")[-3:] == [(K.IDENTIFIER, "base"), (K.EXPR_OP, "-"), (K.INTEGER, "4")]


def test_commas_are_tokens():  # DEV-16
    assert kinds(",,") == [(K.COMMA, ","), (K.COMMA, ",")]


# ------------------------------------------------------------- integers


@pytest.mark.parametrize("text, value", [
    ("0", 0), ("7", 7), ("2147483647", 2**31 - 1),
    ("010", 8), ("0777", 511),  # octal
    ("9999999999", 9999999999),  # DEV-5: RARS overflows to 0x540BE3FF
    ("4294967295", 4294967295),
    ("0x7ff", 2047), ("0X7FF", 2047),
    ("0xFFFFFFFF", 4294967295), ("0x80000000", 2**31),  # DEV-5: RARS wraps to -1, -2**31
    ("0xFFFFFFFFFFFFFFFF", 2**64 - 1),  # DEV-5: RARS makes it -1
    ("9223372036854775808", 2**63),  # exact, range is checked where the value is used
])
def test_integer_values(text, value):
    assert parse_integer(text) == value
    assert tokens(".word " + text)[1].value == value


@pytest.mark.parametrize("text", ["08", "0x", "1_0", "0b101", "٣", "1.5", "-7", "+7"])
def test_not_integers(text):
    assert parse_integer(text) is None


# ---------------------------------------------------------------- reals


@pytest.mark.parametrize("text, value", [
    ("1.5", 1.5), (".5", 0.5), ("5.", 5.0), ("1e3", 1000.0), ("1.5e-3", 0.0015),
    ("08.5", 8.5), ("0x1.8p1", 3.0), ("0x.8p0", 0.5), ("0X1P-2", 0.25),
])
def test_real_values(text, value):
    token = tokens(".double " + text)[1]
    assert (token.kind, token.value) == (K.REAL_NUMBER, value)


def test_infinity_and_nan_words():
    inf, nan = tokens(".double Inf, NaN")[1::2]
    assert inf.value == math.inf and math.isnan(nan.value)


def test_parse_real_rejects():
    # C forms only (DEV-9): no type suffixes, no "Infinity", no "08"; a sign is an operator
    for text in ["1e", "1.2.3", "e5", "0x1.8", "1.5f", "2d", "1F", "08", "5", "Infinity", "NaN", "-2.5"]:
        assert parse_real(text) is None, text


# ----------------------------------------------------- character literals


@pytest.mark.parametrize("literal, code", [
    ("'a'", 97), ("' '", 32), ("'#'", 35), ("','", 44),
    (r"'\''", 39), (r"'\"'", 34), (r"'\\'", 92), (r"'\n'", 10), (r"'\t'", 9),
    (r"'\b'", 8), (r"'\r'", 13), (r"'\f'", 12), (r"'\0'", 0),
    (r"'\101'", 65), (r"'\377'", 255),
])
def test_character_literals_are_integers(literal, code):
    token = tokens(".byte " + literal)[1]
    assert (token.kind, token.text, token.value) == (K.INTEGER, str(code), code)


# ---------------------------------------------------------------- strings


def test_string_keeps_quotes_and_escapes():
    assert kinds(r'.asciz "a, #b\"c" # x') == [
        (K.DIRECTIVE, ".asciz"), (K.QUOTED_STRING, r'"a, #b\"c"'), (K.COMMENT, "# x"),
    ]


def test_string_ending_with_escaped_backslash():  # DEV-7
    assert kinds(r'.asciz "a\\" 5') == [(K.DIRECTIVE, ".asciz"), (K.QUOTED_STRING, r'"a\\"'), (K.INTEGER, "5")]


# -------------------------------------------------------- names and words


@pytest.mark.parametrize("name, number", [("x0", 0), ("x31", 31), ("zero", 0), ("sp", 2),
                                          ("fp", 8), ("s0", 8), ("t6", 31)])
def test_integer_registers(name, number):
    token = tokens(name)[0]
    kind = K.REGISTER_NUMBER if name.startswith("x") else K.REGISTER_NAME
    assert (token.kind, token.value) == (kind, number)


@pytest.mark.parametrize("name, number", [("f0", 0), ("f31", 31), ("ft0", 0), ("fa0", 10), ("ft11", 31)])
def test_fp_registers(name, number):
    assert tokens(name)[0].value == number
    assert tokens(name)[0].kind is K.FP_REGISTER_NAME


@pytest.mark.parametrize("name", ["x05", "x010", "x0x1f", "x32", "f05", "f0x1f", "f32", "X5", "SP"])
def test_not_registers(name):  # DEV-2: only exact names
    assert tokens(name)[0].kind is K.IDENTIFIER


def test_csr_names_and_rounding_modes():
    assert [(t.kind, t.value) for t in tokens("fcsr instreth rne dyn")] == [
        (K.CSR_NAME, 3), (K.CSR_NAME, 0xC82), (K.ROUNDING_MODE, 0), (K.ROUNDING_MODE, 7),
    ]


def test_directives_and_operators_ignore_case():
    assert kinds(".DATA .Word ADDI Lw .foo") == [
        (K.DIRECTIVE, ".DATA"), (K.DIRECTIVE, ".Word"), (K.OPERATOR, "ADDI"), (K.OPERATOR, "Lw"),
        (K.IDENTIFIER, ".foo"),
    ]


def test_identifiers():
    assert kinds("_x $y a.b1 .L2") == [
        (K.IDENTIFIER, "_x"), (K.IDENTIFIER, "$y"), (K.IDENTIFIER, "a.b1"), (K.IDENTIFIER, ".L2"),
    ]


@pytest.mark.parametrize("word", ["éclair", "1.5f", "08", "1F", "@t"])
def test_words_that_are_not_tokens(word):  # DEV-9: ASCII names, C literals; no RARS TAG
    result, errors = tokenize_line(word, OPERATORS)
    assert [t.kind for t in result] == [K.ERROR] and len(errors) == 1


def test_local_labels():  # DEV-4, DEV-8
    assert [(t.kind, t.value) for t in tokens("1b 12f 1f")] == [
        (K.LOCAL_LABEL, 1), (K.LOCAL_LABEL, 12), (K.LOCAL_LABEL, 1),
    ]
    assert kinds("1:") == [(K.INTEGER, "1"), (K.COLON, ":")]


def test_macro_parameter():
    assert kinds(r"%arg %hi \arg") == [(K.MACRO_PARAMETER, "%arg"), (K.HI, "%hi"), (K.MACRO_PARAMETER, r"\arg")]


def test_directives_of_the_asm_manual():  # D15
    words = (".p2align .balign .2byte .short .4byte .long .8byte .quad .zero .sleb128 .uleb128 .equ .endm "
             ".rodata .bss .local .comm .common .insn .option")
    assert {t.kind for t in tokens(words)} == {K.DIRECTIVE}
    assert len(tokens(words)) == 20


# ----------------------------------------------------------------- errors


@pytest.mark.parametrize("line, errors", [
    (".word 1.2.3", [(7, "1.2.3")]),
    (".word 'ab'", [(7, "'ab'")]),
    (".word ''", [(7, "''")]),  # DEV-9: RARS reports "'" twice
    (".word 'a", [(7, "'a")]),
    (".word 'a, 5", [(7, "'a")]),
    (r".word '\q'", [(7, r"'\q'")]),
    (r".word '\400'", [(7, r"'\400'")]),
    ("\t.word 1e", [(8, "1e")]),
    (".word 0x", [(7, "0x")]),
    (".word a = 1", [(9, "=")]),
])
def test_invalid_language_element(line, errors):
    result, found = tokenize_line(line, OPERATORS, "p.s", 3)
    assert K.ERROR in [t.kind for t in result]
    assert [(e.kind, e.loc.file, e.loc.line, e.loc.column, e.message) for e in found] == [
        ("Error", "p.s", 3, column, f"{line}\nInvalid language element: {token}") for column, token in errors
    ]


def test_unterminated_string():
    result, errors = tokenize_line('.asciz "open', OPERATORS, "p.s", 2)
    assert result[-1].kind is K.QUOTED_STRING
    assert [(e.loc.column, e.message) for e in errors] == [(8, "String is not terminated.")]


def test_empty_line():
    assert tokenize_line("", OPERATORS) == ([], [])
    assert tokenize_line("  \t ", OPERATORS) == ([], [])
