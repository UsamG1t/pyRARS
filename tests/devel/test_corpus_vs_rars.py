"""Whole programs of the corpus assemble to the same code as RARS.

The programs in `corpus/` are ordinary RISC-V assembly: data, macros, loops,
subroutine calls, floating point, control and status registers. They avoid the
places where we deliberately differ (those have their own tests), so that a
difference here means a mistake.

The single tests check one thing at a time; the corpus checks that the parts
work together, and it stays as the net that catches a change in the assembled
code when later stages touch the assembler.
"""

from pathlib import Path

import pytest

from pyrars.asm.assembler import Options, assemble

pytestmark = pytest.mark.devel

CORPUS = sorted(Path(__file__).with_name("corpus").glob("*.s"))


def test_the_corpus_is_there():
    assert [path.name for path in CORPUS] == [
        "arithmetic.s", "control.s", "floating.s", "memory.s", "strings.s", "system.s"]


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: path.stem)
def test_a_program_assembles_like_in_rars(rars, path):
    theirs = rars.assemble([path])
    assert theirs.messages == [], f"RARS does not assemble {path.name}"

    program = assemble([str(path)])
    assert program.diagnostics == ()
    assert [entry.word for entry in program.text] == theirs.text

    ours = [int.from_bytes(program.data[i:i + 4], "little")
            for i in range(0, len(program.data), 4)]
    assert ours == theirs.data[:len(ours)]
    assert set(theirs.data[len(ours):]) <= {0}  # RARS pads its dump with zeros


@pytest.mark.parametrize("path", CORPUS, ids=lambda path: path.stem)
def test_the_listing_of_a_program_matches(rars, path):
    """Every word belongs to the same source line as in the listing of RARS."""
    theirs = rars.assemble([path])
    program = assemble([str(path)])
    # a line of a macro belongs to the call, which the listing of RARS shows
    lines = [None if entry.loc is None else
             (entry.loc.calls[0].line if entry.loc.calls else entry.loc.line)
             for entry in program.text]
    assert lines == [row.line for row in theirs.listing]
