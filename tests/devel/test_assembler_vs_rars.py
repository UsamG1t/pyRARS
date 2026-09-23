"""Whole programs assemble to the same text and data as RARS.

1. A program using every part of the assembler: words of .text and bytes of
   .data == the dumps of RARS.
2. The same for a program of two files.
3. Messages of errors where RARS and pyrars agree.
4. Approved deviations: our own directives (DEV-26, DEV-28) and `.insn`, which
   RARS does not have at all.
"""

import pytest

from pyrars.asm.assembler import Options, assemble
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

# Everything both assemblers agree on: no 8-byte data (DEV-27), no "mv" (DEV-22),
# no CSR writing pseudo-instructions (DEV-23), no numeric labels (DEV-4).
PROGRAM = """\
.globl main
.data
msg:    .asciz "hello"
chars:  .ascii "ab"
count:  .word 42
values: .word 1, 2, 3
flag:   .byte 1
half:   .half 0x1234
real:   .float 2.5
room:   .space 8
pointer: .word main
.text
main:   li t0, 5
        li t1, 100000
        la t2, msg
        lw t3, count
        lb t4, flag
        sw t0, count, t5
        addi t0, t0, -1
        beqz t0, done
        bgt t0, t1, done
        j loop
loop:   nop
        addi t1, t1, -1
        bnez t1, loop
        jal ra, done
        call done
        csrr a0, fcsr
        fadd.s ft0, ft1, ft2
        fsqrt.d ft3, ft4
        seqz a1, a0
        sext.b a2, a1
        not a3, a2
        neg a4, a3
done:   ret
"""

FILE_A = """\
.globl shared, start
.data
shared: .word 7
.text
start:  la t0, shared
        j helper
"""

FILE_B = """\
.globl helper
.text
helper: lw t1, shared
        addi t1, t1, 1
        ret
"""


def build(tmp_path, *sources, options=Options()):
    paths = []
    for number, text in enumerate(sources):
        path = tmp_path / f"f{number}.s"
        path.write_text(text)
        paths.append(str(path))
    return assemble(paths, options), paths


def words_of(program):
    return [entry.word for entry in program.text]


def data_words(program, count):
    """The data segment as words, like the RARS dump."""
    image = program.data.ljust(4 * count, b"\0")
    return [int.from_bytes(image[i:i + 4], "little") for i in range(0, 4 * count, 4)]


def test_a_whole_program_matches_rars(rars, tmp_path):
    program, paths = build(tmp_path, PROGRAM)
    assert program.diagnostics == ()
    theirs = rars.assemble([paths[0]])
    assert theirs.messages == []
    assert words_of(program) == theirs.text
    assert data_words(program, len(theirs.data)) == theirs.data
    assert program.symbols["main"] == DEFAULT.text_base


def test_a_program_of_two_files_matches_rars(rars, tmp_path):
    program, paths = build(tmp_path, FILE_A, FILE_B)
    assert program.diagnostics == ()
    theirs = rars.assemble(paths)
    assert theirs.messages == []
    assert words_of(program) == theirs.text
    assert data_words(program, len(theirs.data)) == theirs.data


def test_pseudo_instructions_may_be_forbidden_like_in_rars(rars, tmp_path):
    program, paths = build(tmp_path, ".text\nli t0, 5\n", options=Options(pseudo=False))
    theirs = rars.assemble([paths[0]], ("np",))
    ours = [(d.loc.line, d.loc.column, d.message) for d in program.diagnostics]
    assert ours == [(m.line, m.column, m.text) for m in theirs.messages]


AGREED_ERRORS = [
    (".text\nla t0, missing\n", 'Symbol "missing" not found in symbol table.'),
    (".data\n.byte 300\n", "value 0x0000012c is out-of-range and truncated to 0x0000002c"),
]


@pytest.mark.parametrize("text, message", AGREED_ERRORS)
def test_same_messages(rars, tmp_path, text, message):
    program, paths = build(tmp_path, text)
    ours = [(d.loc.line, d.loc.column, d.message) for d in program.diagnostics]
    theirs = [(m.line, m.column, m.text) for m in rars.assemble([paths[0]]).messages]
    assert ours and ours[0][2] == message and ours == theirs


def test_duplicate_addresses_are_reported_like_rars(rars, tmp_path):
    source = ".text 0x00400000\nnop\n.text 0x00400000\naddi t0, t0, 1\n"
    program, paths = build(tmp_path, source)
    theirs = rars.assemble([paths[0]])
    ours = [(d.loc.line, d.message) for d in program.diagnostics]
    assert ours == [(m.line, m.text) for m in theirs.messages]


def test_what_rars_cannot_assemble(rars, tmp_path):
    """.insn and the pseudo-instructions of the asm manual are ours alone."""
    source = ".text\n.insn r 0x33, 0, 0, t0, t1, t2\n.insn 0x00000013\nlla t3, here\nhere: pause\n"
    program, paths = build(tmp_path, source)
    assert program.diagnostics == ()
    assert words_of(program)[:2] == [0x007302B3, 0x00000013]
    theirs = rars.assemble([paths[0]])
    assert [m.text for m in theirs.messages][:1] == [
        "RARS does not recognize the .insn directive.  Ignored."]
