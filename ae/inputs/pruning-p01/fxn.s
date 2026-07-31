	.text
	.file	"fxn.default.ll"
	.globl	_Z3p01i                         // -- Begin function _Z3p01i
	.p2align	4
	.type	_Z3p01i,@function
_Z3p01i:                                // @_Z3p01i
.Lfunc_begin0:
	.cfi_startproc
// %bb.0:                               // %entry
	sub	csp, csp, #16
	.cfi_def_cfa_offset 16
	str	w0, [csp, #12]
	ldr	w8, [csp, #12]
	subs	w8, w8, #1
	str	w8, [csp, #8]
	ldr	w8, [csp, #12]
	ldr	w9, [csp, #8]
	and	w0, w8, w9
	add	csp, csp, #16
	.cfi_def_cfa csp, 0
	ret	c30
.Lfunc_end0:
	.size	_Z3p01i, .Lfunc_end0-.Lfunc_begin0
	.cfi_endproc
                                        // -- End function
	.section	".note.GNU-stack","",@progbits
	.addrsig
