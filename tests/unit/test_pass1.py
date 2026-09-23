"""Pass 1: addresses, symbols, sections and the data layout."""

import pytest

from pyrars.asm import pass1, pseudo
from pyrars.asm.source import read_source
from pyrars.isa.instructions import mnemonics
from pyrars.isa.memory import DEFAULT

TEXT, DATA, EXTERN = DEFAULT.text_base, DEFAULT.data_base, DEFAULT.extern_base
OPERATORS = mnemonics(32) | pseudo.mnemonics(32)


def run(tmp_path, text, xlen=32):
    path = tmp_path / "p.s"
    path.write_text(text)
    lines, errors = read_source(str(path), OPERATORS)
    assert errors == [], errors
    return pass1.run(lines, xlen)


def messages(result):
    return [(d.kind, d.loc.line, d.loc.column, d.message) for d in result.diagnostics]


def symbols(result):
    return {name: (value.number, value.segment) for name, value in result.symbols.values.items()}


def data_image(result):
    """Bytes of the data segment, values evaluated after pass 1 (a stand-in for pass 2)."""
    from pyrars.asm.expressions import evaluate
    memory = bytearray(256)
    for address, data in result.chunks:
        memory[address - DATA:address - DATA + len(data)] = data
    resolve = result.symbols.resolver()
    for value in result.values:
        number = value.operand.value
        if not isinstance(number, (int, float)):
            number = evaluate(number, resolve).number
        memory[value.address - DATA:value.address - DATA + value.size] = \
            int(number).to_bytes(value.size, "little", signed=number < 0)
    return bytes(memory)


# ---------------------------------------------------------------- addresses


def test_instructions_get_addresses_and_sizes(tmp_path):
    result = run(tmp_path, ".text\nstart: nop\nli t0, 5\nli t1, 100000\nla t2, start\nret\n")
    assert messages(result) == []
    assert [(p.address, p.size) for p in result.text] == [
        (TEXT, 4), (TEXT + 4, 4), (TEXT + 8, 8), (TEXT + 16, 8), (TEXT + 24, 4)]
    assert symbols(result) == {"start": (TEXT, "text")}


def test_text_starts_the_program_and_data_directives_need_the_data_segment(tmp_path):
    result = run(tmp_path, "nop\n.word 1\n.space 4\n")
    assert messages(result) == [
        ("Error", 2, 1, '".word" directive cannot appear in text segment'),
        ("Error", 3, 1, '".space" directive cannot appear in text segment')]


def test_an_instruction_in_the_data_segment_is_an_error(tmp_path):  # DEV-29
    result = run(tmp_path, ".data\nnop\n")
    assert messages(result) == [("Error", 2, 1, '"nop" instruction cannot appear in data segment')]


def test_segment_addresses_can_be_given(tmp_path):
    result = run(tmp_path, ".text 0x00400100\nnop\n.data 0x10020000\nx: .word 1\n")
    assert [p.address for p in result.text] == [0x00400100]
    assert symbols(result) == {"x": (0x10020000, "data")}


# ----------------------------------------------------------------- data


def test_data_labels_get_the_aligned_address_of_their_value(tmp_path):
    result = run(tmp_path, ".data\nb: .byte 1\nh: .half 2\nw: .word 3\nd: .dword 4\nf: .float 1.5\n")
    assert messages(result) == []
    assert symbols(result) == {"b": (DATA, "data"), "h": (DATA + 2, "data"), "w": (DATA + 4, "data"),
                               "d": (DATA + 8, "data"), "f": (DATA + 16, "data")}  # DEV-27: 8 on 8


def test_values_and_their_sizes(tmp_path):
    result = run(tmp_path, ".data\n.byte 1, 2\n.half 0x0304\n.word 5\n")
    assert [(v.address - DATA, v.size, v.directive) for v in result.values] == [
        (0, 1, ".byte"), (1, 1, ".byte"), (2, 2, ".half"), (4, 4, ".word")]
    assert data_image(result)[:8] == bytes([1, 2, 4, 3, 5, 0, 0, 0])


def test_a_value_may_be_an_expression_or_a_label(tmp_path):
    result = run(tmp_path, ".data\nx: .word 2 * 3 + 1\ny: .word x\nz: .word later\n.text\nlater: nop\n")
    assert messages(result) == []
    assert data_image(result)[:12] == (7).to_bytes(4, "little") + DATA.to_bytes(4, "little") \
        + TEXT.to_bytes(4, "little")


def test_strings_and_their_escapes(tmp_path):
    result = run(tmp_path, '.data\na: .ascii "ab"\nb: .asciz "c\\n"\nc: .string "d"\n')
    assert messages(result) == []
    assert data_image(result)[:8] == b"abc\n\0d\0\0"
    assert symbols(result)["b"] == (DATA + 2, "data")


def test_space_and_zero_reserve_bytes(tmp_path):
    result = run(tmp_path, ".data\na: .space 3\nb: .zero 2\nc: .byte 7\n")
    assert symbols(result) == {"a": (DATA, "data"), "b": (DATA + 3, "data"), "c": (DATA + 5, "data")}
    assert data_image(result)[:6] == b"\0\0\0\0\0\x07"


def test_leb128_encodings(tmp_path):  # examples of the DWARF standard
    result = run(tmp_path, ".data\na: .uleb128 624485\nb: .sleb128 -123456\n")
    assert data_image(result)[:6] == bytes([0xE5, 0x8E, 0x26, 0xC0, 0xBB, 0x78])
    assert symbols(result)["b"] == (DATA + 3, "data")


# ------------------------------------------------------------- alignment


def test_uleb128_needs_a_value_that_is_not_negative(tmp_path):
    result = run(tmp_path, ".data\n.uleb128 -5\n")
    assert messages(result) == [("Error", 2, 10, '"-5": operand is out of range')]


def test_align_directives(tmp_path):
    result = run(tmp_path, ".data\n.byte 1\n.align 3\na: .byte 2\n.p2align 2\nb: .byte 3\n"
                           ".balign 16\nc: .byte 4\n")
    assert symbols(result) == {"a": (DATA + 8, "data"), "b": (DATA + 12, "data"),
                               "c": (DATA + 16, "data")}


def test_p2align_pads_with_a_value_and_stops_at_max(tmp_path):
    result = run(tmp_path, ".data\n.byte 1\n.p2align 2, 0xFF\na: .byte 2\n"
                           ".p2align 4, 0, 2\nb: .byte 3\n")
    assert data_image(result)[:6] == bytes([1, 0xFF, 0xFF, 0xFF, 2, 3])
    assert symbols(result)["b"] == (DATA + 5, "data")  # 11 bytes needed, more than max 2


def test_align_zero_switches_automatic_alignment_off(tmp_path):
    result = run(tmp_path, ".data\n.byte 1\n.align 0\na: .word 2\nb: .dword 3\n"
                           ".data\nc: .word 4\n")
    assert symbols(result)["a"] == (DATA + 1, "data")
    assert symbols(result)["b"] == (DATA + 5, "data")
    assert symbols(result)["c"] == (DATA + 16, "data")  # a section directive switches it on again


# -------------------------------------------------------------- sections


def test_sections_share_the_data_area_and_are_recorded(tmp_path):
    result = run(tmp_path, ".data\na: .word 1\n.rodata\nb: .word 2\n.bss\nc: .space 4\n"
                           ".section .text\nnop\n")
    assert messages(result) == []
    assert symbols(result) == {"a": (DATA, "data"), "b": (DATA + 4, "data"),
                               "c": (DATA + 8, "data")}
    assert [p.address for p in result.text] == [TEXT]
    assert result.sections == (("text", TEXT, TEXT), ("data", DATA, DATA + 4),
                               ("rodata", DATA + 4, DATA + 8), ("bss", DATA + 8, DATA + 12),
                               ("text", TEXT, TEXT + 4))


@pytest.mark.parametrize("text, expected", [
    ('.section ".data"\nx: .word 1\n', (DATA, "data")),
    (".section .rodata\nx: .word 1\n", (DATA, "data")),
])
def test_section_names_in_quotes_and_without(tmp_path, text, expected):  # DEV-28
    assert symbols(run(tmp_path, text))["x"] == expected


def test_an_unknown_section_name_is_a_warning(tmp_path):
    result = run(tmp_path, ".section .foo\n.section\n")
    assert messages(result) == [("Warning", 1, 1, 'section name ".foo" is ignored'),
                                ("Warning", 2, 1, ".section without arguments is ignored")]


# --------------------------------------------------------------- symbols


def test_a_label_may_not_be_defined_twice(tmp_path):
    result = run(tmp_path, ".text\na: nop\na: nop\n")
    assert messages(result) == [("Error", 3, 1, 'label "a" already defined')]


def test_numeric_labels_keep_their_order(tmp_path):  # DEV-4
    result = run(tmp_path, ".text\n1: nop\nnop\n1: nop\n")
    assert [(label.number, label.address) for label in result.symbols.numeric] == [
        (1, TEXT), (1, TEXT + 8)]
    assert [label.order for label in result.symbols.numeric] < [p.order for p in result.text][-1:]


def test_globl_and_local(tmp_path):
    result = run(tmp_path, ".globl a, b\n.local b\n.text\na: nop\nb: nop\n")
    assert messages(result) == [] and result.symbols.globals == {"a"}


def test_a_global_label_must_be_defined(tmp_path):
    result = run(tmp_path, ".globl missing\n.text\nnop\n")
    assert messages(result) == [("Error", 1, 8, '"missing" declared global label but not defined.')]


def test_extern_symbols_live_in_their_own_area(tmp_path):
    result = run(tmp_path, ".extern one, 4\n.extern two, 8\n.data\nx: .word 1\n")
    assert symbols(result) == {"one": (EXTERN, "data"), "two": (EXTERN + 4, "data"),
                               "x": (DATA, "data")}
    assert result.symbols.globals == {"one", "two"}


def test_comm_reserves_data_and_is_global(tmp_path):
    result = run(tmp_path, ".data\nx: .byte 1\n.comm buffer, 8\n.comm small, 1\n.comm aligned, 4, 16\n")
    assert symbols(result) == {"x": (DATA, "data"), "buffer": (DATA + 4, "data"),
                               "small": (DATA + 12, "data"), "aligned": (DATA + 16, "data")}
    assert result.symbols.globals == {"buffer", "small", "aligned"}


def test_equ_defines_a_constant_that_may_be_redefined(tmp_path):
    result = run(tmp_path, ".equ N, 4\n.data\na: .space N\n.equ N, N * 2\nb: .space N\n")
    assert messages(result) == []
    assert symbols(result)["b"] == (DATA + 4, "data")
    assert result.symbols.values["N"].number == 8


def test_equ_may_not_use_a_symbol_defined_later_or_a_label_name(tmp_path):
    result = run(tmp_path, ".text\na: nop\n.equ a, 1\n.equ K, later\nlater: nop\n")
    assert messages(result) == [("Error", 3, 6, 'label "a" already defined'),
                                ("Error", 4, 9, 'Symbol "later" not found in symbol table.')]
    assert "K" not in result.symbols.values  # a failed .equ defines nothing


# ---------------------------------------------------------------- .option


def test_option_errors_and_warnings(tmp_path):
    result = run(tmp_path, ".option push\n.option norelax\n.option arch, +m\n.option pop\n"
                           ".option rvc\n.option pic\n.option arch, +c\n.option pop\n")
    assert messages(result) == [
        ("Warning", 2, 1, '".option norelax": has no effect on the assembled program'),
        ("Warning", 3, 1, '".option arch": has no effect on the assembled program'),
        ("Error", 5, 1, '".option rvc": the C extension is not supported'),
        ("Error", 6, 1, '".option pic": position independent code is not supported'),
        ("Error", 7, 1, '".option arch": extension "c" is not supported'),
        ("Error", 8, 1, '".option pop": no ".option push" before it')]


# -------------------------------------------------------------- unknown


def test_an_unknown_directive_is_ignored_with_a_warning(tmp_path):
    result = run(tmp_path, ".text\n.file \"x.s\"\nnop\n")
    assert messages(result) == [
        ("Warning", 2, 1, "pyRARS does not recognize the .file directive.  Ignored.")]
    assert [p.address for p in result.text] == [TEXT]
