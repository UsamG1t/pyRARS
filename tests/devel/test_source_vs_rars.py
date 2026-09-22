"""pyrars.asm.source handles .include and .eqv as RARS does.

1. Nested includes and .eqv chains: the .word values in our lines, in order,
   equal the data RARS stores.
2. Errors: same line, column and text as RARS (duplicates dropped).
3. Approved deviations DEV-10, DEV-11: RARS still behaves as recorded.
"""

import pytest

from pyrars.asm.lexer import Kind
from pyrars.asm.source import read_source
from pyrars.isa.instructions import INSTRUCTIONS

pytestmark = pytest.mark.devel

OPERATORS = {i.mnemonic for i in INSTRUCTIONS} | {"li", "la", "nop", "b"}


def write(directory, name, text):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def word_values(lines):
    """Integer operands of .word lines (after an optional label), in order."""
    values = []
    for line in lines:
        tokens = list(line.tokens)
        if len(tokens) > 1 and tokens[1].kind is Kind.COLON:
            tokens = tokens[2:]
        if tokens and tokens[0].text == ".word":
            values += [t.value for t in tokens[1:] if t.kind is Kind.INTEGER]
    return values


def ours(main):
    lines, errors = read_source(str(main), OPERATORS)
    return lines, sorted((e.loc.line, e.loc.column, e.message) for e in errors)


def theirs(rars, main):
    result = rars.assemble([main])
    return result, sorted({(m.line, m.column, m.text) for m in result.messages})


def test_includes_and_eqv_give_the_same_data(rars, tmp_path):
    write(tmp_path, "lib/y.s", ".word 4, ONE\n")
    write(tmp_path, "lib/x.s", '.eqv THREE, 3\n.word THREE\n.include "y.s"\n.word 5\n')
    main = write(tmp_path, "m.s", '.eqv ONE, 1\n.eqv ALSO_ONE, ONE\n.data\n.word ONE, ALSO_ONE\n'
                                  '  .include "lib/x.s"  # nested\n.word 9, THREE\n')
    lines, errors = ours(main)
    result, rars_errors = theirs(rars, main)
    assert errors == rars_errors == []
    values = word_values(lines)
    assert values == [1, 1, 3, 4, 1, 5, 9, 3]
    assert result.data[:len(values)] == values


@pytest.mark.parametrize("files", [
    {"m.s": '.data\n.include "m.s"\n'},  # recursive include
    {"m.s": '.include "none.s"\n'},  # missing file
    {"m.s": ".eqv A # c\n.eqv 5, 6\n.eqv A, A+1\n.eqv K, 5\n.eqv K, 6\n"
            ".eqv BAD, 1.2.3\n.text\nli t0, BAD\n"},
])
def test_same_errors(rars, tmp_path, files):
    for name, text in files.items():
        write(tmp_path, name, text)
    main = tmp_path / "m.s"
    result, rars_errors = theirs(rars, main)
    assert rars_errors  # every case is an error in RARS
    assert ours(main)[1] == rars_errors


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    write(tmp_path, "d.s", ".data\n.word 7\n")

    # DEV-10: RARS drops a label before .include
    main = write(tmp_path, "m.s", '.data\nstart: .include "d.s"\n.text\nla t0, start\n')
    assert theirs(rars, main)[1] == [(4, 8, 'Symbol "start" not found in symbol table.')]
    assert [t.text for t in ours(main)[0][1].tokens] == ["start", ":"]

    # DEV-10: RARS rejects a second (not nested) include of a file
    main = write(tmp_path, "m.s", '.include "d.s"\n.include "d.s"\n')
    assert theirs(rars, main)[1] == [(2, 10, f"Recursive include of file {tmp_path / 'd.s'}")]
    assert [e[2].split(".")[0] for e in ours(main)[1]] == [f"Repeated include of {tmp_path / 'd'}"]

    # DEV-10: RARS finds .include anywhere and drops the rest of the line
    main = write(tmp_path, "m.s", '.text\naddi t0, t0, 1 .include "d.s" junk\n')
    result, errors = theirs(rars, main)
    assert errors == [] and result.text == [] and result.data[:1] == [7]
    assert ours(main)[0][1].expanded == 'addi t0, t0, 1 .include "d.s" junk'

    # DEV-10: RARS notices an indirect cycle one level late (the main file is not
    # registered), so it reports the next include; we report the include closing the cycle
    main = write(tmp_path, "m.s", '.include "a.s"\n')
    write(tmp_path, "a.s", '.word 1\n.include "m.s"\n')
    assert theirs(rars, main)[1] == [(1, 10, f"Recursive include of file {tmp_path / 'a.s'}")]
    lines, errors = read_source(str(main), OPERATORS)
    assert [(e.loc.file, e.loc.line, e.message) for e in errors] == [
        (str(tmp_path / "a.s"), 2, f"Recursive include of file {main}")]

    # DEV-11: RARS accepts ".eqv A" silently and cuts a character literal to "'a"
    main = write(tmp_path, "m.s", ".eqv A\n.eqv C, 'a'\n.text\nli t0, C\n")
    assert theirs(rars, main)[1] == [(4, 8, "li t0, 'a\nInvalid language element: 'a")]
    assert ours(main)[1] == [(1, 1, "Too few operands for .eqv directive")]

    # DEV-11: an indirect .eqv cycle crashes RARS (StackOverflowError, no message)
    main = write(tmp_path, "m.s", ".eqv X, Y\n.eqv Y, X\n.text\nli t0, X\n")
    result, errors = theirs(rars, main)
    assert result.exit_code != 0 and errors == []
    assert ours(main)[1] == [(2, 1, "Cannot substitute Y for itself in .eqv directive")]
