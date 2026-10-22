// Adversarial interior-entry bed, part A (first in __text: chunk 0). run_ix.py concatenates ix_a.s + generated filler +
// ix_b.s into one file so the L labels (interior targets: not symbols, not LC_FUNCTION_STARTS entries) are visible to
// the callers in ix_b.s, which land in a later chunk. Semantics are restated in C in ix_main.c (x86_64 oracle).
    .section __TEXT,__text,regular,pure_instructions
    .globl _ka, _kb, _kc, _fj, _fjx, _fjy, _fr, _fq, _fs, _ft, _lj
    .p2align 2
_ka:                                    // ka(x) = x + 1
    add x0, x0, #1
    ret
Lk_mid:                                 // interior of ka: 7x - 3 (callers: kb bl, kc b.ne, xb1 bl, xb2 cbz)
    mov x9, #7
    mul x0, x0, x9
    sub x0, x0, #3
    ret

_kb:                                    // kb(x) = Lk_mid(x) + 1000
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl Lk_mid
    add x0, x0, #1000
    ldp x29, x30, [sp], #16
    ret

_kc:                                    // kc(x) = x != 5 ? Lk_mid(x) : 55
    cmp x0, #5
    b.ne Lk_mid
    mov x0, #55
    ret

_fj:                                    // fj(x, y): x 0..3 -> y + 10, 2y, y*y, y - 1 (jump table); else -1
    cmp x0, #3
    b.hi Lj_def
    adrp x8, lJT_fj@PAGE
    add x8, x8, lJT_fj@PAGEOFF
    adr x9, Lj_c0
    ldrb w10, [x8, x0]
    add x9, x9, x10, lsl #2
    br x9
Lj_c0:
    add x0, x1, #10
    ret
Lj_c1:                                  // jump-table target and interior target of xb2
    lsl x0, x1, #1
    ret
Lj_c2:                                  // jump-table target and interior target of fjx
    mul x0, x1, x1
    ret
Lj_c3:                                  // jump-table target and interior target of fjy
    sub x0, x1, #1
    ret
Lj_def:
    mov x0, #-1
    ret

_fjx:                                   // fjx(y) = y * y: b into fj's case 2
    mov x1, x0
    b Lj_c2

_fjy:                                   // fjy(y) = y < 0 ? y - 1 (b.lt into fj's case 3) : 77
    mov x1, x0
    cmp x0, #0
    b.lt Lj_c3
    mov x0, #77
    ret

_fr:                                    // fr(x) = x + 2: setjmp, then longjmp(1) back to the resume point Lr_rs1
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    str x19, [sp, #16]
    mov x19, x0
    adrp x0, _ix_jb@PAGE
    add x0, x0, _ix_jb@PAGEOFF
    bl _setjmp
Lr_rs1:                                 // resume point of fr, and the interior target of fq (arrives with w0 = 9)
    cbnz w0, Lr_back
    adrp x0, _ix_jb@PAGE
    add x0, x0, _ix_jb@PAGEOFF
    mov w1, #1
    bl _longjmp
Lr_back:
    add x0, x19, w0, sxtw
    add x0, x0, #1
    ldr x19, [sp, #16]
    ldp x29, x30, [sp], #32
    ret
Lr_mid:                                 // interior of fr (from fs bl, ft tbnz, xb5 tbz): x + 7, longjmp(7) thrown by lj
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    str x19, [sp, #16]
    mov x19, x0
    adrp x0, _ix_jb2@PAGE
    add x0, x0, _ix_jb2@PAGEOFF
    bl _setjmp
    cbnz w0, Lr_mback
    mov w0, #7
    bl _lj
Lr_mback:
    add x0, x19, w0, sxtw
    ldr x19, [sp, #16]
    ldp x29, x30, [sp], #32
    ret

_fq:                                    // fq(x) = x + 10: fr's frame, w0 = 9, b to fr's resume point
    stp x29, x30, [sp, #-32]!
    mov x29, sp
    str x19, [sp, #16]
    mov x19, x0
    mov w0, #9
    b Lr_rs1

_fs:                                    // fs(x) = 2 * Lr_mid(x)
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl Lr_mid
    lsl x0, x0, #1
    ldp x29, x30, [sp], #16
    ret

_ft:                                    // ft(x) = x odd ? Lr_mid(x) : x
    tbnz x0, #0, Lr_mid
    ret

_lj:                                    // lj(v): longjmp(ix_jb2, v), never returns
    mov w1, w0
    adrp x0, _ix_jb2@PAGE
    add x0, x0, _ix_jb2@PAGEOFF
    bl _longjmp

    .section __TEXT,__const
lJT_fj:                                 // clang's compressed jump table: (target - Lj_c0) / 4 per case
    .byte (Lj_c0-Lj_c0)>>2
    .byte (Lj_c1-Lj_c0)>>2
    .byte (Lj_c2-Lj_c0)>>2
    .byte (Lj_c3-Lj_c0)>>2
