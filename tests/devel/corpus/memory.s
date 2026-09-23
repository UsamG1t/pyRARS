# The data directives and the ways of addressing memory.
.globl main
.globl shared
.data
shared: .word 0xDEADBEEF
bytes:  .byte 1, 2, 3, 4, 5
string: .ascii "abc"
ended:  .asciz "z"
        .align 3
aligned: .word 1
gap:    .space 7
        .align 2
after:  .word 2
chars:  .byte 'a', 'b', '\n'

.text
main:   la t0, shared
        lw t1, 0(t0)
        lw t2, shared
        sw t2, shared, t3
        lb a0, bytes
        lbu a1, 1(t0)
        lh a2, 2(t0)
        lhu a3, 2(t0)
        sb a0, bytes, t4
        sh a2, 4(t0)
        lw a4, 8(t0)
        li t5, 0x10010000
        lw a5, 0(t5)
        ret
