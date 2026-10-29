# Environment variables

None of these is needed for an ordinary translation.

## The translator

`sbt/gdyld.py` reads these when it is imported, so set them before you run `tools/translate.py`.

| Variable | Default | Effect |
|---|---|---|
| `GDYLD_GUESTRT` | `guestrt/lib` | Directory holding the guest `libunwind.1.dylib`, `libc++abi.1.dylib` and `libc++.1.dylib`. |
| `GDYLD_OBJCACHE` | `sbt/build/objcache` | Directory of the content-addressed cache of compiled chunk objects. |
| `GDYLD_LIFT_JOBS` | the smallest of 8, half the CPU cores, and the RAM in GB divided by 8, but at least 1 | Number of forked lift workers; `1` lifts serially, one function at a time. |
| `GDYLD_NZCV` | `nob` | How NZCV stores are placed at calls and returns: `exact`, `nob` or `direct`. |
| `GDYLD_ABI` | unset | `0` keeps every guest register in sync with the CPU struct at every call and return, in place of the AAPCS64 register contract ([how-it-works.md](how-it-works.md#4-lift)). |
| `GDYLD_CHUNK_LANG` | `c++` | Any other value writes the lifted chunks as C instead of C++. |
| `GDYLD_CHUNK_XFLAGS` | empty | Extra clang flags for the lifted chunks; the code marks it as for experiments only. |
| `GDYLD_PGO` | unset | `generate` builds the chunks with profile instrumentation, so the translated program writes a profile when it exits (to `LLVM_PROFILE_FILE`, `default.profraw` if that is unset). A path to a profile merged with `xcrun llvm-profdata merge` builds the chunks optimized with it. |
| `GDYLD_LTO` | unset | `thin` compiles the chunks for ThinLTO, so clang inlines between them at link time; the link takes longer and caches its work under `GDYLD_OBJCACHE`. |

With `GDYLD_NZCV` at `exact` or `nob`, a flag value whose origin cannot be placed makes the whole translation store NZCV at every call and return; `direct` ignores such origins instead.
`exact` and `nob` differ only in how they treat calls and tail calls through stubs to host imports.

A profile comes from a run of an instrumented translation on a workload like the one you care about:

```sh
GDYLD_PGO=generate sbtenv/bin/python tools/translate.py prog prog-train
LLVM_PROFILE_FILE=/tmp/prog-%p.profraw prog-train/translated < training-input
xcrun llvm-profdata merge -o prog.profdata /tmp/prog-*.profraw
GDYLD_PGO=prog.profdata GDYLD_LTO=thin sbtenv/bin/python tools/translate.py prog prog-fast
```

The profile is tied to the translation it came from: translate the same binary with the same translator, or clang ignores the functions that changed.

## The translated program

`translated` reads these when it starts.
Each one is off when unset.

| Variable | Value | Effect |
|---|---|---|
| `GDYLD_CRASH_TRACE` | any | On `SIGSEGV` or `SIGBUS`, prints `FATAL: signal ...` with the faulting address and registers and a host backtrace, then exits with status 71. |
| `GDYLD_TRACE_IMPORTS` | any | Counts the calls to every host import and prints `import-trace <name> <calls> first <order>` lines at exit and before a loud stop; when the initializers finish it prints the same counts as `import-trace-init` lines. |
| `GDYLD_STOP_AT_IMPORT` | `name[,name...]` | Stops loudly before the host call when the guest calls one of the named imports, with or without the leading underscore, by any route. |
| `GDYLD_HEAP_GUARD` | `lo-hi` or `lo-hi,host` | Gives each guest `malloc`, `calloc`, `aligned_alloc` and default-zone `malloc_zone_malloc` block of `lo` to `hi` bytes (`hi` at most 3072) its own page, followed by an inaccessible page. |
| `GDYLD_PROFILE` | `path[,hz]` | Samples every running thread `hz` times a second (1 to 2000, default 200) and writes the counts to `path` every 10 seconds and at exit. |
| `GDYLD_INIT_ONLY` | any | Runs every image's `+load` methods and initializers, then exits with status 0 before `main`. |
| `GDYLD_VERBOSE` | any | Prints how many guest Swift classes were registered, when there are any. |
| `GSW_TRACE` | any | Prints every Swift bridge call on stderr. |
| `GDYLD_TEST_WITHHOLD_NSLOT` | text | Test hook: native vtable slots whose signature contains the text stay unbridged. Only builds that use the `v8/` extension have such slots. |

### Heap guard details

With `GDYLD_HEAP_GUARD`, free makes a block's page inaccessible and keeps it out of reuse for a while, so a write past the end of a block or into a freed block faults at the writing instruction.
With `GDYLD_CRASH_TRACE` as well, the crash report names the block's size and the backtraces of its allocation and free.
Misusing a guarded block, such as freeing it twice, stops with `FATAL: GDYLD_HEAP_GUARD: ...` and exit status 72.
`,host` also guards the host's own allocations, by making the guard zone the default malloc zone.

### Profile output

`GDYLD_PROFILE` groups the samples by image and symbol, for the main thread, the other threads, and the threads that are waiting.
All translated functions count as one group, `translated guest code`; their names are never written.

## The beds

| Variable | Read by | Effect |
|---|---|---|
| `ADV_SBT` | `tests/adv/run_adv.py` | Translator directory to test instead of `sbt/`. |
| `OBJC_REPEAT` | `tests/objc_adv/run_objc_adv.py` | Number of times to run each translated program (default 1). |
| `ADV_DROP_WITNESS` | `tests/swift_adv/run_swift_adv.py` | Comma-separated requirements to leave unbridged, to exercise the loud path. |
| `AB_SHIM` | `tests/perf/shim/gdyld.py` | `fail` (default) or `diff`: how the stand-in translator used by `tests/perf/check_ab_exit.py` misbehaves. |
