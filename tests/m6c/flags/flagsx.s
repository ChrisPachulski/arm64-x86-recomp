// NZCV across calls, returns and tail calls between direct-called functions (no address taken, nothing exported but
// the _fx_* drivers, so gdyld can place per-site stores). Each driver has its own helpers. Every helper is a legal
// AArch64 function; each driver returns what native code returns by construction: 1 when x0 == x1, else 0.
    .section __TEXT,__text,regular,pure_instructions
    .globl _fx_ret_direct, _fx_ret_nested, _fx_ret_tail, _fx_entry_direct, _fx_entry_thunk, _fx_entry_call
    .private_extern _fu_cmp1, _fu_cmp2, _fu_cmp3, _ft_wrap, _ft_tailcmp
    .private_extern _fu_read1, _fu_read2, _fu_read3, _ft_thunk, _ft_call
    .p2align 2
_fu_cmp1:                               // sets NZCV from x0 - x1 and returns it
    cmp x0, x1
    ret
_fu_cmp2:
    cmp x0, x1
    ret
_fu_cmp3:
    cmp x0, x1
    ret
_ft_wrap:                               // non-leaf: returns the flags _fu_cmp2 left
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _fu_cmp2
    ldp x29, x30, [sp], #16
    ret
_ft_tailcmp:                            // tail-calls _fu_cmp3
    b _fu_cmp3
_fu_read1:                              // reads NZCV at entry
    cset w0, eq
    ret
_fu_read2:
    cset w0, eq
    ret
_fu_read3:
    cset w0, eq
    ret
_ft_thunk:                              // tail-calls an entry reader
    b _fu_read2
_ft_call:                               // non-leaf: calls an entry reader with the caller's flags
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _fu_read3
    ldp x29, x30, [sp], #16
    ret

_fx_ret_direct:                         // flags returned by a leaf
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _fu_cmp1
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret
_fx_ret_nested:                         // flags returned through a non-leaf that does not touch them
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _ft_wrap
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret
_fx_ret_tail:                           // flags returned through a tail call
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    bl _ft_tailcmp
    cset w0, eq
    ldp x29, x30, [sp], #16
    ret
_fx_entry_direct:                       // flags read at a direct callee's entry
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl _fu_read1
    ldp x29, x30, [sp], #16
    ret
_fx_entry_thunk:                        // flags read at entry behind a tail-calling thunk
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl _ft_thunk
    ldp x29, x30, [sp], #16
    ret
_fx_entry_call:                         // flags read at entry behind a non-leaf that does not touch them
    stp x29, x30, [sp, #-16]!
    mov x29, sp
    cmp x0, x1
    bl _ft_call
    ldp x29, x30, [sp], #16
    ret
