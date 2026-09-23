# Control and status registers, and the system instructions.
.globl main
.text
main:   csrr t0, fcsr
        csrr t1, cycle
        csrr t2, time
        csrrs t3, fcsr, x0
        csrrw t4, frm, t0
        csrrwi t5, fflags, 3
        csrrsi t6, fflags, 1
        csrrci a0, fflags, 2
        frcsr a1
        frrm a2
        frflags a3
        rdcycle a4
        rdtime a5
        rdinstret a6
        fence 15, 15
        fence.i
        ebreak
        li a7, 10
        ecall
