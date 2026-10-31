#!/usr/bin/env python3
"""Roundtrip a large synthetic file on every level, at default and exact limits.

The Canterbury quick bench in CI tops out at 1 MB, so it missed two decoder
bugs that only appear on large inputs (LZMA dictionary assumed 8 MiB, empty
drain at a buffer boundary read as truncation). This input repeats a 9 MiB
pseudo-random block, so a valid xz stream needs matches 9 MiB back.

Usage: python benchmarks/large_roundtrip.py   (exit 1 on any failure)
"""

import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from hyperpress import HyperPressError, compress, decompress  # noqa: E402
from hyperpress.core import _v2_header, _whole_compress  # noqa: E402

# Every xz WHOLE method, so a decoder bug in one is not hidden by the winner.
LZMA_METHODS = (1, 4, 5, 6, 7, 8, 9, 10, 12, 16)


def make_data():
    rnd = random.Random(2026)
    block = bytes(rnd.getrandbits(8) for _ in range(9 * 1024 * 1024))
    return block + block[: 4 * 1024 * 1024] + bytes(1024 * 1024)


def main():
    data = make_data()
    failures = 0
    for level in ("best", "fast"):
        t = time.time()
        blob = compress(data, level=level)
        for limit in (1 << 30, len(data)):
            try:
                ok = decompress(blob, max_output_size=limit) == data
            except HyperPressError as exc:
                ok = False
                print("  error:", exc)
            failures += not ok
            print("%-4s %d B -> %d B, limit %d: %s (%.1fs)" % (
                level, len(data), len(blob), limit, "ok" if ok else "FAIL", time.time() - t))
    header = _v2_header(0, data)
    for method in LZMA_METHODS:
        t = time.time()
        blob = header + bytes((method,)) + _whole_compress(data, method)
        try:
            ok = decompress(blob, max_output_size=len(data)) == data
        except HyperPressError as exc:
            ok = False
            print("  error:", exc)
        failures += not ok
        print("method %2d: %s (%.1fs)" % (method, "ok" if ok else "FAIL", time.time() - t))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
