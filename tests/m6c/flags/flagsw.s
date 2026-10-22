// NZCV carried into or out of another function through an undecoded br. The br targets come from
// writable data, so each br stays undecoded (every-word fallback). Drivers return 1 when x0 == x1 on arm64.
    .section __TEXT,__text,regular,pure_instructions
    .globl _fq_br_entry, _fq_br_callee, _fq_br_entry_far
    .private_extern _fq_e1, _fq_cmp, _fq_far
    .p2align 2

_fq_e1:                                 // reads its caller's NZCV behind an undecoded br (origin: its entry)
    adrp x9, _fq_slot1@PAGE
    ldr x9, [x9, _fq_slot1@PAGEOFF]
    br x9
Lfq_e1_t:
    cset w0, eq
    ret
_fq_br_entry:                           // flags set by the caller, read in the callee behind its undecoded br
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl _fq_e1
    ldp x29, x30, [sp], #16
    ret

_fq_cmp:                                // returns the NZCV of x0 - x1
    cmp x0, x1
    ret
_fq_br_callee:                          // a callee's returned flags, read behind an undecoded br
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _fq_cmp
    adrp x9, _fq_slot2@PAGE
    ldr x9, [x9, _fq_slot2@PAGEOFF]
    br x9
Lfq_bc_t:
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret

_fq_far:                                // as fq_e1 with 300 words of padding (more than 256 words: state kept in c->)
    adrp x9, _fq_slot3@PAGE
    ldr x9, [x9, _fq_slot3@PAGEOFF]
    br x9
    .rept 300
    add x3, x3, #1
    .endr
Lfq_far_t:
    cset w0, eq
    ret
_fq_br_entry_far:
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl _fq_far
    ldp x29, x30, [sp], #16
    ret

    .section __DATA,__data
    .p2align 3
_fq_slot1:
    .quad Lfq_e1_t
_fq_slot2:
    .quad Lfq_bc_t
_fq_slot3:
    .quad Lfq_far_t
