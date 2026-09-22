"""Source stage: .include and .eqv (RARS rules plus DEV-10, DEV-11)."""

import pytest

from pyrars.asm.lexer import Kind
from pyrars.asm.source import read_source

OPERATORS = {"addi", "li", "lw"}


def write(directory, name, text):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())
    return path


def read(path):
    return read_source(str(path), OPERATORS)


def texts(lines):
    return [(line.file.rsplit("/", 1)[-1], line.line, line.expanded) for line in lines]


def messages(errors):
    return [(e.kind, e.loc.line, e.loc.column, e.message) for e in errors]


# ------------------------------------------------------------------ lines


def test_lines_keep_file_and_number(tmp_path):
    main = write(tmp_path, "m.s", "a\r\n\r\nb\n")
    lines, errors = read(main)
    assert errors == []
    assert [(line.file, line.line, line.text) for line in lines] == [
        (str(main), 1, "a"), (str(main), 2, ""), (str(main), 3, "b")]


def test_unreadable_main_file(tmp_path):
    lines, errors = read(tmp_path / "none.s")
    assert lines == [] and [e.message for e in errors] == [f"Error reading file {tmp_path / 'none.s'}"]


# --------------------------------------------------------------- .include


def test_include_inserts_lines_relative_to_the_including_file(tmp_path):
    write(tmp_path, "lib/b.s", "b1\n")
    write(tmp_path, "lib/a.s", 'a1\n.include "b.s"\na2\n')
    main = write(tmp_path, "m.s", 'm1\n  .INCLUDE "lib/a.s"   # comment\nm3\n')
    lines, errors = read(main)
    assert errors == []
    assert texts(lines) == [("m.s", 1, "m1"), ("a.s", 1, "a1"), ("b.s", 1, "b1"),
                            ("a.s", 3, "a2"), ("m.s", 3, "m3")]
    assert lines[1].file == str(tmp_path / "lib" / "a.s")


def test_label_before_include_is_kept(tmp_path):  # DEV-10
    write(tmp_path, "d.s", ".word 7\n")
    lines, errors = read(write(tmp_path, "m.s", 'start: .include "d.s"\n'))
    assert errors == []
    assert [[t.text for t in line.tokens] for line in lines] == [["start", ":"], [".word", "7"]]


def test_include_needs_a_quoted_name(tmp_path):
    lines, errors = read(write(tmp_path, "m.s", ".include d.s\n.include\n"))
    assert messages(errors) == [
        ("Error", 1, 1, 'The ".include" directive needs a file name in quotes'),
        ("Error", 2, 1, 'The ".include" directive needs a file name in quotes'),
    ]


def test_nothing_but_a_comment_after_the_name(tmp_path):  # DEV-10
    write(tmp_path, "d.s", "x\n")
    lines, errors = read(write(tmp_path, "m.s", '.include "d.s" 5\n'))
    assert messages(errors) == [("Error", 1, 16, 'Unexpected text after the ".include" file name')]
    assert lines == []


def test_include_only_as_the_statement_directive(tmp_path):  # DEV-10
    write(tmp_path, "d.s", "x\n")
    lines, errors = read(write(tmp_path, "m.s", 'addi t0, t0, 1 .include "d.s"\n'))
    assert errors == []
    assert texts(lines) == [("m.s", 1, 'addi t0, t0, 1 .include "d.s"')]


def test_missing_include_file(tmp_path):
    main = write(tmp_path, "m.s", '.include "none.s"\nnext\n')
    lines, errors = read(main)
    assert messages(errors) == [("Error", 1, 10, f"Error reading include file {tmp_path / 'none.s'}")]
    assert texts(lines) == [("m.s", 2, "next")]


def test_recursive_include(tmp_path):
    write(tmp_path, "a.s", 'a\n.include "b.s"\n')
    write(tmp_path, "b.s", 'b\n.include "a.s"\n')
    main = write(tmp_path, "m.s", '.include "a.s"\n')
    lines, errors = read(main)
    assert [(e.kind, e.loc.file, e.loc.line, e.message) for e in errors] == [
        ("Error", str(tmp_path / "b.s"), 2, f"Recursive include of file {tmp_path / 'a.s'}")]
    assert texts(lines) == [("a.s", 1, "a"), ("b.s", 1, "b")]


def test_file_including_itself(tmp_path):
    main = write(tmp_path, "m.s", 'x\n.include "m.s"\n')
    lines, errors = read(main)
    assert messages(errors) == [("Error", 2, 10, f"Recursive include of file {main}")]


def test_repeated_include_is_a_warning(tmp_path):  # DEV-10
    write(tmp_path, "d.s", "d\n")
    main = write(tmp_path, "m.s", '.include "d.s"\n.include "d.s"\n')
    lines, errors = read(main)
    assert messages(errors) == [("Warning", 2, 10, f"Repeated include of {tmp_path / 'd.s'}. "
                                                   "The convention for included files may be violated")]
    assert texts(lines) == [("d.s", 1, "d"), ("d.s", 1, "d")]


# ------------------------------------------------------------------- .eqv


def eqv(tmp_path, text):
    return read(write(tmp_path, "m.s", text))


def test_eqv_substitutes_following_lines(tmp_path):
    lines, errors = eqv(tmp_path, ".eqv R, t1\n.eqv N, -4\naddi R, R, N  # c\n")
    assert errors == []
    assert lines[2].text == "addi R, R, N  # c"
    assert lines[2].expanded == "addi t1, t1, -4  # c"
    assert [(t.kind, t.text) for t in lines[2].tokens] == [
        (Kind.OPERATOR, "addi"), (Kind.REGISTER_NAME, "t1"), (Kind.REGISTER_NAME, "t1"),
        (Kind.INTEGER, "-4"), (Kind.COMMENT, "# c")]


def test_eqv_text_is_tokenized_after_substitution(tmp_path):
    lines, errors = eqv(tmp_path, ".eqv N, 4\nli t0, -N\n")
    assert [(t.kind, t.value) for t in lines[1].tokens][-1] == (Kind.INTEGER, -4)


def test_eqv_is_lazy_and_applies_only_after_its_definition(tmp_path):
    lines, errors = eqv(tmp_path, "li t0, X\n.eqv X, Y\n.eqv Y, 5\nli t0, X\n")
    assert errors == []
    assert [line.expanded for line in lines] == ["li t0, X", ".eqv X, Y", ".eqv Y, 5", "li t0, 5"]


def test_eqv_text_ends_before_a_comment_and_a_final_comma(tmp_path):
    lines, errors = eqv(tmp_path, ".eqv X, 1 + 2,  # sum\nli t0, X\n")
    assert lines[1].expanded == "li t0, 1 + 2"


def test_eqv_character_literal(tmp_path):  # DEV-11: RARS cuts the text to "'a"
    lines, errors = eqv(tmp_path, ".eqv C, 'a'\nli t0, C\n")
    assert errors == [] and lines[1].tokens[-1].value == 97


def test_eqv_after_a_label(tmp_path):
    lines, errors = eqv(tmp_path, "L: .eqv N, 3\nli t0, N\n")
    assert errors == [] and lines[1].expanded == "li t0, 3"


def test_eqv_defined_in_an_included_file(tmp_path):
    write(tmp_path, "defs.s", ".eqv SIZE, 16\n")
    lines, errors = eqv(tmp_path, '.include "defs.s"\nli t0, SIZE\n')
    assert errors == [] and lines[-1].expanded == "li t0, 16"


def test_eqv_redefinition(tmp_path):
    lines, errors = eqv(tmp_path, ".eqv A, 5\n.eqv A, 5\n.eqv A, 6\nli t0, A\n")
    assert messages(errors) == [("Error", 3, 6, '"A" is already defined')]
    assert lines[3].expanded == "li t0, 5"


@pytest.mark.parametrize("line, column, message", [
    (".eqv A", 1, "Too few operands for .eqv directive"),  # DEV-11: RARS accepts it silently
    (".eqv A # c", 1, "Too few operands for .eqv directive"),
    (".eqv 5, 6", 1, "Malformed .eqv directive"),
    ("  .eqv t0, 6", 3, "Malformed .eqv directive"),
    (".eqv A, A+1", 1, "Cannot substitute A for itself in .eqv directive"),
])
def test_eqv_errors(tmp_path, line, column, message):
    lines, errors = eqv(tmp_path, line + "\n")
    assert messages(errors) == [("Error", 1, column, message)]


def test_indirect_eqv_cycle(tmp_path):  # DEV-11: RARS crashes with StackOverflowError
    lines, errors = eqv(tmp_path, ".eqv X, Y\n.eqv Y, Z + 1\n.eqv Z, X\nli t0, X\n")
    assert messages(errors) == [("Error", 3, 1, "Cannot substitute Z for itself in .eqv directive")]
    assert lines[3].expanded == "li t0, Z + 1"


def test_lexical_errors_of_the_eqv_line_and_of_the_substituted_line(tmp_path):
    lines, errors = eqv(tmp_path, ".eqv BAD, 1.2.3\nli t0, BAD\n")
    assert messages(errors) == [("Error", 1, 11, ".eqv BAD, 1.2.3\nInvalid language element: 1.2.3"),
                                ("Error", 2, 8, "li t0, 1.2.3\nInvalid language element: 1.2.3")]
