"""Pass 1 lays out a program the same way as RARS.

1. Addresses and sizes of the instructions == the addresses of the RARS listing.
2. The data segment: the values of pass 1 are evaluated here (pass 2 comes in
   stage 8) and compared with the data dump of RARS.
3. Messages of errors where RARS and pyrars agree.
4. Approved deviations DEV-27..DEV-29: RARS still behaves as recorded.
"""

import struct

import pytest

from pyrars.asm import pass1, pseudo
from pyrars.asm.expressions import evaluate
from pyrars.asm.source import read_source
from pyrars.isa.instructions import mnemonics
from pyrars.isa.memory import DEFAULT

pytestmark = pytest.mark.devel

OPERATORS = mnemonics(32) | pseudo.mnemonics(32)
DATA = DEFAULT.data_base

# Layout that RARS and pyrars agree on: no 8-byte data (DEV-27) and no
# section directives RARS does not know.
PROGRAM = """\
.data
first: .byte 1
count: .half 2
value: .word 3
text:  .asciz "hi"
chars: .ascii "ab"
room:  .space 5
next:  .word 4, 5
.align 3
far:   .word 6
real:  .float 1.5
pi:    .double 0.5
.extern shared, 8
.text
start: nop
li t0, 5
li t1, 100000
la t2, value
lw t3, next
beqz t0, start
ret
"""


def assemble(tmp_path, text, name="p.s"):
    path = tmp_path / name
    path.write_text(text)
    lines, errors = read_source(str(path), OPERATORS)
    assert errors == []
    return pass1.run(lines)


def data_image(result, size):
    """Data segment of pass 1 with its values evaluated (a stand-in for pass 2)."""
    memory = bytearray(size)
    for address, data in result.chunks:
        memory[address - DATA:address - DATA + len(data)] = data
    resolve = result.symbols.resolver()
    for value in result.values:
        number = value.operand.value
        if not isinstance(number, (int, float)):
            number = evaluate(number, resolve).number
        if value.float_value:
            data = struct.pack("<f" if value.size == 4 else "<d", float(number))
        else:
            data = int(number).to_bytes(value.size, "little", signed=number < 0)
        memory[value.address - DATA:value.address - DATA + value.size] = data
    return bytes(memory)


def test_addresses_and_data_match_rars(rars, tmp_path):
    result = assemble(tmp_path, PROGRAM)
    assert result.diagnostics == ()
    theirs = rars.assemble([tmp_path / "p.s"])
    assert theirs.messages == []

    # instructions: one row of the listing per word
    addresses = [placed.address + 4 * word
                 for placed in result.text for word in range(placed.size // 4)]
    assert addresses == [row.address for row in theirs.listing]

    ours = data_image(result, 4 * len(theirs.data))
    assert list(int.from_bytes(ours[i:i + 4], "little") for i in range(0, len(ours), 4)) == theirs.data


AGREED_ERRORS = [
    (".text\n.word 1\n", '".word" directive cannot appear in text segment'),
    (".text\n.space 4\n", '".space" directive cannot appear in text segment'),
    (".text\na: nop\na: nop\n", 'label "a" already defined'),
    (".globl missing\n.text\nnop\n", '"missing" declared global label but not defined.'),
    (".data\n.section .foo\n", 'section name ".foo" is ignored'),
]


@pytest.mark.parametrize("text, message", AGREED_ERRORS)
def test_same_messages(rars, tmp_path, text, message):
    ours = [(d.loc.line, d.loc.column, d.message) for d in assemble(tmp_path, text, "e.s").diagnostics]
    result = rars.assemble([tmp_path / "e.s"])
    theirs = [(m.line, m.column, m.text) for m in result.messages]
    assert ours and ours[0][2] == message and ours == theirs


def rars_result(rars, tmp_path, text):
    path = tmp_path / "d.s"
    path.write_text(text)
    result = rars.assemble([path])
    return result, [(m.line, m.column, m.text) for m in result.messages]


def test_rars_behaviour_we_deviate_from(rars, tmp_path):
    # DEV-27: RARS aligns .dword on 4 although it writes 8 bytes
    text = ".data\nb: .byte 1\nd: .dword 0x1122334455667788\n.text\nla t0, d\n"
    result, errors = rars_result(rars, tmp_path, text)
    assert errors == [] and result.data[1:3] == [0x55667788, 0x11223344]  # at offset 4
    ours = assemble(tmp_path, text, "d.s")
    assert ours.symbols.values["d"].number == DATA + 8  # we align on 8

    # DEV-28: RARS cannot switch to the text segment with .section
    text = '.data\nx: .word 1\n.section .text\nnop\n'
    result, errors = rars_result(rars, tmp_path, text)
    assert errors == [(3, 1, ".section must be followed by a section name ")]
    ours = assemble(tmp_path, text, "d.s")
    assert ours.diagnostics == () and [p.address for p in ours.text] == [DEFAULT.text_base]

    # DEV-29: RARS silently drops an instruction written in the data segment
    text = ".data\nnop\nx: .word 1\n"
    result, errors = rars_result(rars, tmp_path, text)
    assert errors == [] and result.data[:1] == [1]
    ours = assemble(tmp_path, text, "d.s")
    assert [(d.kind, d.loc.line, d.message) for d in ours.diagnostics] == [
        ("Error", 2, '"nop" instruction cannot appear in data segment')]
