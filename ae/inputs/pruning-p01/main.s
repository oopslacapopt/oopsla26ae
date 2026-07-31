	.text
	.file	"input.ll"
                                        // Start of file scope inline assembly
.symver __qsort_r_compat, qsort_r@FBSD_1.0

                                        // End of file scope inline assembly
	.globl	main                            // -- Begin function main
	.p2align	4
	.type	main,@function
main:                                   // @main
.Lfunc_begin0:
	.cfi_startproc
// %bb.0:                               // %entry
	sub	csp, csp, #80
	.cfi_def_cfa csp, -80
	stp	c29, c30, [csp, #48]            // 32-byte Folded Spill
	add	c29, csp, #48
	.cfi_def_cfa c29, 32
	.cfi_offset c30, -16
	.cfi_offset c29, -32
	stur	wzr, [c29, #-4]
	stur	w0, [c29, #-8]
	str	c1, [csp, #16]
	ldur	w8, [c29, #-8]
	subs	w8, w8, #2
	b.lt	.LBB0_2
	b	.LBB0_1
.LBB0_1:                                // %cond.true
	ldr	c0, [csp, #16]
	ldr	c0, [c0, #16]
	mov	x9, xzr
	bl	atoi
	b	.LBB0_3
.LBB0_2:                                // %cond.false
	mov	w0, #1024                       // =0x400
	b	.LBB0_3
.LBB0_3:                                // %cond.end
	str	w0, [csp, #12]
	ldur	w8, [c29, #-8]
	subs	w8, w8, #3
	b.lt	.LBB0_5
	b	.LBB0_4
.LBB0_4:                                // %cond.true2
	ldr	c0, [csp, #16]
	ldr	c0, [c0, #32]
	mov	x9, xzr
	bl	atoi
	b	.LBB0_6
.LBB0_5:                                // %cond.false5
	mov	w0, wzr
	b	.LBB0_6
.LBB0_6:                                // %cond.end6
	str	w0, [csp, #8]
	ldr	w0, [csp, #8]
	mov	x9, xzr
	bl	srand
	str	wzr, [csp, #4]
	b	.LBB0_7
.LBB0_7:                                // %for.cond
                                        // =>This Inner Loop Header: Depth=1
	ldr	w8, [csp, #4]
	ldr	w9, [csp, #12]
	subs	w8, w8, w9
	b.ge	.LBB0_10
	b	.LBB0_8
.LBB0_8:                                // %for.body
                                        //   in Loop: Header=BB0_7 Depth=1
	mov	x9, xzr
	bl	rand
	mov	x9, xzr
	bl	_Z3p01i
	b	.LBB0_9
.LBB0_9:                                // %for.inc
                                        //   in Loop: Header=BB0_7 Depth=1
	ldr	w8, [csp, #4]
	add	w8, w8, #1
	str	w8, [csp, #4]
	b	.LBB0_7
.LBB0_10:                               // %for.end
	mov	w0, wzr
	.cfi_def_cfa csp, 80
	ldp	c29, c30, [csp, #48]            // 32-byte Folded Reload
	add	csp, csp, #80
	.cfi_def_cfa csp, 0
	.cfi_restore c30
	.cfi_restore c29
	ret	c30
.Lfunc_end0:
	.size	main, .Lfunc_end0-.Lfunc_begin0
	.cfi_endproc
                                        // -- End function
	.section	".note.GNU-stack","",@progbits
	.addrsig