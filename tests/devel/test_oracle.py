"""The oracle helper runs RARS and reads its output correctly.

Expected machine words are derived by hand from the RISC-V instruction formats
(ISA manual, RV32I), with the Default RARS memory layout:
.text at 0x00400000, .data at 0x10010000.
"""

import pytest

pytestmark = pytest.mark.devel

PROGRAM = """\
.data
msg: .asciz "hi"
val: .word 5, -1
.text
main:
    la   a0, msg
    addi t0, zero, 5
    ecall
"""

# la a0, msg -> auipc x10, hi ; addi x10, x10, lo
#   msg - pc = 0x10010000 - 0x00400000 = 0x0FC10000 -> hi = 0x0FC10, lo = 0
AUIPC_A0 = (0x0FC10 << 12) | (10 << 7) | 0b0010111                 # 0x0FC10517
ADDI_A0 = (0 << 20) | (10 << 15) | (0b000 << 12) | (10 << 7) | 0b0010011  # 0x00050513
# addi t0, zero, 5 -> imm=5, rs1=x0, rd=x5
ADDI_T0 = (5 << 20) | (0 << 15) | (0b000 << 12) | (5 << 7) | 0b0010011    # 0x00500293
ECALL = 0b1110011                                                    # 0x00000073


def test_text_and_data_dumps(rars, tmp_path):
    source = tmp_path / "prog.s"
    source.write_text(PROGRAM)

    result = rars.assemble([source])

    assert result.exit_code == 0
    assert result.messages == []
    assert result.text == [AUIPC_A0, ADDI_A0, ADDI_T0, ECALL]
    # "hi\0" little-endian in one word, .word 5 and -1 aligned to the next word
    assert result.data[:3] == [0x00006968, 5, 0xFFFFFFFF]
    assert all(word == 0 for word in result.data[3:])


def test_listing(rars, tmp_path):
    source = tmp_path / "prog.s"
    source.write_text(PROGRAM)

    listing = rars.assemble([source]).listing

    assert [row.address for row in listing] == [0x00400000, 0x00400004, 0x00400008, 0x0040000C]
    assert [row.code for row in listing] == [AUIPC_A0, ADDI_A0, ADDI_T0, ECALL]
    assert [row.line for row in listing] == [6, None, 7, 8]
    assert listing[2].basic == "addi x5,x0,5"
    assert listing[2].source == "    addi t0, zero, 5"


def test_assembly_errors(rars, tmp_path):
    source = tmp_path / "bad.s"
    source.write_text(".text\n  addi t0, t0\n  foo x1\n")

    result = rars.assemble([source])

    assert result.exit_code == rars.ASSEMBLY_ERROR_EXIT
    assert result.text == []
    assert [(m.kind, m.file, m.line, m.column) for m in result.messages] == [
        ("Error", str(source), 2, 3),
        ("Error", str(source), 3, 3),
    ]
    assert result.messages[1].text == '"foo" is not a recognized operator'
