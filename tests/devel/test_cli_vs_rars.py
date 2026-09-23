"""The dumps of our command line hold the same words as the dumps of RARS.

RARS is called with `dump .text HexText` and `dump .data HexText`; we call our
own command line with `--dump .text:hex:<file>` and compare the files. This is
the test the corpus of whole programs will use later (T-ASM-OK).
"""

import io

import pytest

from pyrars.cli import main

pytestmark = pytest.mark.devel

PROGRAM = """\
.globl main
.data
msg:    .asciz "hello"
count:  .word 42
values: .word 1, 2, 3
flag:   .byte 1
real:   .float 2.5
room:   .space 8
.text
main:   li t0, 5
        li t1, 100000
        la t2, msg
        lw t3, count
        lb t4, flag
        addi t0, t0, -1
        beqz t0, done
        j loop
loop:   nop
        bnez t1, loop
        call done
        csrr a0, fcsr
        fadd.s ft0, ft1, ft2
        seqz a1, a0
        not a3, a1
done:   ret
"""


def run(*arguments) -> tuple[int, str, str]:
    out, errors = io.StringIO(), io.StringIO()
    code = main(list(arguments), out=out, errors=errors)
    return code, out.getvalue(), errors.getvalue()


def test_our_dumps_hold_the_same_words(rars, tmp_path):
    source = tmp_path / "p.s"
    source.write_text(PROGRAM)
    text_dump, data_dump = tmp_path / "t.hex", tmp_path / "d.hex"
    code, _, errors = run("asm", "-d", f".text:hex:{text_dump}", "-d", f".data:hex:{data_dump}",
                          str(source))
    assert (code, errors) == (0, "")

    theirs = rars.assemble([source])
    assert theirs.messages == []
    assert [int(word, 16) for word in text_dump.read_text().split()] == theirs.text
    ours = [int(word, 16) for word in data_dump.read_text().split()]
    assert ours == theirs.data[:len(ours)] and set(theirs.data[len(ours):]) <= {0}


def test_a_program_that_fails_gives_the_same_messages(rars, tmp_path):
    source = tmp_path / "e.s"
    source.write_text(".text\nla t0, missing\n.data\n.byte 300\n")
    code, _, errors = run("asm", str(source))
    theirs = rars.assemble([source])
    assert code == 1
    ours = [line.split(": ", 1)[1] for line in errors.splitlines()]
    # we sort the messages by their place in the source, RARS by its passes
    assert sorted(ours) == sorted(message.text for message in theirs.messages)


def test_the_words_we_dump_read_back_to_the_same_instructions(rars, tmp_path):
    """asm --dump and disasm are two sides of the same program."""
    source = tmp_path / "p.s"
    source.write_text(PROGRAM)
    dump = tmp_path / "t.hex"
    assert run("asm", "-d", f".text:hex:{dump}", str(source))[0] == 0
    _, out, _ = run("disasm", str(dump))

    theirs = rars.assemble([source])
    mnemonics = [row.basic.split(" ")[0] for row in theirs.listing]
    ours = [line.split("  ")[2].split(" ")[0] if len(line.split("  ")) > 2 else ""
            for line in out.splitlines()]
    assert ours == mnemonics
