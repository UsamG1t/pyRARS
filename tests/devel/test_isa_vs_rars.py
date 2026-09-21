"""pyrars.isa describes exactly the basic instructions of RARS.

1. The same mnemonics in RV32 and RV64.
2. The same fixed bits (RARS operation masks).
3. The same operand syntax (RARS example of each instruction).
4. The same machine words: a program with every instruction and boundary
   operand values, assembled by RARS, equals pyrars.isa.codec.encode.

1-3 compare with RARS_INSTRUCTIONS (recorded below) and need no Java.
"""

import re

import pytest

from pyrars.isa.codec import encode
from pyrars.isa.instructions import find, instructions
from pyrars.isa.registers import CSRS, ROUNDING_MODES
from pyrars.isa.spec import Csr, Offset, Reg, RoundingMode

pytestmark = pytest.mark.devel

XLENS = [32, 64]
TEXT_BASE = 0x00400000  # RARS Default memory configuration
ECALL = 0x00000073
NOP = 0x00000013  # addi x0, x0, 0


# Basic instructions of RARS 1.6: (xlen, name, example, operation mask).
# xlen None: in RV32 and RV64. Mask: 0/1 fixed bits, letters f,s,t,q,p mark
# the bits of operand 1..5. Recorded from rars1_6.jar: for each BasicInstruction
# of InstructionSet (RV32 and RV64 settings) getName(), getExampleFormat(),
# getOperationMask().
RARS_INSTRUCTIONS = (
    (None, 'add',       'add t1,t2,t3',                 '0000000tttttsssss000fffff0110011'),
    (None, 'addi',      'addi t1,t2,-100',              'ttttttttttttsssss000fffff0010011'),
    (  64, 'addiw',     'addiw t1,t2,-100',             'ttttttttttttsssss000fffff0011011'),
    (  64, 'addw',      'addw t1,t2,t3',                '0000000tttttsssss000fffff0111011'),
    (None, 'and',       'and t1,t2,t3',                 '0000000tttttsssss111fffff0110011'),
    (None, 'andi',      'andi t1,t2,-100',              'ttttttttttttsssss111fffff0010011'),
    (None, 'auipc',     'auipc t1,100000',              'ssssssssssssssssssssfffff0010111'),
    (None, 'beq',       'beq t1,t2,label',              'tttttttsssssfffff000ttttt1100011'),
    (None, 'bge',       'bge t1,t2,label',              'tttttttsssssfffff101ttttt1100011'),
    (None, 'bgeu',      'bgeu t1,t2,label',             'tttttttsssssfffff111ttttt1100011'),
    (None, 'blt',       'blt t1,t2,label',              'tttttttsssssfffff100ttttt1100011'),
    (None, 'bltu',      'bltu t1,t2,label',             'tttttttsssssfffff110ttttt1100011'),
    (None, 'bne',       'bne t1,t2,label',              'tttttttsssssfffff001ttttt1100011'),
    (None, 'csrrc',     'csrrc t0, fcsr, t1',           'ssssssssssssttttt011fffff1110011'),
    (None, 'csrrci',    'csrrci t0, fcsr, 10',          'ssssssssssssttttt111fffff1110011'),
    (None, 'csrrs',     'csrrs t0, fcsr, t1',           'ssssssssssssttttt010fffff1110011'),
    (None, 'csrrsi',    'csrrsi t0, fcsr, 10',          'ssssssssssssttttt110fffff1110011'),
    (None, 'csrrw',     'csrrw t0, fcsr, t1',           'ssssssssssssttttt001fffff1110011'),
    (None, 'csrrwi',    'csrrwi t0, fcsr, 10',          'ssssssssssssttttt101fffff1110011'),
    (None, 'div',       'div t1,t2,t3',                 '0000001tttttsssss100fffff0110011'),
    (None, 'divu',      'divu t1,t2,t3',                '0000001tttttsssss101fffff0110011'),
    (  64, 'divuw',     'divuw t1,t2,t3',               '0000001tttttsssss101fffff0111011'),
    (  64, 'divw',      'divw t1,t2,t3',                '0000001tttttsssss100fffff0111011'),
    (None, 'ebreak',    'ebreak',                       '00000000000100000000000001110011'),
    (None, 'ecall',     'ecall',                        '00000000000000000000000001110011'),
    (None, 'fadd.d',    'fadd.d f1, f2, f3, dyn',       '0000001tttttsssssqqqfffff1010011'),
    (None, 'fadd.s',    'fadd.s f1, f2, f3, dyn',       '0000000tttttsssssqqqfffff1010011'),
    (None, 'fclass.d',  'fclass.d t1, f1',              '111000100000sssss001fffff1010011'),
    (None, 'fclass.s',  'fclass.s t1, f1',              '111000000000sssss001fffff1010011'),
    (  64, 'fcvt.d.l',  'fcvt.d.l f1, t1, dyn',         '110100100010ssssstttfffff1010011'),
    (  64, 'fcvt.d.lu', 'fcvt.d.lu f1, t1, dyn',        '110100100011ssssstttfffff1010011'),
    (None, 'fcvt.d.s',  'fcvt.d.s f1, f2, dyn',         '010000100000ssssstttfffff1010011'),
    (None, 'fcvt.d.w',  'fcvt.d.w f1, t1, dyn',         '110100100000ssssstttfffff1010011'),
    (None, 'fcvt.d.wu', 'fcvt.d.wu f1, t1, dyn',        '110100100001ssssstttfffff1010011'),
    (  64, 'fcvt.l.d',  'fcvt.l.d t1, f1, dyn',         '110000100010ssssstttfffff1010011'),
    (  64, 'fcvt.l.s',  'fcvt.l.s t1, f1, dyn',         '110000000010ssssstttfffff1010011'),
    (  64, 'fcvt.lu.d', 'fcvt.lu.d t1, f1, dyn',        '110000100011ssssstttfffff1010011'),
    (  64, 'fcvt.lu.s', 'fcvt.lu.s t1, f1, dyn',        '110000000011ssssstttfffff1010011'),
    (None, 'fcvt.s.d',  'fcvt.s.d f1, f2, dyn',         '010000000001ssssstttfffff1010011'),
    (  64, 'fcvt.s.l',  'fcvt.s.l f1, t1, dyn',         '110100000010ssssstttfffff1010011'),
    (  64, 'fcvt.s.lu', 'fcvt.s.lu f1, t1, dyn',        '110100000011ssssstttfffff1010011'),
    (None, 'fcvt.s.w',  'fcvt.s.w f1, t1, dyn',         '110100000000ssssstttfffff1010011'),
    (None, 'fcvt.s.wu', 'fcvt.s.wu f1, t1, dyn',        '110100000001ssssstttfffff1010011'),
    (None, 'fcvt.w.d',  'fcvt.w.d t1, f1, dyn',         '110000100000ssssstttfffff1010011'),
    (None, 'fcvt.w.s',  'fcvt.w.s t1, f1, dyn',         '110000000000ssssstttfffff1010011'),
    (None, 'fcvt.wu.d', 'fcvt.wu.d t1, f1, dyn',        '110000100001ssssstttfffff1010011'),
    (None, 'fcvt.wu.s', 'fcvt.wu.s t1, f1, dyn',        '110000000001ssssstttfffff1010011'),
    (None, 'fdiv.d',    'fdiv.d f1, f2, f3, dyn',       '0001101tttttsssssqqqfffff1010011'),
    (None, 'fdiv.s',    'fdiv.s f1, f2, f3, dyn',       '0001100tttttsssssqqqfffff1010011'),
    (None, 'fence',     'fence 1, 1',                   '0000ffffssss00000000000000001111'),
    (None, 'fence.i',   'fence.i',                      '00000000000000000001000000001111'),
    (None, 'feq.d',     'feq.d t1, f1, f2',             '1010001tttttsssss010fffff1010011'),
    (None, 'feq.s',     'feq.s t1, f1, f2',             '1010000tttttsssss010fffff1010011'),
    (None, 'fld',       'fld f1, -100(t1)',             'ssssssssssssttttt011fffff0000111'),
    (None, 'fle.d',     'fle.d t1, f1, f2',             '1010001tttttsssss000fffff1010011'),
    (None, 'fle.s',     'fle.s t1, f1, f2',             '1010000tttttsssss000fffff1010011'),
    (None, 'flt.d',     'flt.d t1, f1, f2',             '1010001tttttsssss001fffff1010011'),
    (None, 'flt.s',     'flt.s t1, f1, f2',             '1010000tttttsssss001fffff1010011'),
    (None, 'flw',       'flw f1, -100(t1)',             'ssssssssssssttttt010fffff0000111'),
    (None, 'fmadd.d',   'fmadd.d f1, f2, f3, f4, dyn',  'qqqqq01tttttssssspppfffff1000011'),
    (None, 'fmadd.s',   'fmadd.s f1, f2, f3, f4, dyn',  'qqqqq00tttttssssspppfffff1000011'),
    (None, 'fmax.d',    'fmax.d f1, f2, f3',            '0010101tttttsssss001fffff1010011'),
    (None, 'fmax.s',    'fmax.s f1, f2, f3',            '0010100tttttsssss001fffff1010011'),
    (None, 'fmin.d',    'fmin.d f1, f2, f3',            '0010101tttttsssss000fffff1010011'),
    (None, 'fmin.s',    'fmin.s f1, f2, f3',            '0010100tttttsssss000fffff1010011'),
    (None, 'fmsub.d',   'fmsub.d f1, f2, f3, f4, dyn',  'qqqqq01tttttssssspppfffff1000111'),
    (None, 'fmsub.s',   'fmsub.s f1, f2, f3, f4, dyn',  'qqqqq00tttttssssspppfffff1000111'),
    (None, 'fmul.d',    'fmul.d f1, f2, f3, dyn',       '0001001tttttsssssqqqfffff1010011'),
    (None, 'fmul.s',    'fmul.s f1, f2, f3, dyn',       '0001000tttttsssssqqqfffff1010011'),
    (  64, 'fmv.d.x',   'fmv.d.x f1, t1',               '111100100000sssss000fffff1010011'),
    (None, 'fmv.s.x',   'fmv.s.x f1, t1',               '111100000000sssss000fffff1010011'),
    (  64, 'fmv.x.d',   'fmv.x.d t1, f1',               '111000100000sssss000fffff1010011'),
    (None, 'fmv.x.s',   'fmv.x.s t1, f1',               '111000000000sssss000fffff1010011'),
    (None, 'fnmadd.d',  'fnmadd.d f1, f2, f3, f4, dyn', 'qqqqq01tttttssssspppfffff1001111'),
    (None, 'fnmadd.s',  'fnmadd.s f1, f2, f3, f4, dyn', 'qqqqq00tttttssssspppfffff1001111'),
    (None, 'fnmsub.d',  'fnmsub.d f1, f2, f3, f4, dyn', 'qqqqq01tttttssssspppfffff1001011'),
    (None, 'fnmsub.s',  'fnmsub.s f1, f2, f3, f4, dyn', 'qqqqq00tttttssssspppfffff1001011'),
    (None, 'fsd',       'fsd f1, -100(t1)',             'sssssssfffffttttt011sssss0100111'),
    (None, 'fsgnj.d',   'fsgnj.d f1, f2, f3',           '0010001tttttsssss000fffff1010011'),
    (None, 'fsgnj.s',   'fsgnj.s f1, f2, f3',           '0010000tttttsssss000fffff1010011'),
    (None, 'fsgnjn.d',  'fsgnjn.d f1, f2, f3',          '0010001tttttsssss001fffff1010011'),
    (None, 'fsgnjn.s',  'fsgnjn.s f1, f2, f3',          '0010000tttttsssss001fffff1010011'),
    (None, 'fsgnjx.d',  'fsgnjx.d f1, f2, f3',          '0010001tttttsssss010fffff1010011'),
    (None, 'fsgnjx.s',  'fsgnjx.s f1, f2, f3',          '0010000tttttsssss010fffff1010011'),
    (None, 'fsqrt.d',   'fsqrt.d f1, f2, dyn',          '010110100000ssssstttfffff1010011'),
    (None, 'fsqrt.s',   'fsqrt.s f1, f2, dyn',          '010110000000ssssstttfffff1010011'),
    (None, 'fsub.d',    'fsub.d f1, f2, f3, dyn',       '0000101tttttsssssqqqfffff1010011'),
    (None, 'fsub.s',    'fsub.s f1, f2, f3, dyn',       '0000100tttttsssssqqqfffff1010011'),
    (None, 'fsw',       'fsw f1, -100(t1)',             'sssssssfffffttttt010sssss0100111'),
    (None, 'jal',       'jal t1, target',               'ssssssssssssssssssssfffff1101111'),
    (None, 'jalr',      'jalr t1, t2, -100',            'ttttttttttttsssss000fffff1100111'),
    (None, 'lb',        'lb t1, -100(t2)',              'ssssssssssssttttt000fffff0000011'),
    (None, 'lbu',       'lbu t1, -100(t2)',             'ssssssssssssttttt100fffff0000011'),
    (  64, 'ld',        'ld t1, -100(t2)',              'ssssssssssssttttt011fffff0000011'),
    (None, 'lh',        'lh t1, -100(t2)',              'ssssssssssssttttt001fffff0000011'),
    (None, 'lhu',       'lhu t1, -100(t2)',             'ssssssssssssttttt101fffff0000011'),
    (None, 'lui',       'lui t1,100000',                'ssssssssssssssssssssfffff0110111'),
    (None, 'lw',        'lw t1, -100(t2)',              'ssssssssssssttttt010fffff0000011'),
    (  64, 'lwu',       'lwu t1, -100(t2)',             'ssssssssssssttttt110fffff0000011'),
    (None, 'mul',       'mul t1,t2,t3',                 '0000001tttttsssss000fffff0110011'),
    (None, 'mulh',      'mulh t1,t2,t3',                '0000001tttttsssss001fffff0110011'),
    (None, 'mulhsu',    'mulhsu t1,t2,t3',              '0000001tttttsssss010fffff0110011'),
    (None, 'mulhu',     'mulhu t1,t2,t3',               '0000001tttttsssss011fffff0110011'),
    (  64, 'mulw',      'mulw t1,t2,t3',                '0000001tttttsssss000fffff0111011'),
    (None, 'or',        'or t1,t2,t3',                  '0000000tttttsssss110fffff0110011'),
    (None, 'ori',       'ori t1,t2,-100',               'ttttttttttttsssss110fffff0010011'),
    (None, 'rem',       'rem t1,t2,t3',                 '0000001tttttsssss110fffff0110011'),
    (None, 'remu',      'remu t1,t2,t3',                '0000001tttttsssss111fffff0110011'),
    (  64, 'remuw',     'remuw t1,t2,t3',               '0000001tttttsssss111fffff0111011'),
    (  64, 'remw',      'remw t1,t2,t3',                '0000001tttttsssss110fffff0111011'),
    (None, 'sb',        'sb t1, -100(t2)',              'sssssssfffffttttt000sssss0100011'),
    (  64, 'sd',        'sd t1, -100(t2)',              'sssssssfffffttttt011sssss0100011'),
    (None, 'sh',        'sh t1, -100(t2)',              'sssssssfffffttttt001sssss0100011'),
    (None, 'sll',       'sll t1,t2,t3',                 '0000000tttttsssss001fffff0110011'),
    (  32, 'slli',      'slli t1,t2,10',                '0000000tttttsssss001fffff0010011'),
    (  64, 'slli',      'slli t1,t2,33',                '000000ttttttsssss001fffff0010011'),
    (  64, 'slliw',     'slliw t1,t2,10',               '0000000tttttsssss001fffff0011011'),
    (  64, 'sllw',      'sllw t1,t2,t3',                '0000000tttttsssss001fffff0111011'),
    (None, 'slt',       'slt t1,t2,t3',                 '0000000tttttsssss010fffff0110011'),
    (None, 'slti',      'slti t1,t2,-100',              'ttttttttttttsssss010fffff0010011'),
    (None, 'sltiu',     'sltiu t1,t2,-100',             'ttttttttttttsssss011fffff0010011'),
    (None, 'sltu',      'sltu t1,t2,t3',                '0000000tttttsssss011fffff0110011'),
    (None, 'sra',       'sra t1,t2,t3',                 '0100000tttttsssss101fffff0110011'),
    (  32, 'srai',      'srai t1,t2,10',                '0100000tttttsssss101fffff0010011'),
    (  64, 'srai',      'srai t1,t2,33',                '010000ttttttsssss101fffff0010011'),
    (  64, 'sraiw',     'sraiw t1,t2,10',               '0100000tttttsssss101fffff0011011'),
    (  64, 'sraw',      'sraw t1,t2,t3',                '0100000tttttsssss101fffff0111011'),
    (None, 'srl',       'srl t1,t2,t3',                 '0000000tttttsssss101fffff0110011'),
    (  32, 'srli',      'srli t1,t2,10',                '0000000tttttsssss101fffff0010011'),
    (  64, 'srli',      'srli t1,t2,33',                '000000ttttttsssss101fffff0010011'),
    (  64, 'srliw',     'srliw t1,t2,10',               '0000000tttttsssss101fffff0011011'),
    (  64, 'srlw',      'srlw t1,t2,t3',                '0000000tttttsssss101fffff0111011'),
    (None, 'sub',       'sub t1,t2,t3',                 '0100000tttttsssss000fffff0110011'),
    (  64, 'subw',      'subw t1,t2,t3',                '0100000tttttsssss000fffff0111011'),
    (None, 'sw',        'sw t1, -100(t2)',              'sssssssfffffttttt010sssss0100011'),
    (None, 'uret',      'uret',                         '00000000001000000000000001110011'),
    (None, 'wfi',       'wfi',                          '00010000010100000000000001110011'),
    (None, 'xor',       'xor t1,t2,t3',                 '0000000tttttsssss100fffff0110011'),
    (None, 'xori',      'xori t1,t2,-100',              'ttttttttttttsssss100fffff0010011'),
)


# Deliberate deviation: pyrars uses the F v2.2 names (ISA manual, F chapter:
# "fmv.w.x and fmv.x.w ... were previously called fmv.s.x and fmv.x.s").
RENAMED = {"fmv.x.s": "fmv.x.w", "fmv.s.x": "fmv.w.x"}


def rars_table(xlen):
    """{our name: (example, mask)} of the RARS basic instructions in RV32 or RV64."""
    return {RENAMED.get(name, name): (example, mask)
            for x, name, example, mask in RARS_INSTRUCTIONS if x in (None, xlen)}


@pytest.mark.parametrize("xlen", XLENS)
def test_same_instructions(xlen):
    ours = {i.mnemonic for i in instructions(xlen)}
    assert ours == set(rars_table(xlen))


@pytest.mark.parametrize("xlen", XLENS)
def test_same_fixed_bits(xlen):
    for name, (_, rars_mask) in rars_table(xlen).items():
        mask = int("".join("1" if c in "01" else "0" for c in rars_mask), 2)
        match = int("".join("1" if c == "1" else "0" for c in rars_mask), 2)
        instr = find(name, xlen)
        assert (hex(instr.mask), hex(instr.match)) == (hex(mask), hex(match)), name


def rars_operand_kinds(example):
    """Operand kinds of a RARS example like "lw t1, -100(t2)": x f csr rm imm ( )."""
    operands = example.partition(" ")[2]
    kinds = []
    for token in re.findall(r"[^\s,()]+|[()]", operands):
        if token in "()":
            kinds.append(token)
        elif re.fullmatch(r"t\d", token):
            kinds.append("x")
        elif re.fullmatch(r"f\d", token):
            kinds.append("f")
        elif token == "fcsr":
            kinds.append("csr")
        elif token == "dyn":
            kinds.append("rm")
        else:  # number or label
            kinds.append("imm")
    return kinds


def our_operand_kinds(instr):
    kinds = []
    for token in re.findall(r"[a-z][a-z0-9]*|[()]", instr.syntax):
        if token in "()":
            kinds.append(token)
            continue
        kind = instr.format.fields[token].kind
        if kind is Reg:
            kinds.append("f" if instr.is_fp(token) else "x")
        elif kind is Csr:
            kinds.append("csr")
        elif kind is RoundingMode:
            kinds.append("rm")
        else:
            kinds.append("imm")
    return kinds


@pytest.mark.parametrize("xlen", XLENS)
def test_same_operand_syntax(xlen):
    for name, (example, _) in rars_table(xlen).items():
        assert our_operand_kinds(find(name, xlen)) == rars_operand_kinds(example), name


# ------------------------------------------------------ machine words


REGISTERS = ([1, 2, 3, 4], [31, 17, 8, 22])  # per variant, for the 1st..4th register operand
CSR_NAMES = ("fcsr", "instreth")
RM_NAMES = ("rtz", "dyn")
LABELS = ("first", "last")


def sample(instr, variant, pc, last):
    """Assembly text of instr and its operand values; variant 0 or 1."""
    values, texts, regs = {}, {}, iter(REGISTERS[variant])
    for name in instr.operands:
        field = instr.format.fields[name]
        if field.kind is Reg:
            values[name] = next(regs)
            texts[name] = ("f" if instr.is_fp(name) else "x") + str(values[name])
        elif field.kind is Csr:
            texts[name] = CSR_NAMES[variant]
            values[name] = CSRS[texts[name]]
        elif field.kind is RoundingMode:
            texts[name] = RM_NAMES[variant]
            values[name] = ROUNDING_MODES[texts[name]]
        elif field.kind is Offset:
            texts[name] = LABELS[variant]
            values[name] = (TEXT_BASE if variant == 0 else last) - pc
        elif field.kind.signed:
            values[name] = -(1 << (field.width - 1)) if variant == 0 else (1 << (field.width - 1)) - 1
            texts[name] = str(values[name])
        else:  # all ones, or alternating bits 0101...
            values[name] = (1 << field.width) - 1 if variant == 0 else ((1 << field.width) - 1) // 3
            texts[name] = str(values[name])
    operands = re.sub(r"[a-z][a-z0-9]*", lambda m: texts[m[0]], instr.syntax)
    return f"{instr.mnemonic} {operands}", values


# Padding between the labels and the tested lines: branch offsets then cross
# +-2048, so both values of offset bits 11 and 12 occur.
PAD = 375


@pytest.mark.parametrize("xlen", XLENS)
def test_same_machine_words(rars, tmp_path, xlen):
    table = [(instr, variant) for instr in instructions(xlen) for variant in (0, 1)]
    start = TEXT_BASE + 4 * PAD
    last = start + 4 * (len(table) + PAD)
    lines, words = [], []
    for n, (instr, variant) in enumerate(table):
        text, values = sample(instr, variant, start + 4 * n, last)
        lines.append(text)
        words.append(encode(instr, values))
    pad = ["addi x0, x0, 0"] * PAD
    source = tmp_path / "all.s"
    source.write_text("\n".join([".text", "first:", *pad, *lines, *pad, "last:", "ecall", ""]))

    result = rars.assemble([source], options=("rv64",) if xlen == 64 else ())

    assert result.messages == []
    assert result.text[:PAD] == [NOP] * PAD
    assert result.text[PAD + len(words):] == [NOP] * PAD + [ECALL]
    wrong = [f"{line}: ours {ours:08x}, rars {theirs:08x}"
             for line, ours, theirs in zip(lines, words, result.text[PAD:])
             if ours != theirs]
    assert wrong == []
