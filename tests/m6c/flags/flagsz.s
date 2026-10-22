// NZCV into extra entry points and behind an undecoded br, with no indirect call anywhere, so gdyld places every store
// (no 'everywhere'). Drivers return 1 when x0 == x1, else 0, on arm64 by construction.
    .section __TEXT,__text,regular,pure_instructions
    .globl _fz_interior_b, _fz_interior_bl, _fz_brlocal, _fz_interior_cond
    .private_extern _fz_a, _fz_c
    .p2align 2
_fz_a:                                  // fz_a(x) = 2x + 1; Lfz_mid and Lfz_mid2 are not symbols: interior entries
    lsl x0, x0, #1
    add x0, x0, #1
    ret
Lfz_mid:                                // reads NZCV at an extra entry point (direct b from fz_interior_b)
    cset w0, eq
    ret
Lfz_mid2:                               // reads NZCV at an extra entry point reached by bl (fz_interior_bl)
    cset w0, eq
    ret
_fz_c:                                  // fz_c(x) = x - 1; Lfz_mid3: an extra entry reached by a conditional branch
    sub x0, x0, #1
    ret
Lfz_mid3:
    csinc w0, wzr, wzr, ne              // 1 when Z, else 0
    ret

_fz_interior_b:                         // flags read at an extra entry point, reached by a direct tail branch
    cmp x0, x1
    b Lfz_mid
_fz_interior_bl:                        // flags read at an extra entry point called with bl
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl Lfz_mid2
    ldp x29, x30, [sp], #16
    ret
_fz_interior_cond:                      // a b.cond into another function's interior, flags live across it
    cmp x0, x1
    b.eq Lfz_mid3
    mov x0, #0
    ret
_fz_brlocal:                            // flags set before an undecoded br, read at its target
    adrp x9, _fz_slot@PAGE
    ldr x9, [x9, _fz_slot@PAGEOFF]      // the target comes from writable data: the br stays undecoded
    cmp x0, x1
    br x9
Lfz_tgt:
    cset w0, eq
    ret

    .section __DATA,__data
    .p2align 3
_fz_slot:
    .quad Lfz_tgt
