// Adversarial interior-entry bed, part B (after the filler: a later chunk than part A). Callers into part A's
// interiors from another chunk, a cross-chunk tail call, and an address-only reference (adrp + add, blr).
    .section __TEXT,__text,regular,pure_instructions
    .globl _xb1, _xb2, _xb3, _xb4, _xb5
    .p2align 2
_xb1:                                   // xb1(x) = Lk_mid(x) + 5
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl Lk_mid
    add x0, x0, #5
    ldp x29, x30, [sp], #16
    ret

_xb2:                                   // xb2(x) = x == 0 ? Lk_mid(0) = -3 (cbz) : 2x (b into fj's case 1)
    mov x1, x0
    cbz x0, Lk_mid
    b Lj_c1

_xb3:                                   // xb3(x) = fs(x): tail call to a function start in chunk 0
    b _fs

_xb4:                                   // xb4(x) = ka(x): the address of ka taken with adrp + add, called with blr
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    adrp x9, _ka@PAGE
    add x9, x9, _ka@PAGEOFF
    blr x9
    ldp x29, x30, [sp], #16
    ret

_xb5:                                   // xb5(x) = bit 1 clear ? Lr_mid(x) = x + 7 (cbz; tbz cannot reach 60 KB back) : -5
    and x9, x0, #2
    cbz x9, Lr_mid
    mov x0, #-5
    ret
