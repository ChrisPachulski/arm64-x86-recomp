# Adding an instruction to the lifter

This page is for contributors who want the lifter to handle an arm64 instruction that a translation reports as unsupported.

## Where an instruction goes

`recompile.lift()` turns one Capstone instruction into C statements and hands two instruction families to plug-in modules.
The routing key is the base mnemonic: the mnemonic up to its first dot.
An instruction goes to `lift_neon.lift_neon()` when its base mnemonic is in `lift_neon.MNEMONICS` and it has a vector operand, or it is one of the scalar forms that `lift_neon.scalar_form()` accepts.
It goes to `lift_scalar.lift_scalar()` when it has no vector operand and its base mnemonic is in `lift_scalar.MNEMONICS`.
Branches are lifted by `recompile.lift_function()` before `recompile.lift()` is called; every other instruction is handled, or refused, inside `recompile.lift()`.

`lift_neon.lift_neon()` calls the handler that `lift_neon.DISPATCH` lists for the mnemonic.
`lift_neon.MNEMONICS` is the set of `DISPATCH` keys, so a new vector instruction needs a `DISPATCH` entry and nothing else to be routed.
`lift_scalar.lift_scalar()` tries its families in a fixed order and raises `NotImplementedError("scalar:<mnemonic>")` for a mnemonic none of them takes.

## What happens when a case is missing

`recompile.lift_function()` catches `NotImplementedError` from the lifter, and `IndexError`, `KeyError`, `ValueError` or `TypeError` from an operand shape no case expects.
In both cases the instruction joins the function's unsupported list, and the C code calls `unsupported()` in its place.
If the translated program reaches that call, it stops with `FATAL: unsupported instruction at 0x...` and exit status 70.
`gdyld.translate()` collects every unsupported instruction of every image, and `tools/translate.py` exits 1 when there is any.
So raising `NotImplementedError` is how a helper declines a form it does not implement.

## The register and memory helpers

The helpers in `sbt/cgen.py` build the C text for register and memory operands.

`cgen.reg_parts()` maps a Capstone register name to `(kind, index, width)`.
`fp` and `lr` are `x29` and `x30`, `wsp` is `sp`, `wzr` is the zero register at width 32, and `wN` is register `N` of kind `x` at width 32.
Any other name raises `NotImplementedError`, so the instruction becomes unsupported.

`cgen.wr()` returns the C statement that writes an integer register.
A write to the zero register evaluates the value and discards it, and a 32-bit write zeroes the upper half.
A write to `sp` is followed by a `GD_SPW;` marker, which `recompile.localize` turns into a store of `sp` to the CPU struct before a signal fence.
Only `cgen.publish()` emits that marker, and `wr()` and `mem_addr()` call it, so an `sp` update written by hand gets no marker.

`cgen.mem_addr()` returns three strings for a memory operand: the address expression, a statement to run before the access, and one to run after it.
A register index is zero- or sign-extended according to its extend (`UXTB` to `SXTX`) and shifted before it is added to the base.
A post-indexed or pre-indexed form updates the base in the after-statement.
The exception is a pre-indexed form that lowers `sp`: it lowers `sp` in the before-statement, so a signal frame cannot land on the new slot.
An operand that is not a memory operand raises `NotImplementedError`.

## Test the new case

`sbt/microtest.py` assembles each case with clang, lifts it with `recompile.lift_function()`, compiles the C for x86-64 with the translator's chunk flags, and runs it.
It runs the same arm64 bytes in the Unicorn emulator and compares the two final states.
A case is a dict with `name` and `asm`, optional `regs`, `vregs` and `mem` inputs, and `flags` or `v` to also compare NZCV or the 32 vector registers.
`x0` to `x30` and `sp` are always compared, and `x30` is preset so the snippet's closing `ret` returns on both sides.
An unsupported instruction in a case raises `RuntimeError` instead of producing a result.

Cases live in a `CASES` list in a module in `sbt/`; pass the module names on the command line:

```sh
sbtenv/bin/python sbt/microtest.py cases_scalar cases_neon
```

The run ends with an assertion that every case passed.
`tools/run_beds.py` runs the existing case modules as its `microtest_*` beds.

New cases can go into an existing case module or a new one; a new module runs with the suite once a `microtest_*` bed in `tools/run_beds.py` names it.
