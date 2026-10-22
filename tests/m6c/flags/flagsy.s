// NZCV across an indirect call, a pointer-called entry reader and an extra entry point (a direct branch into another
// function's interior that reads the flags). gdyld must store NZCV everywhere here. Drivers return 1 when x0 == x1.
    .section __TEXT,__text,regular,pure_instructions
    .globl _fy_icall_ret, _fy_icall_entry, _fy_interior, _fy_host
    .private_extern _fy_cmp, _fy_read, _fy_a
    .p2align 2
_fy_cmp:
    cmp x0, x1
    ret
_fy_read:
    cset w0, eq
    ret
_fy_a:                                  // fy_a(x) = 2x + 1; Lfy_mid is not a symbol: an interior entry
    lsl x0, x0, #1
    add x0, x0, #1
    ret
Lfy_mid:
    cset w0, eq
    ret

_fy_icall_ret:                          // flags returned through blr
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    adr x9, _fy_cmp
    blr x9
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret
_fy_icall_entry:                        // flags read at the entry of a blr callee
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    adr x9, _fy_read
    cmp x0, x1
    blr x9
    ldp x29, x30, [sp], #16
    ret
_fy_interior:                           // flags read at an extra entry point, reached by a direct tail branch
    cmp x0, x1
    b Lfy_mid
_fy_host:                               // flags live across a host call (abs): native keeps them only by luck, so
    stp x29, x30, [sp, #-16]!           // this driver re-sets them after the call (no NZCV crosses it)
    mov x29, sp
    stp x0, x1, [sp, #-16]!
    bl _labs
    ldp x0, x1, [sp], #16
    cmp x0, x1
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret
