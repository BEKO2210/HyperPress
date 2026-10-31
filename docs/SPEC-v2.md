# HyperPress v2 — Contract

This file is the contract between all parallel work streams (core, tests, benchmark, docs).
Change it only through the coordinator.

## Goal

`len(compress(d)) <= min(xz-raw-9e, bz2-9, zstd-19*) + HEADER_MAX` for every input `d`,
where `*` = only when the stdlib has zstd (Python >= 3.14, `compression.zstd`).
`HEADER_MAX = 16` bytes. On real data HyperPress must often be strictly smaller
(delta / x86 / lc-lp-pb tuning / block path).

## Public API (`from hyperpress import ...`)

```python
compress(data: bytes, level: str = "best", verbose: bool = False) -> bytes
    # level "best": all candidates; "fast": whole-stream STORED, zlib-9, bz2-9, xz-raw preset 6 and
    # zstd-3 if available — at most 5 candidates, no block path.
decompress(data: bytes, max_output_size: int = 1 << 30) -> bytes
class HyperPressError(ValueError)   # every invalid / corrupt / truncated / oversize input
FORMAT_VERSION = 2
```

Rules:
- `decompress` NEVER uses `assert` for validation (must hold under `python -O`).
- `decompress` NEVER raises anything except `HyperPressError` for bad input
  (wrap `lzma.LZMAError`, `zlib.error`, `OSError`, `struct.error`, `ValueError`, `IndexError`, `KeyError`).
- `max_output_size`: raise `HyperPressError` if the declared size exceeds it, and stream-decode
  with a hard cap (lzma `max_length`, zlib `decompressobj(...).decompress(d, cap)`, bz2 `BZ2Decompressor.decompress(d, cap)`),
  so a bomb never allocates more than `max_output_size + 64 KiB`.
- Wrong CRC / size mismatch / trailing garbage -> `HyperPressError`.
- v1 streams (`HPRX` + version 1) still decompress unchanged.
- Python 3.8+ compatible, stdlib only. zstd import guarded:
  `try: from compression import zstd` -> `HAVE_ZSTD`.
- Output is deterministic (same input + same Python/lib version -> same bytes).

## Format v2

```
magic   4 B  b"HPRX"
version 1 B  2
mode    1 B  0 = WHOLE, 1 = BLOCKS
size    varint (LEB128, unsigned)  original length
crc32   4 B  little endian, CRC32 of the original data
-- mode WHOLE --
method  1 B  see table
payload rest of stream
-- mode BLOCKS --
nblocks varint
per block: osz varint, csz varint, preproc 1 B, backend 1 B, payload csz B
           (block CRC dropped, whole-file CRC above covers it)
```

Empty input: mode WHOLE, method STORED, size 0, crc 0.

WHOLE methods (all on the whole input, no block split):

| id | method |
|----|--------|
| 0 | STORED |
| 1 | xz raw LZMA2 preset 9e, dict = clamp(2*len, 4 KiB, 64 MiB), lc3 lp0 pb2 |
| 2 | bz2-9 |
| 3 | zstd-19 (only if HAVE_ZSTD; decoder raises HyperPressError if missing) |
| 4 | xz raw DELTA dist=1 + LZMA2 9e |
| 5 | xz raw DELTA dist=2 + LZMA2 9e |
| 6 | xz raw DELTA dist=4 + LZMA2 9e |
| 7 | xz raw X86 BCJ + LZMA2 9e |
| 8 | xz raw LZMA2 9e lc4 lp0 pb0 (text) |
| 9 | xz raw LZMA2 9e lc0 lp2 pb2 (structured) |
| 10 | xz raw LZMA2 9e lc1 lp0 pb0 |
| 11 | zlib-9 (raw deflate, wbits=-15) |
| 12 | xz raw LZMA2 preset 6 (fast level) |
| 13 | zstd-3 (fast level, if HAVE_ZSTD) |

Filter parameters needed for decoding are implied by the method id (nothing stored).
BLOCKS mode = existing v1 block engine (preprocessors + backends), kept as one candidate.
`compress(level="best")` runs every WHOLE method + BLOCKS and keeps the smallest.

## Out of scope for v2
Parallel racing (README must not claim it), new preprocessors, C extensions.

## v2.1 additions (2026-10-31)

### Speed (compress side only, format unchanged)
- `level="best"` may prune candidates using a deterministic probe on samples of the input, BUT it must
  always run methods 1 (xz raw 9e), 2 (bz2-9) and 3 (zstd-19, if HAVE_ZSTD) on the full input, so the
  guarantee `<= min(xz-raw-9e, bz2-9, zstd-19) + 16` still holds by construction.
- Targets on Silesia total: `best` >= 1 MB/s, `fast` >= 10 MB/s compression. `fast` has no size guarantee
  except `<= len(data) + 16`.
- Same input -> same output bytes (probe must be deterministic, no time-based decisions).

### Text transform (new WHOLE methods)
| id | method |
|----|--------|
| 14 | TEXT transform + bz2-9 |
| 15 | TEXT transform + xz raw LZMA2 9e (lc/lp/pb free to choose, but fixed per id) |

- Implemented in `src/hyperpress/textxf.py` (`encode(data) -> bytes`, `decode(payload, limit) -> bytes`).
  The transform is fully self-describing (any dictionary is stored inside the payload).
- Decoding must respect `max_output_size` (raise `HyperPressError` before allocating beyond limit + 64 KiB)
  and raise only `HyperPressError` on malformed payloads.
- Exact payload layout is documented in a docstring at the top of `textxf.py`.
- Candidates 14/15 are only tried when the input looks like text (cheap check), so they cost nothing on binaries.

### Memory cap (decoder)
- Every decode path (WHOLE, BLOCKS incl. every preprocessor, v1) keeps peak allocation
  <= `max_output_size + 64 KiB` beyond the input itself.
