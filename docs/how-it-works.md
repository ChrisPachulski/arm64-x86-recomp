# How a translation works

`tools/translate.py <arm64 executable> <out dir>` calls `translate()` in `sbt/gdyld.py`, which runs the steps below in order.
The generated sources, the objects and `translated` go into the output directory; the Swift signature database and the object cache live under `sbt/`.

## 1. Load the image graph

`load_images()` reads the executable, then its dylib dependencies in dyld's load order: each image's direct dependencies, then a depth-first walk.
Each file must be a thin arm64 Mach-O; anything else raises `ValueError`.
Dependencies under `/usr/lib/` and `/System/` are host libraries, so the translated program calls the Intel Mac's own copies.
The C++ runtime install names are the exception: `/usr/lib/libc++.1.dylib`, `/usr/lib/libc++abi.1.dylib`, `/usr/lib/libc++abi.dylib` and `/usr/lib/libunwind.1.dylib` resolve to the arm64 builds in `guestrt/lib`, or in `GDYLD_GUESTRT`.
An image that links `libobjc` and none of those gets the guest `libc++abi` as an extra dependency, because Objective-C exceptions run through it.
Other dependencies are found through `@rpath` (the `LC_RPATH` entries of the load chain, innermost first), `@loader_path` and `@executable_path`.
A dependency file with an x86-64 slice is a host image: it is bound and run natively, never translated.
A required dependency that is not found raises `FileNotFoundError`; a missing weak dependency is skipped.
Images get fixed addresses from `0x200000000`, each on a 16 MB boundary with at least 16 MB between images, and the guest C++ runtime always sits at `0x400000000`, `0x410000000` and `0x420000000`.

## 2. Link

`link()` copies each image's segments into a flat buffer, applies its rebases, and resolves its binds through the export tries (two-level, flat, weak and interposed).
A bind to a guest image is written into the buffer; a bind to a host library becomes a host bind that `translated` fills in when it starts.
A non-weak symbol that no image exports raises `LookupError`.
Each flat image is written to `image<k>.bin`, where image 0 is the executable.

## 3. Bridge the host imports

Every host symbol the images import gets one slot and one entry in the generated `bridge.hpp`.
`gdyld` collects the C names declared by a fixed set of base SDK headers and by the umbrella headers of the program's host frameworks.
For each declared function, `sbt/gbridge.hpp` derives an Apple arm64 to x86-64 SysV bridge from its header prototype when `host.cpp` is compiled.
Calls with special rules have hand-written bridges, among them the `printf` and `scanf` families, `open`, `fcntl`, `ioctl`, `pthread_create`, `sigaction`, `dlopen` and `dlsym`, `setjmp` and `longjmp`, and `objc_msgSend`.
On Apple arm64 `long double` is `double`, so the `long double` math functions are bridged to their `double` versions.
A C symbol that no header declares and the Swift signature database does not cover is resolved by name when `translated` starts.
Data symbols of that kind work; calling one as code stops the program with `FATAL: call to a host import with no header prototype (no bridge)`.
Swift imports are bridged with signatures from `sbt/swift_sigs.json`, a database that `sbt/gswift.py` reads from swiftc's LLVM IR for x86-64 and arm64 over the Swift corpus in `sbt/swift_corpus/` and `tests/swift/`.
Signatures the corpus lacks are derived from the SDK's `.swiftinterface` files by `sbt/gswift_iface.py`.

## 4. Lift

An image's functions start at the addresses listed in its `LC_FUNCTION_STARTS`, plus the entries of its Objective-C selector stubs.
`recompile.lift_function()` turns one function into one C function that reads and writes a CPU-state struct: `X[31]`, `SP`, the four NZCV flags and `V[32]`.
The lifter finds instructions by recursive descent from the function's entry and resume points, and words that control flow never reaches stay data.
A `br` through a jump table is decoded when the table's base, its entries and a bound on the index are proven on every path to it: the bound from a `cmp` and `b.hi`/`b.hs` (other instructions may sit between them, as clang 21 schedules a load there) or from an `and` mask, the base from straight-line code or, for a base set before a loop, by constant propagation over the function's control-flow graph.
When an indirect branch inside the function cannot be decoded, every instruction word of the function is lifted instead, and the branch becomes a switch over all of their addresses.
Such a function runs slower (an undecoded table in SQLite's bytecode loop made the whole shell 2.3 times slower), and the translation report names each one in a `WARNING: ... undecoded br` line.
The return sites of `setjmp`-family calls and the C++ landing pads become resume points, where a function can be re-entered in the middle.
The functions are written in chunks of 6000 instructions as `image<k>_<j>.cc`, or `.c` when `GDYLD_CHUNK_LANG` is set to anything but `c++`, plus `image<k>_t.c`, which maps guest addresses to the C functions.
The lift runs in forked worker processes when more than one lift job is allowed (`GDYLD_LIFT_JOBS`) and the images have at least 16 chunks in all.
An instruction with no lifter case is listed in the result and replaced by a call that stops the program if it runs; [lifter.md](lifter.md) shows how to add one.
`gdyld` then works out where the NZCV flags must be stored at calls and returns, and writes that plan to `gd_flags_<k>.h`.

Calls between lifted functions follow the AAPCS64 register contract wherever `gdyld` can show the code keeps it.
A call then stores to the CPU struct only what a callee may read (x0-x8, x16, x17, fp, lr, sp, v0-v7 and the flags), a return stores the results (x0, x1, fp, sp and v0-v3), and after a call only x0, x1, v0-v3 and the flags are read back; the callee-saved registers x19-x28 and v8-v15 stay in C locals across the call.
Machine-outlined code and hand-written assembly can break the contract, so the lifter records, for every function, the registers past the arguments it reads at entry and the callee-saved registers it leaves changed; a register its own prologue saved counts as the function's.
`gdyld` closes those facts over the direct calls in each image and the calls between images. A call into a function that breaks the contract stores and reloads every register, and that function's returns store every register.
A call after which the caller reads a register the call may have changed gets the same treatment.
An image keeps full register sync at every call when one of its functions that breaks the contract can be reached through a pointer or an export (an indirect call cannot tell), when it links a Swift library (Swift passes self, errors and async contexts in x20, x21 and x22), or when `GDYLD_ABI=0` is set.
Functions with resume points also keep every store and reload, so the C++ unwinder and `longjmp` find callee-saved registers in the CPU struct.
The translation report has one `register contract` line per image.

## 5. Build

The output directory also receives these generated files:

- `gd_disp.c` — the miss path of the indirect-call caches.
- `bridge.hpp` — one entry per host import.
- `layout.hpp` — the guest images, host binds, initializers, thread-local variables and the entry point.
- `gdyld_gen.hpp` — tables for guest `dlopen` and `dlsym`, and for Objective-C method parameters that need typing.
- `swift_gen.hpp` — the Swift bridges and the guest Swift records.
- `host.cpp` — the SDK headers, `sbt/gbridge.hpp` (which includes `sbt/gobjc.hpp`, `sbt/gswift.hpp` and `sbt/gvarargs.h`), `bridge.hpp` and `layout.hpp`.

clang compiles the chunks for x86-64 at `-O2` and `host.cpp` as Objective-C++ at `-O1`, at most 8 at a time, and links `translated` with a 512 MB main-thread stack.
Chunk objects go through a content-addressed cache keyed by the compile flags and the source text, in `sbt/build/objcache` or `GDYLD_OBJCACHE`.
`compile_stats.json` records each compile's seconds and peak memory.
`host_link_cmds.json` keeps the `host.cpp` compile and link commands, which `tools/relink_host.py` reruns after a change to the host runtime headers.
A host dylib that the program loads through `@loader_path` or `@executable_path` is symlinked into the output directory.
A guest-host incompatibility found by the host link raises `LookupError` with the message `gdyld link: ...`.

## 6. Run

When `translated` starts, its `main()` in `sbt/gbridge.hpp`:

1. maps the import slots and reads each `image<k>.bin` back to its address, stopping with `FATAL: cannot open guest image` if one is missing;
2. resolves every host import and writes the host binds, stopping with `FATAL: symbol not found in the host` for a missing non-weak one;
3. registers the guest's Objective-C selectors, protocols, classes and categories, then its Swift records, with the host runtimes;
4. runs `+load` methods and initializers in dependency order;
5. calls the guest's `main` with `argc`, `argv`, `envp` and the apple strings on an 8 MB guest stack.

When `main` returns, the thread-local destructors run and the process exits with `main`'s return value.
Guest threads run on host threads, and each one gets a guest stack of the size its attributes ask for.
`_NSGetExecutablePath` returns the original arm64 executable's path, not the path of `translated`.

## Diagnostic tools

Each Python script in `tools/` states its usage in its docstring.

- `tools/import_classes.py <arm64 executable>` prints the bridge class of every host import without lifting or building.
- `tools/abi_audit.py` lists prototype-bridged imports whose types the SDK lays out differently for arm64 and x86-64.
- `tools/relink_host.py <out dir>` recompiles `host.cpp` and relinks a build in place, without touching the lifted chunks.
- `tools/safe_trace.py` summarizes a crash report or a log with the frame names that carry guest addresses replaced.
- `tools/loop_run.py <exe> <n>` runs an executable `n` times and prints the runs that fail or differ from the first.
- `tools/xdis.py` disassembles one function of one Mach-O slice, at most a bounded number of instructions.
