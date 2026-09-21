"""Assembler directive names; matched ignoring case.

Semantics are implemented by the assembler stages (skill D15).
"""

# Directives of the RARS dialect (RARS: assembler/Directives.java).
# .align is a power of two, as in the asm manual; .extern makes multi-file programs possible.
RARS_DIRECTIVES = frozenset({
    ".data", ".text", ".word", ".dword", ".ascii", ".asciz", ".string", ".byte",
    ".align", ".half", ".space", ".double", ".float", ".extern", ".globl", ".global",
    ".eqv", ".macro", ".end_macro", ".include", ".section",
})

# Directives of the RISC-V Assembly Programmer's Manual ("Assembler Directives")
# that affect code or data and are missing in RARS.
MANUAL_DIRECTIVES = frozenset({
    ".p2align", ".balign",                                        # alignment
    ".2byte", ".short", ".4byte", ".long", ".8byte", ".quad",     # integer data
    ".zero", ".sleb128", ".uleb128",                              # data
    ".equ",                                                       # constant symbol
    ".endm",                                                      # end of macro (GNU)
    ".rodata", ".bss",                                            # sections
    ".local", ".comm", ".common",                                 # symbols
    ".insn",                                                      # raw instruction
    ".option",                                                    # assembler options
})

DIRECTIVES = RARS_DIRECTIVES | MANUAL_DIRECTIVES
