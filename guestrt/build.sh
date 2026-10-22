#!/bin/zsh
# Build arm64 libunwind + libc++abi + libc++ (LLVM 20.1.8) into out/ and copy the dylibs to lib/ (gdyld.GUESTRT).
# Log: build/build.log
set -euo pipefail
LANE=${0:A:h}
SRC=$LANE/src/llvm-project-20.1.8.src
TARBALL=$LANE/src/llvm-project-20.1.8.src.tar.xz
SHA=6898f963c8e938981e6c4a302e83ec5beb4630147c7311183cf61069af16333d   # GitHub release asset digest
BLD=$LANE/build/runtimes
LOG=$LANE/build/build.log
SDK=$(xcrun --show-sdk-path)
MAP="-ffile-prefix-map=$SRC=llvm-project-20.1.8.src"   # no build-machine paths in the dylibs

mkdir -p $LANE/src $LANE/lib
if [[ ! -d $SRC ]]; then
  [[ -f $TARBALL ]] || curl -sL -o $TARBALL https://github.com/llvm/llvm-project/releases/download/llvmorg-20.1.8/llvm-project-20.1.8.src.tar.xz
  echo "$SHA  $TARBALL" | shasum -a 256 -c -
  tar -xJf $TARBALL -C $LANE/src llvm-project-20.1.8.src/{runtimes,libcxx,libcxxabi,libunwind,libc,cmake,llvm/cmake,llvm/utils/lit,llvm/utils/llvm-lit}
fi

mkdir -p $BLD
{
cmake -S $SRC/runtimes -B $BLD -G "Unix Makefiles" \
  -C $SRC/libcxx/cmake/caches/Apple.cmake \
  -DLLVM_ENABLE_RUNTIMES="libunwind;libcxxabi;libcxx" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=$(xcrun -f clang) -DCMAKE_CXX_COMPILER=$(xcrun -f clang++) \
  -DCMAKE_OSX_SYSROOT=$SDK -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=11.0 \
  -DCMAKE_SYSTEM_NAME=Darwin -DCMAKE_SYSTEM_PROCESSOR=arm64 \
  -DCMAKE_C_FLAGS="-mcpu=apple-m1 $MAP" -DCMAKE_CXX_FLAGS="-mcpu=apple-m1 $MAP" -DCMAKE_ASM_FLAGS="-mcpu=apple-m1 $MAP" \
  -DCMAKE_C_FLAGS_RELEASE="-O2 -DNDEBUG" -DCMAKE_CXX_FLAGS_RELEASE="-O2 -DNDEBUG" \
  -DCMAKE_SHARED_LINKER_FLAGS="-Wl,-fixup_chains" \
  -DCMAKE_INSTALL_PREFIX=$LANE/out \
  -DLIBCXX_ABI_VERSION=1 -DLIBCXXABI_USE_LLVM_UNWINDER=ON \
  -DLIBCXX_ENABLE_SHARED=ON -DLIBCXXABI_ENABLE_SHARED=ON -DLIBUNWIND_ENABLE_SHARED=ON \
  -DLIBCXX_ENABLE_STATIC=OFF -DLIBCXXABI_ENABLE_STATIC=OFF -DLIBUNWIND_ENABLE_STATIC=OFF \
  -DLIBCXX_INCLUDE_TESTS=OFF -DLIBCXXABI_INCLUDE_TESTS=OFF -DLIBUNWIND_INCLUDE_TESTS=OFF \
  -DLIBCXX_INCLUDE_BENCHMARKS=OFF -DLIBCXX_INCLUDE_DOCS=OFF -DLIBUNWIND_INCLUDE_DOCS=OFF \
  -DLIBCXX_INSTALL_MODULES=OFF
make -C $BLD -j8
make -C $BLD install
} > $LOG 2>&1
cp -a $LANE/out/lib/lib* $LANE/lib/
echo "build ok: $(ls $LANE/lib/*.dylib | tr '\n' ' ')"
