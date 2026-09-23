"""Macro expansion gives the same lines, machine words and messages as RARS.

1. The text of every expanded line equals the source column of the RARS listing
   ("<body line> text") and belongs to the same call line.
2. The machine words of the expanded instructions equal the RARS words.
3. Messages of macro errors where RARS and pyrars agree.
4. Approved deviations DEV-17..DEV-21: RARS still behaves as recorded.
"""

import pytest

from pyrars.asm.lexer import Kind
from pyrars.asm.source import read_source, statement_start
from pyrars.isa.instructions import mnemonics
from test_isa_vs_rars import TEXT_BASE
from test_operands_vs_rars import assemble_line

pytestmark = pytest.mark.devel

OPERATORS = mnemonics(32)

PROGRAM = """\
.macro incr %r, %n
addi %r, %r, %n
addi %r, %r, 1
.end_macro
.macro twice %r
incr %r, 4
incr %r, 8
.end_macro
.text
incr t0, 2
start: twice t1
incr t2, 8
"""


def write(tmp_path, text, name="m.s"):
    path = tmp_path / name
    path.write_text(text)
    return path


def our_lines(path):
    lines, errors = read_source(str(path), OPERATORS)
    assert errors == []
    return lines


def is_instruction(line):
    """The line has a statement that is not a directive: the listing shows it."""
    start = statement_start(line.tokens)
    return start < len(line.tokens) and line.tokens[start].kind is not Kind.DIRECTIVE


def test_expanded_lines_match_the_rars_listing(rars, tmp_path):
    path = write(tmp_path, PROGRAM)
    result = rars.assemble([path])
    assert result.messages == []

    # Lines of ours that RARS shows in the listing: the instructions.
    ours = [(line.calls[0].line if line.calls else line.line,
             f"<{line.line}> {line.expanded.strip()}" if line.calls else line.expanded)
            for line in our_lines(path) if is_instruction(line)]
    assert ours == [(row.line, row.source) for row in result.listing]


def test_expanded_instructions_assemble_like_rars(rars, tmp_path):
    path = write(tmp_path, PROGRAM)
    result = rars.assemble([path])
    words = []
    for number, line in enumerate(l for l in our_lines(path) if is_instruction(l)):
        words.append(assemble_line(line.expanded, 32, TEXT_BASE + 4 * number, {}))
    assert words == result.text


AGREED_ERRORS = [
    (".macro\n", '".macro" directive requires at least one argument.'),
    (".macro 5\n", 'Invalid Macro name "5"'),
    (".macro add %a\n", 'Invalid Macro name "add"'),
    (".macro m a\n.end_macro\n", "Invalid macro argument 'a'"),
    (".macro m\nnop\n.macro k\n.end_macro\n", "Nested macros are not allowed"),
    (".end_macro\n", ".END_MACRO without .MACRO"),
    (".macro m\n.end_macro nop\n", "invalid text after .END_MACRO"),
    (".macro m\nnop\n", "Macro started but not ended (no .end_macro directive)"),
    (".macro m %a\nnop\n.end_macro\n.text\nm t0, t1\n",
     'forward reference or invalid parameters for macro "m"'),
    (".macro m %a\nadd %a, %b, x0\n.end_macro\n.text\nm t0\n", "Unknown macro parameter"),
]


@pytest.mark.parametrize("text, message", AGREED_ERRORS)
def test_same_macro_errors(rars, tmp_path, text, message):
    result = rars.assemble([write(tmp_path, text)])
    theirs = [(m.line, m.column, m.text) for m in result.messages if m.text == message]
    _, errors = read_source(str(write(tmp_path, text)), OPERATORS)
    ours = [(e.loc.line, e.loc.column or None, e.message) for e in errors if e.message == message]
    assert ours and ours == theirs


def rars_messages(rars, tmp_path, text):
    result = rars.assemble([write(tmp_path, text)])
    return result, [(m.line, m.column, m.text) for m in result.messages]


def our_result(tmp_path, text):
    lines, errors = read_source(str(write(tmp_path, text, "ours.s")), OPERATORS)
    return [line.expanded for line in lines], [(e.loc.line, e.loc.column, e.message) for e in errors]


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    # DEV-17: RARS substitutes by text search, so "%a" is found inside "%ab"
    text = ".macro m %ab, %a\nadd %ab, %a, x0\n.end_macro\n.text\nm t0, t1\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [(2, 5, '"t1b": operand is of incorrect type')]
    assert our_result(tmp_path, text) == ([".text", "add t0, t1, x0"], [])

    # DEV-17: a label of the body is found inside another word
    text = ".macro m %r\nn: addi %r, %r, -1\nbnez %r, n\n.end_macro\n.text\nm t0\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [(3, 1, '"bn_M0ez" is not a recognized operator')]
    assert our_result(tmp_path, text) == ([".text", "n_M0: addi t0, t0, -1", "bnez t0, n_M0"], [])

    # DEV-18: RARS separates arguments by blanks; for us "t0 t1" is one argument
    text = ".macro m %a, %b\nadd %a, %a, %b\n.end_macro\n.text\nm t0 t1\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x006282B3]
    lines, ours = our_result(tmp_path, text)
    assert lines == [".text"]
    assert ours == [(5, 1, 'forward reference or invalid parameters for macro "m"')]

    # DEV-18: RARS strips the parentheses of a call; for us they belong to the argument
    text = ".macro m %a\naddi %a, %a, 1\n.end_macro\n.text\nm(t2)\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x00138393]
    assert our_result(tmp_path, text) == ([".text", "addi (t2), (t2), 1"], [])

    # DEV-18: RARS accepts a parameter list without commas
    text = ".macro m %a %b\nadd %a, %a, %b\n.end_macro\n.text\nm t0, t1\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x006282B3]
    assert our_result(tmp_path, text)[1] == [
        (1, 13, 'Macro parameters must be separated by ","'),  # only "%a" is a parameter, so
        (5, 1, 'forward reference or invalid parameters for macro "m"')]  # the call has too many

    # DEV-21: RARS takes a "$name" that is not a register as a parameter (SPIM style)
    text = ".macro m $a\naddi $a, $a, 1\n.end_macro\n.text\nm t0\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x00128293]
    assert our_result(tmp_path, text)[1] == [
        (1, 10, "Invalid macro argument '$a'"),  # the macro has no parameters, so
        (5, 1, 'forward reference or invalid parameters for macro "m"')]  # the call has one

    # DEV-19: RARS detects an expansion loop one call later
    text = ".macro a\nb1\n.end_macro\n.macro b1\na\n.end_macro\n.text\na\n"
    result, errors = rars_messages(rars, tmp_path, text)
    loop = "Detected a macro expansion loop (recursive reference). "
    assert errors == [(2, None, loop)]
    assert "line 8->2->5->2:" in result.stdout
    assert our_result(tmp_path, text)[1] == [(5, 1, loop)]


def test_the_body_sees_the_eqv_of_the_call(rars, tmp_path):
    """DEV-20: RARS applies every .eqv of the file to a body, we those of the call."""
    text = ".macro m\naddi t0, t0, K\n.end_macro\n.text\n.eqv K, 3\nm\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x00328293]
    assert our_result(tmp_path, text) == ([".text", ".eqv K, 3", "addi t0, t0, 3"], [])

    # RARS substitutes an .eqv defined after the call as well; we do not
    text = ".macro m\naddi t0, t0, K\n.end_macro\n.text\nm\n.eqv K, 3\n"
    result, errors = rars_messages(rars, tmp_path, text)
    assert errors == [] and result.text == [0x00328293]
    assert our_result(tmp_path, text)[0] == [".text", "addi t0, t0, K", ".eqv K, 3"]
