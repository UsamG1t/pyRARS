# Counting the characters of a string and printing the result.
.globl main
.data
prompt: .asciz "length: "
text:   .asciz "assembler"
buffer: .space 16
count:  .word 0

.text
.macro print_string %address
        li a7, 4
        la a0, %address
        ecall
.end_macro

.macro print_int %register
        li a7, 1
        add a0, x0, %register
        ecall
.end_macro

main:   print_string prompt
        la t0, text
        li t1, 0
loop:   lb t2, 0(t0)
        beqz t2, done
        addi t1, t1, 1
        addi t0, t0, 1
        j loop
done:   sw t1, count, t3
        print_int t1
        li a7, 10
        ecall
