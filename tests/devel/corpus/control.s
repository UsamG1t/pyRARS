# Branches, jumps and a subroutine call.
.globl main
.data
table:  .word 5, 3, 9, 1, 7
size:   .word 5
found:  .word 0

.text
main:   la s0, table
        lw s1, size
        li s2, 0
        lw s3, 0(s0)
search: bge s2, s1, finish
        slli t0, s2, 2
        add t0, s0, t0
        lw t1, 0(t0)
        ble t1, s3, next
        add s3, x0, t1
next:   addi s2, s2, 1
        j search
finish: sw s3, found, t2
        add a0, x0, s3
        jal ra, twice
        beqz a0, zero_case
        bnez a0, other
zero_case:
        li a1, 0
        j end
other:  li a1, 1
end:    li a7, 10
        ecall

twice:  add a0, a0, a0
        ret
