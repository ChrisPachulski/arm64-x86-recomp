# guestrt: guest C++ runtime (arm64 libunwind + libc++abi + libc++, LLVM 20.1.8)

A guest that links the system C++ runtime gets these arm64 builds in its place: gdyld translates them with the guest
at fixed bases (`sbt/gdyld.py` `RUNTIME`, `RUNTIME_LOAD`). gdyld reads them from `guestrt/lib`, or from the directory
in `GDYLD_GUESTRT`.

Build (zsh; log in `build/build.log`):

    guestrt/build.sh

If `src/llvm-project-20.1.8.src` is missing, build.sh downloads the release tarball, checks its sha256
(6898f963c8e938981e6c4a302e83ec5beb4630147c7311183cf61069af16333d, the GitHub release asset digest) and extracts only
runtimes, libcxx, libcxxabi, libunwind, libc (from_chars needs libc/shared), cmake, llvm/cmake, llvm/utils/lit and
llvm/utils/llvm-lit.
It installs into `out/` and copies the dylibs to `lib/`. Clean rebuild: `rm -rf build/runtimes out lib` first.

Configuration: `libcxx/cmake/caches/Apple.cmake` (Apple's own vendor cache: ABI v1, vendor availability annotations,
libdispatch PSTL, forgiving dynamic_cast) plus: Release -O2, arm64, deployment target 11.0, `-mcpu=apple-m1` (LSE
atomics), `LIBCXXABI_USE_LLVM_UNWINDER=ON`, shared only, no tests/benchmarks/docs/modules,
`-ffile-prefix-map` (no build-machine paths in the dylibs) and `-Wl,-fixup_chains`, so the dylibs use chained fixups
(`sbt/macho.py` only parses chained fixups; an 11.0 link would otherwise emit LC_DYLD_INFO_ONLY). The alternate
std::string layout comes from upstream `__configuration/abi.h`, which is byte-identical to the SDK's and turns it on
for every Apple non-x86 target. Install names: /usr/lib/libc++.1.dylib, /usr/lib/libc++abi.1.dylib,
/usr/lib/libunwind.1.dylib (libc++ re-exports the libc++abi symbols, as Apple's does).

Output: `out/lib` (dylibs, copied to `lib/`), `out/include/c++/v1` (headers + `__config_site`, identical to the SDK's
`__config_site`).

Verification (each runs bare from the repository root with its Python environment; results in `out/verify/`):
- `verify_layout.py`: `probe/layout_probe.cpp` compiled for arm64 against the SDK headers and the built ones; every
  sizeof/alignof/member offset must be identical -> layout.json
- `census_rt.py`: lift census of the three dylibs (functions, instructions, % lift-supported) -> census_<lib>.json
