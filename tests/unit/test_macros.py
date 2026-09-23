"""Macros: definition, expansion and errors (RARS rules plus DEV-17..DEV-21)."""

import pytest

from pyrars.asm.source import read_source

OPERATORS = {"addi", "add", "nop", "li", "j", "bnez", "lw"}


def write(directory, name, text):
    path = directory / name
    path.write_text(text)
    return path


def read(tmp_path, text, name="m.s"):
    """Lines and errors of a program; the text is written to a file first."""
    return read_source(str(write(tmp_path, name, text)), OPERATORS)


def expanded(lines):
    """(line number, call lines, text) of every line of the program."""
    return [(line.line, tuple(call.line for call in line.calls), line.expanded) for line in lines]


def messages(errors):
    return [(e.loc.line, tuple(c.line for c in e.loc.calls), e.loc.column, e.message)
            for e in errors]


# ----------------------------------------------------------------- expansion


def test_body_replaces_the_call(tmp_path):
    lines, errors = read(tmp_path, ".macro inc %r\n"
                                   "addi %r, %r, 1\n"
                                   "nop\n"
                                   ".end_macro\n"
                                   "inc t0\n"
                                   "inc t1\n")
    assert errors == []
    assert expanded(lines) == [(2, (5,), "addi t0, t0, 1"), (3, (5,), "nop"),
                               (2, (6,), "addi t1, t1, 1"), (3, (6,), "nop")]


def test_parameter_styles(tmp_path):
    lines, errors = read(tmp_path, ".macro m %a, \\b\n"
                                   "add %a, \\b, x0\n"
                                   ".end_macro\n"
                                   "m t0, t1\n")
    assert errors == []
    assert [line.expanded for line in lines] == ["add t0, t1, x0"]


def test_a_dollar_name_is_not_a_parameter(tmp_path):  # DEV-21
    lines, errors = read(tmp_path, ".macro m $a\nadd $a, $a, x0\n.end_macro\nm t0\n")
    assert messages(errors) == [
        (1, (), 10, "Invalid macro argument '$a'"),  # the macro has no parameters, so
        (4, (), 1, 'forward reference or invalid parameters for macro "m"')]  # the call has one
    assert [line.expanded for line in lines] == []  # the body belongs to the macro


def test_arguments_are_comma_separated_texts(tmp_path):  # DEV-18
    lines, errors = read(tmp_path, ".macro m %d, %s\n"
                                   "lw %d, %s\n"
                                   ".end_macro\n"
                                   "m t0, 4 * N(sp)\n"
                                   "m t1, -8(sp)\n")
    assert errors == []
    assert [line.expanded for line in lines] == ["lw t0, 4 * N(sp)", "lw t1, -8(sp)"]


def test_parentheses_are_part_of_the_argument(tmp_path):  # DEV-18: no SPIM-style call
    lines, _ = read(tmp_path, ".macro m %a\naddi %a, %a, 1\n.end_macro\nm(t0)\n")
    assert [line.expanded for line in lines] == ["addi (t0), (t0), 1"]


def test_labels_of_the_body_get_the_number_of_the_expansion(tmp_path):
    lines, errors = read(tmp_path, ".macro m %r\n"
                                   "start: end: addi %r, %r, -1\n"
                                   "bnez %r, start\n"
                                   "1: j 1b\n"
                                   ".end_macro\n"
                                   "m t0\n"
                                   "m t1\n")
    assert errors == []
    assert [line.expanded for line in lines] == [
        "start_M0: end_M0: addi t0, t0, -1", "bnez t0, start_M0", "1: j 1b",
        "start_M1: end_M1: addi t1, t1, -1", "bnez t1, start_M1", "1: j 1b"]


def test_labels_of_nested_expansions(tmp_path):
    lines, errors = read(tmp_path, ".macro inner\n"
                                   "i: j i\n"
                                   ".end_macro\n"
                                   ".macro outer\n"
                                   "inner\n"
                                   "o: j o\n"
                                   ".end_macro\n"
                                   "outer\n"
                                   "outer\n")
    assert errors == []
    assert expanded(lines) == [(2, (8, 5), "i_M1: j i_M1"), (6, (8,), "o_M0: j o_M0"),
                               (2, (9, 5), "i_M3: j i_M3"), (6, (9,), "o_M2: j o_M2")]


def test_labels_of_the_call_line_are_kept(tmp_path):
    lines, errors = read(tmp_path, ".macro m\nnop\n.end_macro\nhere: there: m\n")
    assert errors == []
    assert [(line.line, line.expanded) for line in lines] == [(4, "here: there: "), (2, "nop")]


def test_a_parameter_inside_a_string_is_not_substituted(tmp_path):  # RARS
    lines, _ = read(tmp_path, '.macro m %a\n.asciz "%a"\n.end_macro\nm 1\n')
    assert [line.expanded for line in lines] == ['.asciz "%a"']


def test_endm_ends_a_definition(tmp_path):  # D15 (GNU as)
    lines, errors = read(tmp_path, ".macro m\nnop\n.endm\nm\n")
    assert errors == [] and [line.expanded for line in lines] == ["nop"]


# ------------------------------------------------------- choosing the macro


def test_macros_of_the_same_name_differ_by_the_number_of_arguments(tmp_path):
    lines, errors = read(tmp_path, ".macro m %a\naddi %a, %a, 1\n.end_macro\n"
                                   ".macro m %a, %b\nadd %a, %a, %b\n.end_macro\n"
                                   "m t0\nm t0, t1\n")
    assert errors == []
    assert [line.expanded for line in lines] == ["addi t0, t0, 1", "add t0, t0, t1"]


def test_the_last_definition_wins(tmp_path):
    lines, errors = read(tmp_path, ".macro m\nnop\n.end_macro\n"
                                   ".macro m\naddi t0, t0, 1\n.end_macro\nm\n")
    assert errors == [] and [line.expanded for line in lines] == ["addi t0, t0, 1"]


def test_a_call_before_the_definition_stays_a_line(tmp_path):
    lines, errors = read(tmp_path, "m\n.macro m\nnop\n.end_macro\nm\n")
    assert errors == []  # the parser reports "m" as an unknown operator
    assert expanded(lines) == [(1, (), "m"), (3, (5,), "nop")]


def test_macros_come_from_the_included_files_of_the_program(tmp_path):
    write(tmp_path, "lib.s", ".macro m %r\naddi %r, %r, 1\n.end_macro\n")
    lines, errors = read(tmp_path, '.include "lib.s"\nm t0\n')
    assert errors == []
    assert [(line.file.rsplit("/", 1)[-1], line.expanded) for line in lines] == [("lib.s", "addi t0, t0, 1")]


def test_an_include_in_a_body_is_read_once(tmp_path):  # no "repeated include" warning
    write(tmp_path, "body.s", "nop\n")
    lines, errors = read(tmp_path, '.macro m\n.include "body.s"\nli t1, 2\n.end_macro\nm\nm\n')
    assert errors == []
    assert [(line.file.rsplit("/", 1)[-1], line.expanded) for line in lines] == [
        ("body.s", "nop"), ("m.s", "li t1, 2"), ("body.s", "nop"), ("m.s", "li t1, 2")]


# -------------------------------------------------------------------- .eqv


def test_the_body_sees_the_eqv_symbols_of_the_call(tmp_path):  # DEV-20
    lines, errors = read(tmp_path, ".macro m\naddi t0, t0, K\n.end_macro\n"
                                   ".eqv K, 2 + 3\nm\n")
    assert errors == []
    assert [line.expanded for line in lines] == [".eqv K, 2 + 3", "addi t0, t0, 2 + 3"]


def test_an_eqv_of_the_body_is_defined_at_every_expansion(tmp_path):
    lines, errors = read(tmp_path, ".macro m %v\n.eqv K, %v\naddi t0, t0, K\n.end_macro\nm 1\nm 2\n")
    assert [line.expanded for line in lines] == [".eqv K, 1", "addi t0, t0, 1",
                                                 ".eqv K, 2", "addi t0, t0, 1"]
    assert messages(errors) == [(2, (6,), 6, '"K" is already defined')]


# ------------------------------------------------------------------ errors


@pytest.mark.parametrize("text, expected", [
    (".macro\n", [(1, 1, '".macro" directive requires at least one argument.')]),
    (".macro 5\n", [(1, 8, 'Invalid Macro name "5"')]),
    (".macro add %a\n", [(1, 8, 'Invalid Macro name "add"')]),
    (".macro m a\n.end_macro\n", [(1, 10, "Invalid macro argument 'a'")]),
    (".macro m %a %b\n.end_macro\n", [(1, 13, 'Macro parameters must be separated by ","')]),
    (".macro m %a,\n.end_macro\n", [(1, 12, 'Missing macro parameter after ","')]),
    (".macro m\nnop\n.macro k\n.end_macro\n", [(3, 1, "Nested macros are not allowed")]),
    (".end_macro\n", [(1, 1, ".END_MACRO without .MACRO")]),
    (".macro m\n.end_macro nop\n", [(2, 1, "invalid text after .END_MACRO"),
                                    (1, 0, "Macro started but not ended (no .end_macro directive)")]),
    (".macro m\nnop\n", [(1, 0, "Macro started but not ended (no .end_macro directive)")]),
])
def test_definition_errors(tmp_path, text, expected):
    _, errors = read(tmp_path, text)
    assert messages(errors) == [(line, (), column, message) for line, column, message in expected]


def test_a_name_without_a_matching_number_of_arguments(tmp_path):
    _, errors = read(tmp_path, ".macro m %a\nnop\n.end_macro\nm t0, t1\n")
    assert messages(errors) == [(4, (), 1, 'forward reference or invalid parameters for macro "m"')]


def test_an_unknown_parameter_stays_in_the_line(tmp_path):
    lines, errors = read(tmp_path, ".macro m %a\nadd %a, %b, x0\n.end_macro\nm t0\n")
    assert [line.expanded for line in lines] == ["add t0, %b, x0"]
    assert messages(errors) == [(2, (4,), 9, "Unknown macro parameter")]


def test_an_expansion_loop_is_reported_at_the_repeated_call(tmp_path):  # DEV-19
    _, errors = read(tmp_path, ".macro a\nb\n.end_macro\n.macro b\na\n.end_macro\na\n")
    assert messages(errors) == [
        (5, (7, 2), 1, "Detected a macro expansion loop (recursive reference). ")]


def test_an_error_of_a_body_line_keeps_the_calls(tmp_path):
    _, errors = read(tmp_path, ".macro m\n@\n.end_macro\nm\n")
    assert [(e.loc.line, tuple(c.line for c in e.loc.calls)) for e in errors] == [(2, ()), (2, (4,))]
