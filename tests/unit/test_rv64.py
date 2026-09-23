"""RV64: the 64-bit `li`, and the rest of the assembler with 64-bit registers."""

import pytest

from pyrars.asm.assembler import Options, assemble
from pyrars.isa.codec import decode
from pyrars.isa.memory import DEFAULT

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base
MASK = (1 << 64) - 1


def build(tmp_path, text, xlen=64):
    path = tmp_path / "p.s"
    path.write_text(text)
    return assemble([str(path)], Options(xlen=xlen))


def run_sequence(words: list[int]) -> int:
    """Value one register holds after the words of a `li` expansion.

    Only the four instructions `li` uses are needed: lui, addiw, slli, addi.
    """
    register = 0
    for word in words:
        decoded = decode(word, 64)
        assert decoded is not None, f"{word:08x} is no instruction"
        operands = decoded.operands
        match decoded.instr.mnemonic:
            case "lui":
                register = _signed(operands["imm"] << 12)
            case "addiw":
                register = _signed((register + operands["imm"]) & 0xFFFFFFFF, bits=32)
            case "addi":
                register = _signed(register + operands["imm"])
            case "slli":
                register = _signed(register << operands["shamt"])
            case other:
                raise AssertionError(f"unexpected instruction {other}")
    return register & MASK


def _signed(value: int, bits: int = 64) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


@pytest.mark.parametrize("value, count", [
    (0, 1), (2047, 1), (-2048, 1),
    (2048, 2), (100000, 2), (0x7FFFFFFF, 2), (-2**31, 2), (-1, 1),
    (0x80000000, 8), (0xFFFFFFFF, 8), (0x100000000, 8),
    (0x1122334455667788, 8), (2**63 - 1, 8), (-2**63, 8),
])
def test_li_builds_the_value_it_was_given(tmp_path, value, count):
    program = build(tmp_path, f".text\nli t0, {value}\n")
    assert program.diagnostics == ()
    words = [entry.word for entry in program.text]
    assert len(words) == count
    assert run_sequence(words) == value & MASK


def test_a_value_wider_than_64_bits_is_out_of_range(tmp_path):
    program = build(tmp_path, ".text\nli t0, 0x1_0000_0000_0000_0000\n".replace("_", ""))
    assert [d.message for d in program.diagnostics] == [
        '"0x10000000000000000": operand is out of range']


def test_the_64_bit_li_is_the_sequence_of_rars(tmp_path):
    """lui, addiw, then three shifts with additions of 11, 11 and 10 bits."""
    program = build(tmp_path, ".text\nli t0, 0x1122334455667788\n")
    assert [entry.basic for entry in program.text] == [
        "lui x5,0x11223", "addiw x5,x5,836", "slli x5,x5,11", "addi x5,x5,683",
        "slli x5,x5,11", "addi x5,x5,413", "slli x5,x5,10", "addi x5,x5,904"]


def test_rv32_keeps_its_own_range(tmp_path):  # DEV-13
    program = build(tmp_path, ".text\nli t0, 0xFFFFFFFF\n", xlen=32)
    assert program.diagnostics == () and len(program.text) == 2
    program = build(tmp_path, ".text\nli t0, 0x100000000\n", xlen=32)
    assert [d.message for d in program.diagnostics] == [
        '"0x100000000": operand is out of range']


# ------------------------------------------------- the rest of the assembler


def test_instructions_and_pseudo_instructions_of_rv64(tmp_path):
    program = build(tmp_path, ".data\nvalue: .dword 0x1122334455667788\n"
                              ".text\nld t0, value\nsd t0, value, t1\naddiw t2, t0, 1\n"
                              "slli t3, t0, 63\nsext.w t4, t0\nzext.w t5, t0\nnegw t6, t0\n")
    assert program.diagnostics == ()
    assert program.data == (0x1122334455667788).to_bytes(8, "little")
    basics = [entry.basic for entry in program.text]
    assert basics[:2] == ["auipc x5,0x0fc10", "ld x5,0(x5)"]  # "ld t0, value"
    assert basics[-6:] == ["addiw x7,x5,1", "slli x28,x5,63", "addiw x29,x5,0",
                           "slli x30,x5,32", "srli x30,x30,32", "subw x31,x0,x5"]


def test_the_shift_amount_of_rv64_reaches_63(tmp_path):
    assert build(tmp_path, ".text\nslli t0, t0, 63\n").diagnostics == ()
    program = build(tmp_path, ".text\nslli t0, t0, 64\n")
    assert [d.message for d in program.diagnostics] == ['"64": operand is out of range']
    program = build(tmp_path, ".text\nslli t0, t0, 32\n", xlen=32)
    assert [d.message for d in program.diagnostics] == ['"32": operand is out of range']


def test_an_instruction_of_the_other_width_is_unknown(tmp_path):
    assert [d.message for d in build(tmp_path, ".text\naddiw t0, t0, 1\n", xlen=32).diagnostics] \
        == ['"addiw" is not a recognized operator']
    assert build(tmp_path, ".text\naddiw t0, t0, 1\n").diagnostics == ()
