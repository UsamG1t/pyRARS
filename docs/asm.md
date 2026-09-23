# pyRARS assembler

A RISC-V assembler written in pure Python. It reads assembly source files and produces the machine
code of the text segment, the image of the data segment, a symbol table and diagnostics; a
disassembler turns a machine word back into text. The dialect is inspired by
[RARS](https://github.com/TheThirdOne/rars) and brought in line with the RISC-V assembly manual and
GNU `as`, so that source written for either of them assembles here.

Supported base and extensions: RV32I and RV64I with M (integer multiplication and division), F
(single precision floating point), D (double precision floating point), Zicsr (control and status
registers), Zifencei (instruction fetch fence), plus `ecall`, `ebreak`, `wfi` and `uret`. There are
no compressed (C) and no atomic (A) instructions.

Entry points: the command line `python -m pyrars`, and `pyrars.asm.assembler.assemble(paths,
options)` for use from other code.

## Command line

```
python -m pyrars asm    [options] file...     assemble source files into machine code
python -m pyrars disasm [options] file        read a dump of instruction words back
```

Messages are written to the error stream, everything else to the standard output. The exit code is
`1` when the program has errors and `0` otherwise.

### `asm`

| Short | Long | Meaning |
|---|---|---|
| `-x` | `--xlen {32,64}` | width of the registers; default `32` |
| `-m` | `--mem-config NAME` | memory configuration: `Default`, `CompactDataAtZero`, `CompactTextAtZero` |
| `-d` | `--dump SEGMENT:FORMAT:FILE` | write a segment to a file; may be repeated |
| `-l` | `--listing` | print the text segment: address, word, instruction, source line |
| `-s` | `--symbols` | print the symbol table, marking the global names |
| `-a` | `--abi-names` | write register names of the calling convention (`t0`) instead of numbers (`x5`) |
| `-w` | `--warnings-are-errors` | a warning makes the program fail |
| | `--no-pseudo` | forbid pseudo-instructions |
| | `--start-at-main` | the entry point is the label `main` when the program defines one |

`SEGMENT` is `.text` or `.data`, `FILE` is a path or `-` for the standard output.

| Format | Content |
|---|---|
| `hex` | one word per line, eight hexadecimal digits |
| `bin` | raw bytes, little endian; needs a file |
| `text` | a table: address and word, with the instruction text for `.text` |

### `disasm`

| Short | Long | Meaning |
|---|---|---|
| `-f` | `--format {hex,bin}` | format of the input file; default `hex` |
| `-b` | `--base ADDRESS` | address of the first word; default: the text base of the configuration |
| `-x` | `--xlen {32,64}` | width of the registers; default `32` |
| `-m` | `--mem-config NAME` | memory configuration, used for the default base address |
| `-a` | `--abi-names` | register names of the calling convention |
| `-p` | `--pseudo` | name the pseudo-instruction a word stands for |

A word that is no instruction of the set keeps its text column empty.

## Instruction formats

An instruction is one 32-bit word. The formats differ in which fields the word holds.

| Format | Fields | Used by |
|---|---|---|
| R | funct7, rs2, rs1, funct3, rd, opcode | register-register operations |
| R (rm) | funct7, rs2, rs1, rounding mode, rd, opcode | floating point operations with a rounding mode |
| R4 | rs3, funct2, rs2, rs1, rounding mode, rd, opcode | fused multiply-add |
| I | imm[11:0], rs1, funct3, rd, opcode | operations with an immediate, loads, jumps to a register |
| I (shift) | funct, shamt, rs1, funct3, rd, opcode | shifts by a constant: 5 bits of shift amount in RV32, 6 in RV64 |
| S | imm[11:5], rs2, rs1, funct3, imm[4:0], opcode | stores |
| B | imm[12\|10:5], rs2, rs1, funct3, imm[4:1\|11], opcode | conditional branches; the target is even |
| U | imm[31:12], rd, opcode | upper immediate |
| J | imm[20\|10:1\|11\|19:12], rd, opcode | jump and link; the target is even |
| Fence | fm, pred, succ, rs1, funct3, rd, opcode | memory ordering |
| CSR | csr, rs1, funct3, rd, opcode | control and status register, source is a register |
| CSR (imm) | csr, uimm, funct3, rd, opcode | control and status register, source is a 5-bit constant |

Ranges of the operand fields: a 12-bit immediate holds −2048…2047, an upper immediate 0…0xFFFFF,
a shift amount 0…31 in RV32 and 0…63 in RV64, a CSR number 0…4095, a 5-bit constant 0…31.

## Instructions

### RV32I and RV64I base

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| lui | U | `lui rd, imm` | write the immediate shifted left by 12 bits into rd |
| auipc | U | `auipc rd, imm` | add the immediate shifted left by 12 bits to the address of the instruction, write the sum into rd |
| jal | J | `jal rd, offset` | write the address of the next instruction into rd and jump to the target |
| jalr | I | `jalr rd, rs1, imm` | write the address of the next instruction into rd and jump to rs1 + imm |
| beq | B | `beq rs1, rs2, offset` | branch to the target when rs1 equals rs2 |
| bne | B | `bne rs1, rs2, offset` | branch when rs1 differs from rs2 |
| blt | B | `blt rs1, rs2, offset` | branch when rs1 is less than rs2, signed |
| bge | B | `bge rs1, rs2, offset` | branch when rs1 is greater than or equal to rs2, signed |
| bltu | B | `bltu rs1, rs2, offset` | branch when rs1 is less than rs2, unsigned |
| bgeu | B | `bgeu rs1, rs2, offset` | branch when rs1 is greater than or equal to rs2, unsigned |
| lb | I | `lb rd, imm(rs1)` | load one byte from rs1 + imm into rd, sign extended |
| lh | I | `lh rd, imm(rs1)` | load two bytes, sign extended |
| lw | I | `lw rd, imm(rs1)` | load four bytes; in RV64 sign extended |
| lbu | I | `lbu rd, imm(rs1)` | load one byte, zero extended |
| lhu | I | `lhu rd, imm(rs1)` | load two bytes, zero extended |
| sb | S | `sb rs2, imm(rs1)` | store the low byte of rs2 at rs1 + imm |
| sh | S | `sh rs2, imm(rs1)` | store the low two bytes of rs2 |
| sw | S | `sw rs2, imm(rs1)` | store the low four bytes of rs2 |
| addi | I | `addi rd, rs1, imm` | write rs1 + imm into rd |
| slti | I | `slti rd, rs1, imm` | write 1 into rd when rs1 is less than imm, signed, else 0 |
| sltiu | I | `sltiu rd, rs1, imm` | the same comparison, unsigned |
| xori | I | `xori rd, rs1, imm` | write the bitwise exclusive or of rs1 and imm into rd |
| ori | I | `ori rd, rs1, imm` | write the bitwise or into rd |
| andi | I | `andi rd, rs1, imm` | write the bitwise and into rd |
| slli | I (shift) | `slli rd, rs1, shamt` | write rs1 shifted left by shamt into rd |
| srli | I (shift) | `srli rd, rs1, shamt` | shift right, filling with zeros |
| srai | I (shift) | `srai rd, rs1, shamt` | shift right, keeping the sign |
| add | R | `add rd, rs1, rs2` | write rs1 + rs2 into rd |
| sub | R | `sub rd, rs1, rs2` | write rs1 − rs2 into rd |
| sll | R | `sll rd, rs1, rs2` | shift rs1 left by the low bits of rs2 |
| slt | R | `slt rd, rs1, rs2` | write 1 into rd when rs1 is less than rs2, signed, else 0 |
| sltu | R | `sltu rd, rs1, rs2` | the same comparison, unsigned |
| xor | R | `xor rd, rs1, rs2` | bitwise exclusive or |
| srl | R | `srl rd, rs1, rs2` | shift rs1 right by the low bits of rs2, filling with zeros |
| sra | R | `sra rd, rs1, rs2` | shift right, keeping the sign |
| or | R | `or rd, rs1, rs2` | bitwise or |
| and | R | `and rd, rs1, rs2` | bitwise and |
| fence | Fence | `fence pred, succ` | order the memory accesses of the sets pred and succ |
| ecall | I | `ecall` | call the execution environment |
| ebreak | I | `ebreak` | return control to the debugger |

### RV64I only

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| lwu | I | `lwu rd, imm(rs1)` | load four bytes, zero extended |
| ld | I | `ld rd, imm(rs1)` | load eight bytes |
| sd | S | `sd rs2, imm(rs1)` | store eight bytes |
| addiw | I | `addiw rd, rs1, imm` | add imm to rs1 in 32 bits, write the result sign extended into rd |
| slliw | I (shift) | `slliw rd, rs1, shamt` | shift the low 32 bits of rs1 left, result sign extended |
| srliw | I (shift) | `srliw rd, rs1, shamt` | shift the low 32 bits right, filling with zeros |
| sraiw | I (shift) | `sraiw rd, rs1, shamt` | shift the low 32 bits right, keeping the sign |
| addw | R | `addw rd, rs1, rs2` | add in 32 bits, result sign extended |
| subw | R | `subw rd, rs1, rs2` | subtract in 32 bits, result sign extended |
| sllw | R | `sllw rd, rs1, rs2` | shift the low 32 bits left by the low bits of rs2 |
| srlw | R | `srlw rd, rs1, rs2` | shift the low 32 bits right, filling with zeros |
| sraw | R | `sraw rd, rs1, rs2` | shift the low 32 bits right, keeping the sign |

### M: multiplication and division

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| mul | R | `mul rd, rs1, rs2` | write the low half of the product into rd |
| mulh | R | `mulh rd, rs1, rs2` | write the high half of the product, both factors signed |
| mulhsu | R | `mulhsu rd, rs1, rs2` | high half, rs1 signed and rs2 unsigned |
| mulhu | R | `mulhu rd, rs1, rs2` | high half, both factors unsigned |
| div | R | `div rd, rs1, rs2` | signed quotient, truncated towards zero |
| divu | R | `divu rd, rs1, rs2` | unsigned quotient |
| rem | R | `rem rd, rs1, rs2` | signed remainder, its sign follows rs1 |
| remu | R | `remu rd, rs1, rs2` | unsigned remainder |
| mulw | R | `mulw rd, rs1, rs2` | RV64: product of the low 32 bits, result sign extended |
| divw | R | `divw rd, rs1, rs2` | RV64: signed quotient of the low 32 bits |
| divuw | R | `divuw rd, rs1, rs2` | RV64: unsigned quotient of the low 32 bits |
| remw | R | `remw rd, rs1, rs2` | RV64: signed remainder of the low 32 bits |
| remuw | R | `remuw rd, rs1, rs2` | RV64: unsigned remainder of the low 32 bits |

### F: single precision floating point

The rounding mode is the last operand; when it is left out, `dyn` is used, which takes the mode
from the `frm` field of `fcsr`. The modes are `rne` (to nearest, ties to even), `rtz` (towards
zero), `rdn` (down), `rup` (up), `rmm` (to nearest, ties away from zero) and `dyn`.

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| flw | I | `flw rd, imm(rs1)` | load four bytes into the floating point register rd |
| fsw | S | `fsw rs2, imm(rs1)` | store the low four bytes of the floating point register rs2 |
| fadd.s | R (rm) | `fadd.s rd, rs1, rs2, rm` | write rs1 + rs2 into rd |
| fsub.s | R (rm) | `fsub.s rd, rs1, rs2, rm` | write rs1 − rs2 into rd |
| fmul.s | R (rm) | `fmul.s rd, rs1, rs2, rm` | write rs1 × rs2 into rd |
| fdiv.s | R (rm) | `fdiv.s rd, rs1, rs2, rm` | write rs1 ÷ rs2 into rd |
| fsqrt.s | R (rm) | `fsqrt.s rd, rs1, rm` | write the square root of rs1 into rd |
| fmadd.s | R4 | `fmadd.s rd, rs1, rs2, rs3, rm` | write rs1 × rs2 + rs3 into rd, rounded once |
| fmsub.s | R4 | `fmsub.s rd, rs1, rs2, rs3, rm` | write rs1 × rs2 − rs3 into rd |
| fnmadd.s | R4 | `fnmadd.s rd, rs1, rs2, rs3, rm` | write −(rs1 × rs2 + rs3) into rd |
| fnmsub.s | R4 | `fnmsub.s rd, rs1, rs2, rs3, rm` | write −(rs1 × rs2 − rs3) into rd |
| fmin.s | R | `fmin.s rd, rs1, rs2` | write the smaller of rs1 and rs2 into rd |
| fmax.s | R | `fmax.s rd, rs1, rs2` | write the larger into rd |
| fsgnj.s | R | `fsgnj.s rd, rs1, rs2` | write rs1 with the sign of rs2 into rd |
| fsgnjn.s | R | `fsgnjn.s rd, rs1, rs2` | write rs1 with the opposite sign of rs2 |
| fsgnjx.s | R | `fsgnjx.s rd, rs1, rs2` | write rs1 with the exclusive or of both signs |
| feq.s | R | `feq.s rd, rs1, rs2` | write 1 into the integer register rd when rs1 equals rs2 |
| flt.s | R | `flt.s rd, rs1, rs2` | write 1 when rs1 is less than rs2 |
| fle.s | R | `fle.s rd, rs1, rs2` | write 1 when rs1 is less than or equal to rs2 |
| fclass.s | R | `fclass.s rd, rs1` | write the class of rs1 as a bit mask into the integer register rd |
| fcvt.w.s | R (rm) | `fcvt.w.s rd, rs1, rm` | convert rs1 to a signed 32-bit integer in rd |
| fcvt.wu.s | R (rm) | `fcvt.wu.s rd, rs1, rm` | convert to an unsigned 32-bit integer |
| fcvt.s.w | R (rm) | `fcvt.s.w rd, rs1, rm` | convert the signed 32-bit integer rs1 to a float |
| fcvt.s.wu | R (rm) | `fcvt.s.wu rd, rs1, rm` | convert the unsigned 32-bit integer rs1 to a float |
| fcvt.l.s | R (rm) | `fcvt.l.s rd, rs1, rm` | RV64: convert rs1 to a signed 64-bit integer |
| fcvt.lu.s | R (rm) | `fcvt.lu.s rd, rs1, rm` | RV64: convert to an unsigned 64-bit integer |
| fcvt.s.l | R (rm) | `fcvt.s.l rd, rs1, rm` | RV64: convert the signed 64-bit integer rs1 to a float |
| fcvt.s.lu | R (rm) | `fcvt.s.lu rd, rs1, rm` | RV64: convert the unsigned 64-bit integer rs1 to a float |
| fmv.x.w | R | `fmv.x.w rd, rs1` | copy the bits of the floating point register rs1 into the integer register rd |
| fmv.w.x | R | `fmv.w.x rd, rs1` | copy the low bits of the integer register rs1 into the floating point register rd |

`fmv.x.s` and `fmv.s.x` are accepted as the older names of `fmv.x.w` and `fmv.w.x`.

### D: double precision floating point

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| fld | I | `fld rd, imm(rs1)` | load eight bytes into the floating point register rd |
| fsd | S | `fsd rs2, imm(rs1)` | store eight bytes of the floating point register rs2 |
| fadd.d | R (rm) | `fadd.d rd, rs1, rs2, rm` | write rs1 + rs2 into rd |
| fsub.d | R (rm) | `fsub.d rd, rs1, rs2, rm` | write rs1 − rs2 into rd |
| fmul.d | R (rm) | `fmul.d rd, rs1, rs2, rm` | write rs1 × rs2 into rd |
| fdiv.d | R (rm) | `fdiv.d rd, rs1, rs2, rm` | write rs1 ÷ rs2 into rd |
| fsqrt.d | R (rm) | `fsqrt.d rd, rs1, rm` | write the square root of rs1 into rd |
| fmadd.d | R4 | `fmadd.d rd, rs1, rs2, rs3, rm` | write rs1 × rs2 + rs3 into rd, rounded once |
| fmsub.d | R4 | `fmsub.d rd, rs1, rs2, rs3, rm` | write rs1 × rs2 − rs3 into rd |
| fnmadd.d | R4 | `fnmadd.d rd, rs1, rs2, rs3, rm` | write −(rs1 × rs2 + rs3) into rd |
| fnmsub.d | R4 | `fnmsub.d rd, rs1, rs2, rs3, rm` | write −(rs1 × rs2 − rs3) into rd |
| fmin.d | R | `fmin.d rd, rs1, rs2` | write the smaller of rs1 and rs2 into rd |
| fmax.d | R | `fmax.d rd, rs1, rs2` | write the larger into rd |
| fsgnj.d | R | `fsgnj.d rd, rs1, rs2` | write rs1 with the sign of rs2 into rd |
| fsgnjn.d | R | `fsgnjn.d rd, rs1, rs2` | write rs1 with the opposite sign of rs2 |
| fsgnjx.d | R | `fsgnjx.d rd, rs1, rs2` | write rs1 with the exclusive or of both signs |
| feq.d | R | `feq.d rd, rs1, rs2` | write 1 into the integer register rd when rs1 equals rs2 |
| flt.d | R | `flt.d rd, rs1, rs2` | write 1 when rs1 is less than rs2 |
| fle.d | R | `fle.d rd, rs1, rs2` | write 1 when rs1 is less than or equal to rs2 |
| fclass.d | R | `fclass.d rd, rs1` | write the class of rs1 as a bit mask into the integer register rd |
| fcvt.s.d | R (rm) | `fcvt.s.d rd, rs1, rm` | convert the double rs1 to a single precision value |
| fcvt.d.s | R (rm) | `fcvt.d.s rd, rs1, rm` | convert the single precision value rs1 to a double |
| fcvt.w.d | R (rm) | `fcvt.w.d rd, rs1, rm` | convert rs1 to a signed 32-bit integer |
| fcvt.wu.d | R (rm) | `fcvt.wu.d rd, rs1, rm` | convert to an unsigned 32-bit integer |
| fcvt.d.w | R (rm) | `fcvt.d.w rd, rs1, rm` | convert the signed 32-bit integer rs1 to a double |
| fcvt.d.wu | R (rm) | `fcvt.d.wu rd, rs1, rm` | convert the unsigned 32-bit integer rs1 to a double |
| fcvt.l.d | R (rm) | `fcvt.l.d rd, rs1, rm` | RV64: convert rs1 to a signed 64-bit integer |
| fcvt.lu.d | R (rm) | `fcvt.lu.d rd, rs1, rm` | RV64: convert to an unsigned 64-bit integer |
| fcvt.d.l | R (rm) | `fcvt.d.l rd, rs1, rm` | RV64: convert the signed 64-bit integer rs1 to a double |
| fcvt.d.lu | R (rm) | `fcvt.d.lu rd, rs1, rm` | RV64: convert the unsigned 64-bit integer rs1 to a double |
| fmv.x.d | R | `fmv.x.d rd, rs1` | RV64: copy the bits of the floating point register rs1 into the integer register rd |
| fmv.d.x | R | `fmv.d.x rd, rs1` | RV64: copy the bits of the integer register rs1 into the floating point register rd |

### Zicsr, Zifencei and system

| Instruction | Format | Syntax | Meaning |
|---|---|---|---|
| csrrw | CSR | `csrrw rd, csr, rs1` | write rs1 into the CSR and its old value into rd |
| csrrs | CSR | `csrrs rd, csr, rs1` | set in the CSR the bits that are set in rs1, old value into rd |
| csrrc | CSR | `csrrc rd, csr, rs1` | clear in the CSR the bits that are set in rs1, old value into rd |
| csrrwi | CSR (imm) | `csrrwi rd, csr, uimm` | write the 5-bit constant into the CSR, old value into rd |
| csrrsi | CSR (imm) | `csrrsi rd, csr, uimm` | set the bits of the constant in the CSR |
| csrrci | CSR (imm) | `csrrci rd, csr, uimm` | clear the bits of the constant in the CSR |
| fence.i | I | `fence.i` | make the written instructions visible to the instruction fetch |
| uret | I | `uret` | return from a user level trap handler |
| wfi | I | `wfi` | wait for an interrupt |

The control and status registers that can be named: `ustatus`, `uie`, `utvec`, `uscratch`, `uepc`,
`ucause`, `utval`, `uip`, `fflags`, `frm`, `fcsr`, `cycle`, `time`, `instret`, `cycleh`, `timeh`,
`instreth`. A CSR may also be written as a number or a constant expression.

## Pseudo-instructions

A pseudo-instruction stands for one or more basic instructions. When several forms of one mnemonic
exist, the first that fits the operands is used, so a small value costs one instruction and a large
one costs more.

| Pseudo-instruction | Expands to | Meaning |
|---|---|---|
| `nop` | `addi x0, x0, 0` | do nothing |
| `mv rd, rs` | `addi rd, rs, 0` | copy a register |
| `not rd, rs` | `xori rd, rs, -1` | invert every bit |
| `neg rd, rs` | `sub rd, x0, rs` | negate |
| `negw rd, rs` | `subw rd, x0, rs` | RV64: negate in 32 bits |
| `seqz rd, rs` | `sltiu rd, rs, 1` | 1 when rs is zero |
| `snez rd, rs` | `sltu rd, x0, rs` | 1 when rs is not zero |
| `sltz rd, rs` | `slt rd, rs, x0` | 1 when rs is negative |
| `sgtz rd, rs` | `slt rd, x0, rs` | 1 when rs is positive |
| `sgt rd, rs, rt` | `slt rd, rt, rs` | 1 when rs is greater than rt, signed |
| `sgtu rd, rs, rt` | `sltu rd, rt, rs` | the same, unsigned |
| `sext.b rd, rs` | two shifts | sign extend the low byte |
| `sext.h rd, rs` | two shifts | sign extend the low halfword |
| `sext.w rd, rs` | `addiw rd, rs, 0` | RV64: sign extend the low word |
| `zext.b rd, rs` | `andi rd, rs, 255` | zero extend the low byte |
| `zext.h rd, rs` | two shifts | zero extend the low halfword |
| `zext.w rd, rs` | two shifts | RV64: zero extend the low word |
| `li rd, value` | 1, 2 or 8 instructions | load a constant into a register |
| `la rd, symbol` | `auipc` + `addi` | load the address of a symbol |
| `lla rd, symbol` | `auipc` + `addi` | load the address of a symbol |
| `b offset` | `jal x0, offset` | jump |
| `j offset` | `jal x0, offset` | jump |
| `jal offset` | `jal x1, offset` | call, return address in `ra` |
| `jr rs` | `jalr x0, rs, 0` | jump to a register |
| `jr offset(rs)`, `jr rs, offset` | `jalr x0, rs, offset` | jump to a register plus an offset |
| `jalr rs` | `jalr x1, rs, 0` | call a register, return address in `ra` |
| `jalr rd, rs` | `jalr rd, rs, 0` | call a register, return address in rd |
| `jalr offset(rs)`, `jalr rs, offset` | `jalr x1, rs, offset` | call a register plus an offset |
| `jalr rd, offset(rs)` | `jalr rd, rs, offset` | the same with a chosen return register |
| `ret` | `jalr x0, x1, 0` | return from a subroutine |
| `call symbol` | `auipc x6` + `jalr x1` | call a subroutine at any distance |
| `call rt, symbol` | `auipc rt` + `jalr x1` | the same, using rt to hold the address |
| `tail symbol` | `auipc x6` + `jalr x0` | jump to a subroutine without a return address |
| `jump symbol, rt` | `auipc rt` + `jalr x0` | jump to any distance, using rt |
| `beqz rs, offset` | `beq rs, x0, offset` | branch when rs is zero |
| `bnez rs, offset` | `bne rs, x0, offset` | branch when rs is not zero |
| `bgez rs, offset` | `bge rs, x0, offset` | branch when rs is not negative |
| `bltz rs, offset` | `blt rs, x0, offset` | branch when rs is negative |
| `bgtz rs, offset` | `blt x0, rs, offset` | branch when rs is positive |
| `blez rs, offset` | `bge x0, rs, offset` | branch when rs is not positive |
| `bgt rs, rt, offset` | `blt rt, rs, offset` | branch when rs is greater than rt, signed |
| `ble rs, rt, offset` | `bge rt, rs, offset` | branch when rs is not greater than rt, signed |
| `bgtu rs, rt, offset` | `bltu rt, rs, offset` | the same, unsigned |
| `bleu rs, rt, offset` | `bgeu rt, rs, offset` | the same, unsigned |
| `l{b,bu,h,hu,w,wu,d} rd, address` | 1 or 2 instructions | load from an address written as a number or a symbol |
| `s{b,h,w,d} rs, address[, rt]` | 1 or 2 instructions | store at an address; a far address needs the temporary register rt |
| `f{lw,ld} fd, address[, rt]` | 1 or 2 instructions | floating point load from an address |
| `f{sw,sd} fs, address[, rt]` | 1 or 2 instructions | floating point store at an address |
| `fmv.{s,d} fd, fs` | `fsgnj` | copy a floating point register |
| `fabs.{s,d} fd, fs` | `fsgnjx` | absolute value |
| `fneg.{s,d} fd, fs` | `fsgnjn` | negate |
| `fgt.{s,d} rd, fs, ft` | `flt` with swapped operands | 1 when fs is greater than ft |
| `fge.{s,d} rd, fs, ft` | `fle` with swapped operands | 1 when fs is not less than ft |
| `csrr rd, csr` | `csrrs rd, csr, x0` | read a CSR |
| `csrw csr, rs` | `csrrw x0, csr, rs` | write a CSR |
| `csrs csr, rs` | `csrrs x0, csr, rs` | set bits in a CSR |
| `csrc csr, rs` | `csrrc x0, csr, rs` | clear bits in a CSR |
| `csrwi csr, uimm` | `csrrwi x0, csr, uimm` | write a constant into a CSR |
| `csrsi csr, uimm` | `csrrsi x0, csr, uimm` | set the bits of a constant |
| `csrci csr, uimm` | `csrrci x0, csr, uimm` | clear the bits of a constant |
| `frcsr rd`, `frsr rd` | `csrrs rd, fcsr, x0` | read the floating point control and status register |
| `fscsr rd, rs`, `fssr rd, rs` | `csrrw rd, fcsr, rs` | write it and keep the old value |
| `fscsr rs`, `fssr rs` | `csrrw x0, fcsr, rs` | write it |
| `frrm rd` | `csrrs rd, frm, x0` | read the rounding mode |
| `fsrm rd, rs`, `fsrm rs` | `csrrw` on `frm` | write the rounding mode |
| `frflags rd` | `csrrs rd, fflags, x0` | read the exception flags |
| `fsflags rd, rs`, `fsflags rs` | `csrrw` on `fflags` | write the exception flags |
| `rdcycle rd`, `rdcycleh rd` | `csrrs` on `cycle`, `cycleh` | read the cycle counter |
| `rdtime rd`, `rdtimeh rd` | `csrrs` on `time`, `timeh` | read the clock |
| `rdinstret rd`, `rdinstreth rd` | `csrrs` on `instret`, `instreth` | read the counter of retired instructions |
| `fence` | `fence iorw, iorw` | order every memory access |
| `pause` | `fence w, 0` | hint that the program is spinning |

`li` chooses its form by the value: one instruction for −2048…2047; two (`lui` and `addi`) in RV32
for −2³¹…2³²−1 and (`lui` and `addiw`) in RV64 for −2³¹…2³¹−1; eight instructions in RV64 for any
other 64-bit value, building it from parts of 32, 11, 11 and 10 bits. A value that is not known
while the addresses are being assigned reserves the longest form of its mnemonic.

## Source syntax

### Statements

A line holds any number of labels, then at most one statement, then an optional comment:

```asm
loop: count: addi t0, t0, -1    # a comment runs to the end of the line
```

A statement is an instruction, a pseudo-instruction, a directive or a macro call. Its operands are
separated by commas; blanks inside an operand are free, so `lw t0, 4 * N(sp)` is one operand
`4 * N` and the base register `sp`. Upper and lower case do not matter in a mnemonic or a directive
name; they do matter in a symbol name.

### Labels

A named label is `name:` and may be written on its own line. A label of a data directive gets the
address of the value that follows it, after alignment.

A numeric label is a number followed by a colon and may be repeated. A reference `1b` means the
nearest definition of `1:` before the reference, `1f` the nearest after it:

```asm
1:      addi t0, t0, -1
        bnez t0, 1b
        j 2f
        nop
2:      ret
```

A name consists of letters, digits, `_`, `.` and `$`, and does not start with a digit. Register and
CSR names are recognized first, so a label cannot be called `t0` or `fcsr`.

### Registers

Integer registers are `x0`…`x31` or their names of the calling convention: `zero`, `ra`, `sp`,
`gp`, `tp`, `t0`…`t6`, `s0`…`s11`, `a0`…`a7`; `fp` is another name of `s0`. Floating point
registers are `f0`…`f31` or `ft0`…`ft11`, `fs0`…`fs11`, `fa0`…`fa7`. Only these exact names are
accepted.

### Literals

| Kind | Examples |
|---|---|
| Decimal | `42`, `-7` |
| Octal, leading zero | `0755` |
| Hexadecimal | `0x1F`, `0XdeadBEEF` |
| Character | `'a'`, `'\n'`, `'\0'`, `'\101'` |
| Floating point | `1.5`, `-2.5e3`, `0x1p-2`, `Inf`, `NaN` |
| String | `"text\n"` |

Escapes in a character or a string are `\'`, `\"`, `\\`, `\n`, `\t`, `\b`, `\r`, `\f`, `\0` and an
octal `\ooo` up to 255. An unknown escape keeps its character. An integer literal has no width of
its own: the value is exact and its range is checked where it is used.

### Expressions

Wherever a number or an address is expected, an expression may be written: literals, symbols,
numeric label references and parentheses, with the operators of GNU `as`.

Prefix operators: `-` negation, `~` bitwise not, `!` logical not (`!0` is 1, anything else gives
0), `+` nothing. A `+` or `-` is a prefix operator at the start of an operand and a binary operator
between two of them.

Binary operators, from the lowest precedence to the highest; equal precedence is evaluated left to
right:

| Precedence | Operators | Meaning |
|---|---|---|
| 1 | `\|\|` | logical or, gives 1 or 0 |
| 2 | `&&` | logical and, gives 1 or 0 |
| 3 | `+` `-` `==` `<>` `!=` `<` `>` `>=` `<=` | addition, subtraction, signed comparisons; a true comparison gives −1 |
| 4 | `\|` `&` `^` `!` | bitwise or, and, exclusive or; `a ! b` is `a \| ~b` |
| 5 | `*` `/` `%` `<<` `>>` | multiplication; division and remainder truncate towards zero; shifts |

A value is either a number or an address in a segment. An address may only be added to a number,
have a number subtracted from it, or have an address of the same segment subtracted from it, which
gives a number; anything else on an address is an error.

Two functions build the parts of an address for the instructions that need them:

```asm
lui  t0, %hi(msg)       # upper 20 bits, corrected for the sign of the lower part
addi t0, t0, %lo(msg)   # lower 12 bits, signed
```

### Directives

#### Segments and sections

| Directive | Meaning |
|---|---|
| `.text [address]` | the following statements go into the text segment, optionally at a chosen address |
| `.data [address]` | the following values go into the data area |
| `.rodata`, `.bss`, `.sdata` | continue the data area under another section name |
| `.section {.text,.data,.rodata,.bss}` | the same as the directive of that name; the name may be quoted |

`.data`, `.rodata` and `.bss` share one area, each section continuing where the previous one
stopped. Instructions belong to the text segment and values to the data area; the other way round
is an error.

#### Values

| Directive | Meaning |
|---|---|
| `.byte v, …` | 8-bit values |
| `.half`, `.short`, `.2byte` | 16-bit values |
| `.word`, `.long`, `.4byte` | 32-bit values |
| `.dword`, `.quad`, `.8byte` | 64-bit values |
| `.float v, …` | 32-bit floating point values |
| `.double v, …` | 64-bit floating point values |
| `.ascii "s", …` | the characters of a string |
| `.asciz "s"`, `.string "s"` | the characters and a zero byte |
| `.space n`, `.zero n` | n bytes of zero |
| `.sleb128 v`, `.uleb128 v` | a value in the variable length encoding of DWARF |

A value may be any expression, including the address of a label defined further down. A value that
does not fit its directive is truncated and reported as a warning. Every value is aligned to its
own size: one byte needs no alignment, 16-bit values are aligned to 2, 32-bit values and `.float`
to 4, 64-bit values and `.double` to 8. A label written in front of a value gets the address after
that alignment.

#### Alignment

| Directive | Meaning |
|---|---|
| `.align n` | align to 2ⁿ; `.align 0` switches automatic alignment off until the next section directive |
| `.p2align p2[, pad[, max]]` | align to 2^p2, filling with pad; do nothing when more than max bytes would be needed |
| `.balign b[, pad]` | align to a multiple of b bytes, filling with pad |

#### Symbols

| Directive | Meaning |
|---|---|
| `.globl name, …`, `.global name, …` | make the symbols visible to the other files of the program |
| `.local name, …` | keep the symbols in their own file |
| `.extern name, size` | declare a symbol of the given size in the extern area |
| `.comm name, size[, align]`, `.common …` | reserve size bytes in the data area and make the symbol global |
| `.equ name, value` | define a constant; it may be redefined, and its value must be known at that point |
| `.eqv name, text` | define a text substitution, applied to the following lines |

A program may be assembled from several files. Each file keeps its own symbols; `.globl`, `.extern`
and `.comm` put a name into the table shared by the files. A name declared global in two files is
an error, as is a name that no file defines.

#### Source and macros

| Directive | Meaning |
|---|---|
| `.include "file"` | read the file in place of the directive; the path is relative to the including file |
| `.macro name params` … `.end_macro`, `.endm` | define a macro |

#### Other

| Directive | Meaning |
|---|---|
| `.insn value` | write one instruction word |
| `.insn length, value` | the same, with the length in bytes checked; only 4 is accepted |
| `.insn type fields` | write an instruction word from the fields of a format |
| `.option {rvc,norvc,arch,pic,nopic,relax,norelax,push,pop}` | an option of the assembly |

`.option rvc`, `.option pic` and `.option arch` with an extension that is not supported are errors;
the other options have no effect on the program and are reported as warnings. `.option push` and
`.option pop` keep a stack of the options.

`.insn` with a type writes the fields of a format from the least significant bits to the most
significant ones, grouped as opcode, function fields, registers, immediates:

```asm
.insn r  0x33, 0, 0, t0, t1, t2   # add t0, t1, t2
.insn r  opcode, func3, func2, rd, rs1, rs2, rs3
.insn i  0x13, 0, t0, t1, 5       # addi t0, t1, 5
.insn i  0x03, 2, t0, -4(t1)      # lw t0, -4(t1)
.insn s  0x23, 2, t2, 8(t1)       # sw t2, 8(t1)
.insn sb opcode, func3, rs1, rs2, symbol
.insn u  0x37, t0, 0x12345        # lui t0, 0x12345
.insn uj opcode, rd, symbol
```

`b` is another name of the type `sb` and `j` of `uj`.

### Macros

A macro is defined once and expanded at every call. Parameters are written `%name` or `\name` and
are replaced by the text of the arguments; parameters and arguments are separated by commas.

```asm
.macro print_int %value
        li a7, 1
        add a0, x0, %value
        ecall
.end_macro

        print_int t0
```

Macros of one name are told apart by the number of parameters, and the last definition of a name
and count wins. A macro must be defined before it is called, and it is visible in the file that
defines it, including the files that file includes.

A label defined in a body gets the suffix `_M<number>` of the expansion, so every expansion has its
own labels:

```asm
.macro wait %count
        add t0, x0, %count
spin:   addi t0, t0, -1
        bnez t0, spin       # becomes spin_M0, spin_M1, … in the expansions
.end_macro
```

The body of a macro is read like source text at the call, so the `.eqv` symbols and the `.include`
files known at that point apply to it. A macro that calls itself, directly or through another
macro, is reported as an expansion loop.

### Memory layout

| Area | Default | CompactDataAtZero | CompactTextAtZero |
|---|---|---|---|
| text | 0x00400000 | 0x00003000 | 0x00000000 |
| extern | 0x10000000 | 0x00001000 | 0x00001000 |
| data | 0x10010000 | 0x00000000 | 0x00002000 |
| heap | 0x10040000 | 0x00002000 | 0x00003000 |
| stack pointer | 0x7FFFEFFC | 0x00002FFC | 0x00003FFC |

Files of one program follow each other: the text of the second file starts where the text of the
first one ends, and the same holds for the data. The entry point is the base of the text segment,
or the address of `main` when the program is assembled with `--start-at-main`.

### Diagnostics

A message names its kind, its file, its line and its column:

```
Error in program.s line 12 column 8: "missing": operand is of incorrect type
Warning in program.s line 4 column 7: value 0x0000012c is out-of-range and truncated to 0x0000002c
```

A line that came from a macro shows the call as well: `line 9->2` is line 2 of a body expanded from
line 9. Messages are sorted by their place in the source. A warning does not stop the assembly
unless `--warnings-are-errors` is given.

## References

- RISC-V Instruction Set Manual, ratified build v20260120 — <https://docs.riscv.org/reference/isa/v20260120>
- RISC-V Assembly Programmer's Manual — <https://github.com/riscv-non-isa/riscv-asm-manual>
- GNU `as` manual, "Expressions", "Infix Ops", "Prefix Ops", "Macro" — <https://sourceware.org/binutils/docs/as/>
- GNU `as` manual, "RISC-V-Formats" (the types of `.insn`) — <https://sourceware.org/binutils/docs/as/RISC_002dV_002dFormats.html>
- RARS, the assembler and simulator this dialect follows — <https://github.com/TheThirdOne/rars>
