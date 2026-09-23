# Values of every width, the shifts and the comparisons.
.globl main
.data
small:  .byte 7
half:   .half 1234
word:   .word 0x12345678
values: .word 1, -1, 2047, -2048
bytes:  .byte 1, 2, 3, 4
room:   .space 12

.text
main:   li t0, 1
        li t1, 2047
        li t2, -2048
        li t3, 100000
        li t4, 0x7FFFFFFF
        lw a0, word
        lb a1, small
        lh a2, half
        add a3, a0, a1
        sub a4, a0, a2
        mul a5, a3, a4
        div a6, a5, t0
        rem a7, a5, t1
        sll s0, a0, t0
        srl s1, a0, t0
        sra s2, a0, t0
        slli s3, a0, 31
        srai s4, a0, 5
        and s5, a0, a1
        or s6, a0, a1
        xor s7, a0, a1
        andi s8, a0, 255
        slt s9, a0, a1
        sltu s10, a0, a1
        slti s11, a0, 100
        seqz t5, a0
        snez t6, a0
        sgtz t0, a1
        ret
