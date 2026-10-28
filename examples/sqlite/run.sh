#!/bin/bash
# SQLite 3.54.1 on an Intel Mac: its shell and speedtest1, built for arm64 only and translated, against x86-64 builds
# of the same source. Usage: examples/sqlite/run.sh [work directory]; exits 1 if any output differs.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="${1:-$here/work}"
py="$root/sbtenv/bin/python"
zip_url=https://sqlite.org/2026/sqlite-amalgamation-3540100.zip
zip_sha3=92281c86e2957f9b9305890f9ac04204caa7b677cc868dc326d942689df28e30          # sqlite.org download page
st_url=https://raw.githubusercontent.com/sqlite/sqlite/version-3.54.1/test/speedtest1.c
st_sha256=bcb4a3123b60db648e748837f5c46092e23a3b35d970f7da5e62c42809f18185
flags=(-O2 -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_MATH_FUNCTIONS -DSQLITE_ENABLE_RTREE)
sdk="$(xcrun --show-sdk-path)"
fail=0

check() {                                                    # check <name> <file> <hash> <algorithm>
  local got
  got="$("$py" -c 'import hashlib,sys; print(hashlib.new(sys.argv[2], open(sys.argv[1], "rb").read()).hexdigest())' "$2" "$4")"
  [ "$got" = "$3" ] || { echo "FAILED: $1 $4 is $got, expected $3"; exit 1; }
}
seconds() { "$py" -c 'import subprocess,sys,time; t=time.time(); subprocess.run(sys.argv[2:], stdin=open(sys.argv[1]), stdout=subprocess.DEVNULL, check=True); print("%.2f" % (time.time()-t))' "$@"; }
same() {                                                     # same <name> <file> <file>
  if cmp -s "$2" "$3"; then echo "PASS $1"; else echo "FAIL $1: $2 and $3 differ"; fail=1; fi
}

mkdir -p "$work" && cd "$work"
[ -f sqlite.zip ] || curl -fsSL -o sqlite.zip "$zip_url"
[ -f speedtest1.c ] || curl -fsSL -o speedtest1.c "$st_url"
check sqlite.zip sqlite.zip "$zip_sha3" sha3_256
check speedtest1.c speedtest1.c "$st_sha256" sha256
rm -rf src && mkdir src && (cd src && unzip -q ../sqlite.zip) && src="$work/src/sqlite-amalgamation-3540100"

for arch in arm64 x86_64; do
  clang -arch "$arch" -isysroot "$sdk" "${flags[@]}" "$src/shell.c" "$src/sqlite3.c" -o "sqlite3.$arch"
  clang -arch "$arch" -isysroot "$sdk" "${flags[@]}" -I"$src" speedtest1.c "$src/sqlite3.c" -o "speedtest1.$arch"
done
file sqlite3.arm64 speedtest1.arm64
"$py" "$root/tools/translate.py" sqlite3.arm64 out-sqlite3 | tail -1
"$py" "$root/tools/translate.py" speedtest1.arm64 out-speedtest1 | tail -1

for bin in sqlite3.x86_64 out-sqlite3/translated; do
  tag="${bin%%/*}"
  "./$bin" :memory: < "$here/suite.sql" > "suite.memory.$tag.txt"
  rm -f "file.$tag.db" && "./$bin" "file.$tag.db" < "$here/suite.sql" > "suite.file.$tag.txt"
  "./$bin" < "$here/mandelbrot.sql" > "mandelbrot.$tag.txt"
  rm -f "st.$tag.db" && "./${bin/sqlite3/speedtest1}" --verify --size 25 "st.$tag.db" | grep '^Verification Hash' > "speedtest1.$tag.txt"
done
same "suite.sql, in-memory database" suite.memory.sqlite3.x86_64.txt suite.memory.out-sqlite3.txt
same "suite.sql, on-disk database" suite.file.sqlite3.x86_64.txt suite.file.out-sqlite3.txt
same "mandelbrot.sql" mandelbrot.sqlite3.x86_64.txt mandelbrot.out-sqlite3.txt
same "speedtest1 --verify --size 25 ($(cut -d' ' -f3- speedtest1.out-sqlite3.txt))" speedtest1.sqlite3.x86_64.txt speedtest1.out-sqlite3.txt
echo "suite.sql seconds: native x86-64 $(seconds "$here/suite.sql" ./sqlite3.x86_64 :memory:), translated $(seconds "$here/suite.sql" ./out-sqlite3/translated :memory:)"
exit $fail
