# Testing

Most tests are differential: a translation is right when it behaves like a reference.
For whole programs the reference is the same source built natively for x86-64; for single instructions and short snippets it is the Unicorn emulator running the arm64 code.

## Before you run them

Set up `sbtenv` and build the guest C++ runtime as the [README](../README.md#install) shows.
The beds compile their test programs with clang and swiftc on the Intel Mac, and most of them build every program for both `arm64` and `x86_64`.
Most runners write their builds to a `build/` or `build_*/` directory next to themselves, which git ignores.

## Run the beds

```sh
sbtenv/bin/python tools/run_beds.py [--jobs=N] [--log=<dir>] [bed names ...]
```

With no names it runs every bed, 4 at a time (`--jobs`), and writes one log per bed to `tests/beds_logs/` (`--log`).
It prints one line per bed (name, exit status, seconds, and the last line of its log that looks like a summary), then a total line that lists the beds that exited nonzero.
Most bed runners exit 0 even when a case fails, so read the summary lines; `run_beds.py` exits 1 only when a bed exits nonzero.

| Bed | Runner | What it checks |
|---|---|---|
| `microtest_forms`, `microtest_core`, `microtest_m45`, `microtest_m67` | `sbt/microtest.py` with case modules | Instruction snippets, lifted and compiled for x86-64, compared with Unicorn on `x0`-`x30` and `sp`, and on NZCV, the vector registers and memory where a case asks. |
| `m3a2_cf` | `sbt/cases_m3a2_cf.py` | Whole arm64 snippets with branches and jump tables, lifted and compared with Unicorn. |
| `check_ab_exit` | `tests/perf/check_ab_exit.py` | `ab_translate.py` and `ab_perf.py` exit nonzero on a translation error and on an output mismatch. |
| `adv` | `tests/adv/run_adv.py` | Adversarial programs against the native build, and cases that must stop loudly at link or run time. |
| `cxx` | `tests/cxx/run_cxx.py` | The loader's fixups of the guest C++ runtime against `dyld_info`, then C++ and exception programs against the native build. |
| `cxx_adv` | `tests/cxx_adv/run_cxx_adv.py` | Harder C++ runtime and exception programs against the native build. |
| `objc`, `objc_adv` | `tests/objc/run_objc.py`, `tests/objc_adv/run_objc_adv.py` | Objective-C and blocks programs against the native build. |
| `m6c_objc_cache` | `tests/m6c/run_objc_cache.py` | The per-call-site Objective-C send cache when a disposed class's address is reused. |
| `m6c_flags` | `tests/m6c/run_flags.py` | NZCV placement: translated flag programs against Unicorn, plus a broken plan that must differ. |
| `swift`, `swift_adv`, `swift_adv_corpus` | `tests/swift/run_swift.py`, `tests/swift_adv/run_swift_adv.py` | Swift programs against the native build; `--corpus` adds the adversarial sources to the signature corpus. |
| `swift_link` | `tests/swift_adv/run_link_checks.py` | Weak Swift imports and the same Swift symbol imported from two host dylibs. |
| `uiguard` | `tests/uiguard/run_uiguard.py` | Every window-server, AppKit-UI and GPU case stops loudly before its call; a Foundation-only case still runs. |
| `dl`, `m5b_dl` | `tests/dl/run_dl.py`, `tests/m5b_adv/dl/run_m5b_dl.py` | Guest `dlopen` and `dlsym`, including an arm64 image outside the load graph. |
| `m5b_cb` | `tests/m5b_adv/cb/run_m5b_cb.py` | Guest callbacks that host code calls (libc, CoreFoundation and Foundation callback tables, later calls from other threads), against the native build. Two cases mismatch on the known gaps in [limits.md](limits.md): `c1_cfuncs` (a variadic function with no bridge) and `c5_fts` (callback pointer identity). |
| `fp16` | `tests/fp16/run_fp16_loud.py` | Half-precision `fcmp` and `scvtf`/`ucvtf` stay unsupported instead of being lifted as single precision. |
| `msglookup` | `tests/m7b/run_msglookup.py` | The `objc_msgLookup` thunks, natively on the host. |
| `send_cache` | `tests/m7b/run_send_cache.py` | One send site under swizzling, method changes, forwarding, KVO and two threads, against the native build. |
| `heapguard` | `tests/heapguard/run_heapguard.py` | `GDYLD_HEAP_GUARD` stops overflows, use after free and double frees; `GDYLD_PROFILE` writes no guest names. |
| `abi` | `tests/abi/run_abi.py` | Host functions whose array element type differs between arm64 and x86-64 macOS. |

## Your own beds

`tools/beds_local.txt` is optional and ignored by git.
Each line is `cpu <name> <script> [args ...]`, `gpu <name> <script> [args ...]` or `after <name> <script> [args ...]`, with the script path relative to the repository root; `#` starts a comment line.
`cpu` beds join the parallel pool after the built-in ones, and `gpu` beds run one at a time after all of them.
An `after` line adds a step that runs after the bed called `<name>` exits 0, with its output appended to that bed's log.
Every bed runs with the same Python as `run_beds.py`, from the repository root.

## Runners outside the default list

- `tests/m4a_adv/run_ix.py` — interior entry points, the address lookup tables and calls into the main image through `dlsym`.
- `tests/m4a_adv/run_ui2.py` — more UI-guard routes, including stops inside `+load` and constructors under `GDYLD_INIT_ONLY`.
- `tests/perf/run_perf.py` — speed of translated benchmarks against native builds, after checking that their output matches.
- `guestrt/verify_layout.py` and `guestrt/census_rt.py` — the guest C++ runtime checks described in [guestrt/BUILD.md](../guestrt/BUILD.md).

## Single instructions

`sbt/microtest.py` runs its built-in cases plus every case module named on its command line:

```sh
sbtenv/bin/python sbt/microtest.py cases_scalar cases_neon
```

[lifter.md](lifter.md) describes the case format and how to add cases.
