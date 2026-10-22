# Limits and loud stops

A problem shows up in one of three places: as a one-line error from `tools/translate.py`, on its last line as a build error or an unsupported-instruction count (exit status 1), or as a loud stop while the translated program runs.
A loud stop prints a `FATAL:` line on stderr and exits with status 70, unless an item below says otherwise.

## What the translator refuses

`tools/translate.py` prints these exceptions from `gdyld` as one line, `translate.py: <exception>: <message>`, and exits 1:

| Situation | Exception |
|---|---|
| The input is not a thin arm64 Mach-O (for example a universal file) | `ValueError: ...: not a thin arm64 Mach-O` |
| The executable has no `LC_MAIN` entry point | `ValueError: ... has no LC_MAIN` |
| A required dylib is not found | `FileNotFoundError: ...: required dylib ... not found` |
| A non-weak symbol is not exported by any image | `LookupError: ...: symbol ... (ordinal ...) not found` |
| The guest images grow into the fixed C++ runtime addresses | `MemoryError: guest images reach the fixed runtime bases at ...` |
| The host link finds a guest-host incompatibility | `LookupError: gdyld link: ...` |
| An image imports `libv8*` and the repository has no `v8/` directory | `LookupError: guest images import libv8*, and this tree has no V8 bridge generators (...)` |

Instructions with no lifter case do not stop the build.
`tools/translate.py` prints their count on its last line and exits 1, and the program they are in stops only if it reaches one (see [lifter.md](lifter.md)).

## Instructions

- **No lifter case** — `FATAL: unsupported instruction at 0x...` when the instruction runs.
- **SVE and SME** — an instruction with `z`, `p` or `za` registers, or an SVE-only operation, is lifted to a stop: `FATAL: SVE/SME instruction ... (this x86-64 host has no SVE/SME) at 0x...`. It does not count as unsupported, so it only matters if the program runs it.
- **EL1 ID registers** — an `mrs` of `midr_el1`, `mpidr_el1`, `revidr_el1` or an `id_*_el1` register stops with `FATAL: EL1 system register read ...`.
- **Half precision** — `fcmp`, `fcmpe`, `scvtf` and `ucvtf` on `h` registers have no lifter case, so they count as unsupported.
- **`udf`** — traps with `SIGILL`, as it does on arm64.
- **Data reached by control flow** — a word the disassembler cannot decode, if control flow reaches it, stops with `FATAL: unsupported instruction at 0x...`.

## Control transfers and host calls

- **Only the load graph is translated.** `dlopen` of an arm64 file that is not part of the translation returns `NULL`, and `dlerror()` returns `gdyld: <path> is an arm64 image that is not part of this translation (only the load graph is translated)`. `dlopen` of an x86-64 library works natively.
- **No code made at run time.** A branch to an address outside the translated images, the import slots and the known bridges stops with `FATAL: indirect branch to an unmapped target`.
- **Native code without a type.** A branch into host code that has no typed bridge stops with `FATAL: indirect branch to native code ... with no typed bridge`, naming the nearest host symbol. A call through a host code pointer whose type is unknown (a `dlsym` result with no known signature, or a `void (*)(void)`) stops with `FATAL: call through an untyped host code pointer ...`.
- **ucontext and vfork.** `makecontext`, `swapcontext`, `getcontext`, `setcontext` and `vfork` stop with `FATAL: unsupported control transfer ...`. The C++ exception entry points stop the same way, but only when no guest C++ runtime provides them.
- **Undeclared host functions.** Calling a host function that no SDK header declares and no Swift signature covers stops with `FATAL: call to a host import with no header prototype (no bridge)`.
- **Guest images stay loaded.** `dlclose` of a guest image returns 0 and unloads nothing.
- **Variadic functions without a bridge.** A variadic host function with no hand-written bridge, such as `CFStringCreateWithFormat`, stops with `FATAL: variadic import has no bridge: <name>` when called.
- **Callback pointer identity.** When the host stores a guest callback (for example the comparator passed to `fts_open`) and the guest reads the pointer back, it gets the bridge's address, not its own function. Calls through it work; comparing it with the original function does not.

## The UI guard

By default a translation is headless.
These stop before they run, with `FATAL: blocked window-server / AppKit-UI / GPU entry point (headless translation)`:

- imports from AppKit, Metal, MetalKit, MetalFX and the MetalPerformanceShaders frameworks, and from `libswiftAppKit`, `libswiftMetal`, `libswiftMetalKit` and `libswiftQuartzCore`;
- window-server, display, cursor and event-tap functions (`CGS*`, `SLS*`, `CGDisplay*`, `CGWindow*`, `CGEventPost` and similar), `CVDisplayLink*`, `NSApplication*` functions and `CFUserNotification*`;
- Objective-C messages to classes defined in those frameworks or derived from them, and to `CAMetalLayer`, `CADisplayLink` and `CAMetalDisplayLink`.

`tools/translate.py --ui-guard-off` gives those imports and messages their ordinary bridges.
The program then prints `gdyld: UI guard OFF (built with ui_guard=False): window, AppKit and GPU calls run` when it starts.
The library function documents this switch as a runner option for windowed and GPU tests.

## The output directory

- **It cannot move.** With `tools/translate.py`, `layout.hpp` records each `image<k>.bin` by its absolute path, and `translated` stops with `FATAL: cannot open guest image` if a file is gone.
- **Fixed addresses.** `translated` maps the guest images from `0x200000000`, the C++ runtime at `0x400000000` to `0x420000000`, and the import slots at `0x1F0000000`; if any of that address space is taken, it stops with `FATAL: guest region is not free at 0x...`.
- **CPU extensions.** The lifted code is compiled with `-mavx2 -mfma -mbmi -mbmi2 -mlzcnt -mpopcnt -mf16c -maes -mpclmul`.
- **Stacks.** The guest main thread gets an 8 MB stack, and `translated` is linked with a 512 MB main-thread stack.

## Extension points

These hook host libraries outside the SDK into a translation.

- **`sbt/extensions.txt`** (ignored by git, optional) lists Python module names, one per line, with `#` comments.
  `sbt/gdyld.py` imports each one; a module provides `LIB_RE`, `HEADER` and `prepare(names, keys, out_dir, sdk)`.
  For the host imports whose install name matches `LIB_RE`, `prepare()` returns their bridge-table entries, extra host compile flags and report lines, and `host.cpp` includes `HEADER`.
- **`v8/`** at the repository root is not part of this repository.
  When a program's host images include `libv8`, `libv8_libbase` or `libv8_libplatform`, `gdyld` runs the generator scripts `gen_v8_bridges.py`, `catalog_v8_entries.py` and `gen_v8_marshal.py` from it, and compiles `host.cpp` against its `fork/include` headers.
- **`host_extra`**, a parameter of `gdyld.translate()` that `tools/translate.py` does not expose, maps an install name to a C header and an x86-64 dylib for a host library outside the SDK.
