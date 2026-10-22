# Third-party notices

This repository's code is under the MIT license in `LICENSE`. It bundles no third-party code.

Fetched at build or setup time, not stored here, each under its own license:

| What | Fetched by | Upstream |
|---|---|---|
| LLVM 20.1.8 runtimes source (libc++, libc++abi, libunwind) | `guestrt/build.sh` | https://github.com/llvm/llvm-project (Apache License v2.0 with LLVM Exceptions) |
| capstone, libclang, unicorn (Python packages) | `pip install -r requirements.txt` | see each package's license |

The translator runs programs you supply, on your own machine. Translating a program does not give you any right to
use, copy or distribute it; check that program's license.
