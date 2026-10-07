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


# Literals whose value both assemblers must agree on, RARS through a Java
# double and a cast, we through pyrars.softfloat (DEV-36).
LITERALS = (".float 0.0, -0.0, 1.0, -1.5, 0.1, 3.14159265, 1e10, 1e-10, 1e-46, "
            "16777217, 0x1.8p1, Inf, -Inf, NaN, 1.17549435e-38, 3.4e38\n"
            ".double 0.1, 1e300, 1e-320, 4.9e-324, 1.7976931348623157e308, Inf\n")


def test_the_values_of_float_literals_agree(rars, tmp_path):
    program, paths = build(tmp_path, ".data\n" + LITERALS)
    assert program.diagnostics == ()
    theirs = rars.assemble([paths[0]])
    assert theirs.messages == []
    ours = [int.from_bytes(program.data[i:i + 4], "little")
            for i in range(0, len(program.data), 4)]
    assert ours == theirs.data[:len(ours)]


def test_a_literal_is_rounded_once(rars, tmp_path):
    """DEV-36: this literal lies just above the midpoint between two singles,
    and rounding it to a double first lands exactly on that midpoint, from where
    a second rounding goes to the even value below. One rounding goes up."""
    literal = ("1.00000029802322387695312582718061255302767487140869206996285356581"
               "21109008789062")
    program, paths = build(tmp_path, f".data\nv: .float {literal}\n")
    assert program.diagnostics == ()
    assert program.data[:4] == (0x3F800003).to_bytes(4, "little")
    assert rars.assemble([paths[0]]).data[:1] == [0x3F800002]


def test_a_value_too_large_for_its_format(rars, tmp_path):  # DEV-42
    """A literal that has no value in its format is refused with the message of
    RARS. RARS itself asks the question differently: it reads every literal as a
    64-bit value and compares THAT with the largest single, so it refuses a
    `.float` value that rounds to the largest single, and refuses nothing at all
    for `.double`. We refuse exactly the values whose rounding overflows."""
    program, paths = build(tmp_path, ".data\nv: .float 1.0, 1e40\n")
    theirs = rars.assemble([paths[0]])
    ours = [(d.loc.line, d.loc.column, d.message) for d in program.diagnostics]
    assert ours == [(m.line, m.column, m.text) for m in theirs.messages]
    assert ours == [(2, 16, '"1e40" is an out-of-range value')]

    program, paths = build(tmp_path, ".data\nw: .double 1e400\n")
    assert [d.message for d in program.diagnostics] == [
        '"1e400" is an out-of-range value']
    theirs = rars.assemble([paths[0]])
    assert theirs.messages == [] and theirs.data[:2] == [0x00000000, 0x7FF00000]

    # a value between the largest single and the overflow: it rounds to the
    # largest single, which RARS refuses although the value has a rounding
    program, paths = build(tmp_path, ".data\nv: .float 3.4028235e38\n")
    assert program.diagnostics == ()
    assert program.data[:4] == (0x7F7FFFFF).to_bytes(4, "little")
    theirs = rars.assemble([paths[0]])
    assert [m.text for m in theirs.messages] == [
        '"3.4028235e38" is an out-of-range value']
