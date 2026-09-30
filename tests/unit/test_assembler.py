"""Pass 2 and the assembler interface: values, machine code, .insn and options."""

import pytest

from pyrars.asm.assembler import Options, assemble
from pyrars.isa.memory import DEFAULT

TEXT, DATA = DEFAULT.text_base, DEFAULT.data_base


def build(tmp_path, *sources, options=Options()):
    """Assemble the sources; each one becomes a file of the program."""
    paths = []
    for number, text in enumerate(sources):
        path = tmp_path / f"f{number}.s"
        path.write_text(text)
        paths.append(str(path))
    return assemble(paths, options)


def messages(program):
    return [(d.kind, d.loc.line, d.loc.column, d.message) for d in program.diagnostics]


def words(program):
    return [entry.word for entry in program.text]


# ------------------------------------------------------------------ program


def test_a_program_becomes_machine_code_and_data(tmp_path):
    program = build(tmp_path, '.globl main\n.data\nmsg: .asciz "hi"\nn: .word 42\n'
                              ".text\nmain: addi t0, x0, 1\nlw t1, n\nret\n")
    assert messages(program) == []
    assert [(e.address, e.word) for e in program.text] == [
        (TEXT, 0x00100293),  # addi x5, x0, 1
        (TEXT + 4, 0x0FC10317), (TEXT + 8, 0x00032303),  # lw t1, n = auipc + lw
        (TEXT + 12, 0x00008067)]  # ret = jalr x0, x1, 0
    assert program.data_base == DATA and program.data == b"hi\0\0" + (42).to_bytes(4, "little")
    assert program.symbols == {"msg": DATA, "n": DATA + 4, "main": TEXT}
    assert program.globals == frozenset({"main"}) and not program.failed


def test_the_first_line_of_an_expansion_keeps_the_source(tmp_path):
    program = build(tmp_path, ".text\nli t0, 100000\n")
    assert [(e.loc.line if e.loc else None, e.source) for e in program.text] == [
        (2, "li t0, 100000"), (None, "")]


def test_labels_of_both_segments_are_resolved(tmp_path):
    program = build(tmp_path, ".data\nvalue: .word target\n.text\ntarget: j target\n")
    assert messages(program) == []
    assert program.data == TEXT.to_bytes(4, "little")
    assert words(program) == [0x0000006F]  # jal x0, 0


def test_numeric_labels_look_back_and_forward(tmp_path):  # DEV-4
    program = build(tmp_path, ".text\n1: nop\nj 1b\nj 1f\nnop\n1: nop\n")
    # j 1b at TEXT+4 jumps to TEXT (-4), j 1f at TEXT+8 jumps to TEXT+16 (+8)
    from pyrars.isa.codec import decode
    jumps = [decode(word, 32) for word in words(program)[1:3]]
    assert [j.operands["imm"] for j in jumps] == [-4, 8]


def test_a_numeric_label_reference_takes_the_nearest_definition(tmp_path):
    from pyrars.isa.codec import decode
    program = build(tmp_path, ".text\n1: nop\n1: nop\nj 1b\nj 1f\nnop\n1: nop\n1: nop\n")
    assert messages(program) == []
    # "1b" at TEXT+8 takes the label at TEXT+4, "1f" at TEXT+12 the one at TEXT+20
    jumps = [decode(word, 32) for word in words(program)[2:4]]
    assert [j.operands["imm"] for j in jumps] == [-4, 8]


def test_a_numeric_label_that_is_missing(tmp_path):
    program = build(tmp_path, ".text\nj 2f\n")
    assert messages(program) == [
        ("Error", 2, 3, 'Symbol "2f" not found after this line.')]


def test_an_unknown_symbol_is_reported_in_pass_2(tmp_path):
    program = build(tmp_path, ".text\nla t0, missing\n")
    assert messages(program) == [
        ("Error", 2, 8, 'Symbol "missing" not found in symbol table.')]


def test_duplicate_text_addresses(tmp_path):
    program = build(tmp_path, ".text 0x00400000\nnop\n.text 0x00400000\naddi t0, t0, 1\n")
    kind, line, column, message = messages(program)[0]
    assert (kind, line, column) == ("Error", 4, 0)
    assert message.startswith("Duplicate text segment address: 0x00400000 already occupied by ")
    assert message.endswith(" line 2 (caused by use of .text operand)")


# --------------------------------------------------------------------- data


@pytest.mark.parametrize("source, image", [
    (".data\n.byte 1, -1\n", bytes([1, 0xFF])),
    (".data\n.half -2\n", bytes([0xFE, 0xFF])),
    (".data\n.word 0xFFFFFFFF\n", bytes([0xFF] * 4)),
    (".data\n.dword 0x1122334455667788\n", bytes([0x88, 0x77, 0x66, 0x55, 0x44, 0x33, 0x22, 0x11])),
    (".data\n.float 1.5\n", bytes([0, 0, 0xC0, 0x3F])),
    (".data\n.double 1.0\n", bytes([0, 0, 0, 0, 0, 0, 0xF0, 0x3F])),
])
def test_data_values(tmp_path, source, image):
    program = build(tmp_path, source)
    assert messages(program) == [] and program.data == image


def test_a_value_that_does_not_fit_is_truncated_with_a_warning(tmp_path):
    program = build(tmp_path, ".data\n.byte 300\n.half 0x12345\n")
    assert messages(program) == [
        ("Warning", 2, 7, "value 0x0000012c is out-of-range and truncated to 0x0000002c"),
        ("Warning", 3, 7, "value 0x00012345 is out-of-range and truncated to 0x00002345")]
    assert program.data == bytes([0x2C, 0x00, 0x45, 0x23])


def test_messages_follow_the_source_and_are_not_repeated(tmp_path):  # DEV-31
    # pass 2 finds the error of line 2, pass 1 the one of line 5: the source decides
    program = build(tmp_path, ".text\nla t0, missing\n.data\n.byte 300\n.align -1\n")
    assert messages(program) == [
        ("Error", 2, 8, 'Symbol "missing" not found in symbol table.'),
        ("Warning", 4, 7, "value 0x0000012c is out-of-range and truncated to 0x0000002c"),
        ("Error", 5, 1, '"-1": operand is out of range')]


def test_a_value_that_fits_nowhere_is_reported_once(tmp_path):
    # both passes meet it: pass 1 while choosing the variant, pass 2 while encoding
    program = build(tmp_path, ".text\nli t0, 0x100000000\n")
    assert messages(program) == [("Error", 2, 8, '"0x100000000": operand is out of range')]


# ---------------------------------------------------------------- several files


def test_a_global_symbol_is_visible_in_the_other_files(tmp_path):
    program = build(tmp_path, ".globl shared\n.data\nshared: .word 7\n.text\nla t0, shared\n",
                    ".text\nlw t1, shared\n")
    assert messages(program) == []
    assert [e.address for e in program.text] == [TEXT, TEXT + 4, TEXT + 8, TEXT + 12]


def test_a_local_symbol_stays_in_its_file(tmp_path):
    program = build(tmp_path, ".data\nhidden: .word 7\n.text\nnop\n", ".text\nla t0, hidden\n")
    assert messages(program) == [
        ("Error", 2, 8, 'Symbol "hidden" not found in symbol table.')]


def test_the_same_global_in_two_files(tmp_path):
    program = build(tmp_path, ".globl same\n.text\nsame: nop\n", ".globl same\n.text\nsame: nop\n")
    assert messages(program) == [("Error", 3, 1, 'label "same" already defined')]


def test_files_follow_each_other_in_the_text_segment(tmp_path):
    program = build(tmp_path, ".text\nnop\n", ".text\naddi t0, t0, 1\n")
    assert [(e.address, e.word) for e in program.text] == [(TEXT, 0x00000013),
                                                           (TEXT + 4, 0x00128293)]


# ------------------------------------------------------------------- options


def test_pseudo_instructions_can_be_forbidden(tmp_path):
    program = build(tmp_path, ".text\nli t0, 5\n", options=Options(pseudo=False))
    assert messages(program) == [
        ("Error", 2, 1, "Extended (pseudo) instruction or format not permitted.  See Settings.")]


def test_warnings_become_errors(tmp_path):
    program = build(tmp_path, ".data\n.byte 300\n", options=Options(warnings_are_errors=True))
    assert [m[0] for m in messages(program)] == ["Error"] and program.failed


def test_the_program_may_start_at_main(tmp_path):
    source = ".text\nnop\n.globl main\nmain: nop\n"
    assert build(tmp_path, source).entry == TEXT
    assert build(tmp_path, source, options=Options(start_at_main=True)).entry == TEXT + 4
    assert build(tmp_path, ".text\nnop\n", options=Options(start_at_main=True)).entry == TEXT


def test_the_memory_configuration_is_kept(tmp_path):
    program = build(tmp_path, ".text\nnop\n")
    assert program.mem_config == "Default" and program.xlen == 32


# --------------------------------------------------------------------- .insn


@pytest.mark.parametrize("source, word", [
    (".insn 0x00000013", 0x00000013),
    (".insn 4, 0x00100093", 0x00100093),
    (".insn r 0x33, 0, 0, t0, t1, t2", 0x007302B3),  # add t0, t1, t2
    (".insn r 0x33, 0, 0x20, t0, t1, t2", 0x407302B3),  # sub t0, t1, t2
    (".insn i 0x13, 0, t0, t1, 5", 0x00530293),  # addi t0, t1, 5
    (".insn i 0x03, 2, t0, -4(t1)", 0xFFC32283),  # lw t0, -4(t1)
    (".insn s 0x23, 2, t2, 8(t1)", 0x00732423),  # sw t2, 8(t1)
    (".insn u 0x37, t0, 0x12345", 0x123452B7),  # lui t0, 0x12345
])
def test_insn_writes_the_word(tmp_path, source, word):
    program = build(tmp_path, ".text\n" + source + "\n")
    assert messages(program) == [] and words(program) == [word]


def test_insn_with_a_branch_or_jump_target(tmp_path):
    program = build(tmp_path, ".text\nhere: .insn sb 0x63, 0, t0, t1, here\n.insn uj 0x6F, ra, here\n")
    assert messages(program) == []
    assert words(program) == [0x0062_8063 & 0xFFFFFFFF, 0xFFDFF0EF]  # beq t0, t1, 0 / jal ra, -4


@pytest.mark.parametrize("source, message", [
    (".insn", '".insn" directive needs an instruction'),
    (".insn 2, 0x13", '"2": an instruction is 4 bytes long'),
    (".insn 0x100000000", '"4294967296": operand is out of range'),
    (".insn r 0x33, 0, 0, t0, t1", '".insn r" takes 6 fields: opcode, funct3, funct7, rd, rs1, rs2'),
    (".insn r 0x200, 0, 0, t0, t1, t2", '"0x200": operand is out of range'),
])
def test_insn_errors(tmp_path, source, message):
    program = build(tmp_path, ".text\n" + source + "\n")
    assert [m[3] for m in messages(program)] == [message]


def test_insn_belongs_to_the_text_segment(tmp_path):
    program = build(tmp_path, ".data\n.insn 0x13\n")
    assert [m[3] for m in messages(program)] == ['".insn" directive cannot appear in data segment']


# ---------------------------------------------------- floating point values


@pytest.mark.parametrize("source, image", [
    (".data\n.float 0.1\n", (0x3DCCCCCD).to_bytes(4, "little")),
    (".data\n.float -1.5\n", (0xBFC00000).to_bytes(4, "little")),
    (".data\n.float Inf\n", (0x7F800000).to_bytes(4, "little")),
    (".data\n.float -Inf\n", (0xFF800000).to_bytes(4, "little")),
    (".data\n.float NaN\n", (0x7FC00000).to_bytes(4, "little")),
    (".data\n.float 1e-46\n", bytes(4)),  # too small: zero, and no message
    (".data\n.float 0x1.8p1\n", (0x40400000).to_bytes(4, "little")),
    (".data\n.float 16777217\n", (0x4B800000).to_bytes(4, "little")),  # an integer, rounded
    (".data\n.double 0.1\n", (0x3FB999999999999A).to_bytes(8, "little")),
    (".data\n.double 1e-400\n", bytes(8)),
])
def test_a_floating_point_value(tmp_path, source, image):
    program = build(tmp_path, source)
    assert messages(program) == [] and program.data == image


def test_a_literal_is_rounded_once(tmp_path):
    """DEV-36: rounding to a double first and narrowing afterwards would give
    0x3f800002 here, because the first rounding lands on the midpoint."""
    literal = ("1.00000029802322387695312582718061255302767487140869206996285356581"
               "21109008789062")
    program = build(tmp_path, f".data\n.float {literal}\n")
    assert messages(program) == []
    assert program.data == (0x3F800003).to_bytes(4, "little")


def test_a_value_too_large_for_its_format_is_refused(tmp_path):
    """The message of RARS, for both formats (user decision 2026-09-30; RARS
    refuses it for .float alone, DEV-42)."""
    program = build(tmp_path, ".data\nv: .float 1.0, 1e40\nw: .double 1e400\n")
    assert messages(program) == [
        ("Error", 2, 16, '"1e40" is an out-of-range value'),
        ("Error", 3, 12, '"1e400" is an out-of-range value')]
