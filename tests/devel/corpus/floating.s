# Floating point values and operations.
.globl main
.data
one:    .float 1.0
half:   .float 0.5
pi:     .double 3.14159
array:  .float 1.5, -2.25, 0.125

.text
main:   flw ft0, one, t0
        flw ft1, half, t0
        fld ft2, pi, t0
        fadd.s ft3, ft0, ft1
        fsub.s ft4, ft0, ft1
        fmul.s ft5, ft0, ft1
        fdiv.s ft6, ft0, ft1
        fsqrt.s ft7, ft0
        fmin.s fs0, ft0, ft1
        fmax.s fs1, ft0, ft1
        fmadd.s fs2, ft0, ft1, ft3, rne
        fcvt.w.s a0, ft0, rtz
        fcvt.s.w ft8, a0, dyn
        feq.s a1, ft0, ft1
        flt.s a2, ft0, ft1
        fle.s a3, ft0, ft1
        fgt.s a4, ft0, ft1
        fabs.s ft9, ft4
        fneg.s ft10, ft4
        fmv.s ft11, ft0
        fclass.s a5, ft0
        fsgnj.s fs3, ft0, ft1
        li a7, 10
        ecall
