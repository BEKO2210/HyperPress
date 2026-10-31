<p align="center">
  <img src="https://img.shields.io/badge/HyperPress-v2.0-00f0ff?style=for-the-badge&labelColor=0a0a0f" alt="HyperPress v2.0">
</p>

<h1 align="center">HyperPress</h1>
<p align="center"><strong>Adaptive Meta-Compressor</strong></p>
<p align="center">
  Default level: never larger than the best of xz-9e / bz2-9 / zstd-19 (+ at most 16 header bytes) &middot; Pure Python &middot; Zero dependencies
</p>

<p align="center">
  <a href="https://github.com/BEKO2210/HyperPress/actions/workflows/ci.yml"><img src="https://github.com/BEKO2210/HyperPress/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.8%2B-blue.svg" alt="Python 3.8+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://beko2210.github.io/HyperPress/">Live Demo &amp; Documentation</a>
</p>

---

## What is HyperPress?

HyperPress is **not** a new compression algorithm. It is a **meta-compressor**: it runs several established compressors (LZMA2, bzip2, zlib, zstd when available) with different filters and parameters on your data and keeps the smallest result, so the output is never meaningfully worse than the best of them.

```python
from hyperpress import compress, decompress

compressed = compress(data)
restored = decompress(compressed)
```

## Honest status

An independent audit showed that the v1 marketing numbers were wrong: they came from self-generated, highly repetitive data, subtracted the container header ("netto"), counted ties as wins, did not run LZMA at its strongest setting, and on real files v1 was about 20 % *worse* than plain `xz -9e`. The "parallel racing" claim was also false — candidates are tried **sequentially**. All of those claims have been removed. v2 was redesigned around a checkable guarantee (below).

**No compressor wins on all data.** HyperPress is a safety net on top of existing codecs, not a better codec. On many inputs it ties the best single codec (and pays up to 16 bytes of header); on some it is slightly smaller (delta / x86 filters, LZMA `lc/lp/pb` tuning, block path for sensor-like data). It is also slower than any single codec, because it tries many candidates one after another.

## Guarantee

For every input `d` with the default `level="best"`:

```
len(compress(d)) <= min(xz-raw-9e, bz2-9, zstd-19*) + 16
```

`*` zstd-19 only counts when the standard library provides zstd (Python 3.14+, `compression.zstd`). The guarantee is enforced by construction (the plain xz-9e, bz2-9 and zstd-19 results are always candidates, plus a STORED fallback) and checked by the test suite. The container adds a fixed 11–16 bytes (magic, version, mode, size varint, CRC32, method), so tiny inputs grow: `b""` becomes 12 bytes, 10 random bytes become 22. `level="fast"` trades size for speed and has no size guarantee (it never expands beyond STORED + header). Output is deterministic for the same input and the same Python/library versions.

## Benchmarks

Results are produced by `benchmarks/fair_bench.py` on real files, with the **full container size** (no header subtraction) compared against `xz -9e`, bz2-9 and (if available) zstd-19.

<!-- BENCH:START -->
| Corpus | File | Original | HyperPress | Best stdlib opponent | vs best | vs xz -9e | vs zstd -19 |
|---|---|---:|---:|---|---:|---:|---:|
| canterbury | alice29.txt | 152,089 | 43,177 | bz2-9 43,202 | -25 B (-0.06 %) | -11.0 % | -12.3 % |
| canterbury | asyoulik.txt | 125,179 | 39,583 | bz2-9 39,569 | +14 B (+0.04 %) | -11.2 % | -12.3 % |
| canterbury | cp.html | 24,603 | 7,602 | xz-raw-9e 7,596 | +6 B (+0.08 %) | -0.7 % | -1.5 % |
| canterbury | fields.c | 11,150 | 2,956 | xz-raw-9e 2,973 | -17 B (-0.57 %) | -2.5 % | -2.0 % |
| canterbury | grammar.lsp | 3,721 | 1,222 | zlib-9 1,222 | +0 B (+0.00 %) | -5.4 % | +0.7 % |
| canterbury | kennedy.xls | 1,029,744 | 47,973 | xz-raw-9e 51,811 | -3838 B (-7.41 %) | -7.5 % | -31.2 % |
| canterbury | lcet10.txt | 426,754 | 107,665 | bz2-9 107,706 | -41 B (-0.04 %) | -9.9 % | -11.3 % |
| canterbury | plrabn12.txt | 481,861 | 145,566 | bz2-9 145,577 | -11 B (-0.01 %) | -12.0 % | -13.1 % |
| canterbury | ptt5 | 513,216 | 39,012 | xz-raw-9e 39,801 | -789 B (-1.98 %) | -2.1 % | -10.2 % |
| canterbury | sum | 38,240 | 9,409 | xz-raw-9e 9,443 | -34 B (-0.36 %) | -1.0 % | -15.1 % |
| canterbury | xargs.1 | 4,227 | 1,738 | zlib-9 1,736 | +2 B (+0.12 %) | -4.1 % | +0.5 % |
| silesia | dickens | 10,192,446 | 2,759,608 | bz2-9 2,799,520 | -39912 B (-1.43 %) | -2.5 % | -3.2 % |
| silesia | mozilla | 51,220,480 | 13,232,814 | xz-raw-9e 13,376,180 | -143366 B (-1.07 %) | -1.1 % | -12.0 % |
| silesia | mr | 9,970,564 | 2,441,295 | bz2-9 2,441,280 | +15 B (+0.00 %) | -11.3 % | -21.6 % |
| silesia | nci | 33,553,445 | 1,449,224 | xz-raw-9e 1,449,209 | +15 B (+0.00 %) | -0.0 % | -11.7 % |
| silesia | ooffice | 6,152,192 | 2,084,481 | xz-raw-9e 2,427,163 | -342682 B (-14.12 %) | -14.1 % | -19.8 % |
| silesia | osdb | 10,085,684 | 2,802,807 | bz2-9 2,802,792 | +15 B (+0.00 %) | -1.5 % | -9.5 % |
| silesia | reymont | 6,627,202 | 1,246,245 | bz2-9 1,246,230 | +15 B (+0.00 %) | -5.3 % | -7.5 % |
| silesia | samba | 21,606,400 | 3,739,479 | xz-raw-9e 3,739,464 | +15 B (+0.00 %) | -0.0 % | -3.8 % |
| silesia | sao | 7,251,944 | 4,425,619 | xz-raw-9e 4,425,604 | +15 B (+0.00 %) | -0.0 % | -11.5 % |
| silesia | webster | 41,458,703 | 8,368,624 | xz-raw-9e 8,368,609 | +15 B (+0.00 %) | -0.0 % | -3.0 % |
| silesia | x-ray | 8,474,240 | 4,051,127 | bz2-9 4,051,112 | +15 B (+0.00 %) | -9.8 % | -21.4 % |
| silesia | xml | 5,345,280 | 434,845 | xz-raw-9e 434,830 | +15 B (+0.00 %) | -0.0 % | -4.4 % |
| **Total** | 23 files | **214,749,364** | **47,482,071** | per-file best 48,012,629 | **-1.11 %** | **-3.00 %** | **-10.97 %** |

Sizes are full HPRX containers (header included). Speed on this run: `best` compresses at 0.94 MB/s and `fast` at 24.65 MB/s, but `fast` output is +24.2 % larger than `best`; decompression runs at about 48 MB/s. Python 3.12.3, zstd opponent: CLI: zstd -19 --ultra --long=27, 0 violations of the guarantee. Reproduce with `python benchmarks/fair_bench.py`.
<!-- BENCH:END -->

## How It Works (v2)

`compress(data, level="best")` builds candidates and keeps the smallest. Candidates are tried **one after another** (no parallelism).

```
Input Data
    │
    ├── WHOLE candidates (whole input, no block split)
    │     STORED, xz-raw LZMA2 9e, bz2-9, zstd-19*, zlib-9,
    │     DELTA(1/2/4) + LZMA2, x86 BCJ + LZMA2,
    │     LZMA2 with tuned lc/lp/pb (text / structured / other)
    │
    └── BLOCKS candidate (block engine inherited from v1)
          adaptive block split → block profiler → preprocessors
          (Delta, BWT+MTF, RLE, Transpose, Nibble-Split …) × backends,
          per-block smallest wins
    │
    ▼
 smallest stream wins → HPRX v2 output
```

`level="fast"` tries only whole-stream zlib-9, bz2-9, xz preset 6 and zstd-3 (if available) — at most 4 candidates, no block path.

## Installation

```bash
git clone https://github.com/BEKO2210/HyperPress.git
cd HyperPress
pip install -e .
```

## API

```python
from hyperpress import compress, decompress, HyperPressError, FORMAT_VERSION

compressed = compress(data, level="best", verbose=False)   # level: "best" | "fast"
restored = decompress(compressed, max_output_size=1 << 30)
```

- `decompress` raises **only** `HyperPressError` (a `ValueError` subclass) for invalid, corrupt, truncated, oversize or trailing-garbage input; it does not rely on `assert`.
- `max_output_size` is a decompression-bomb guard: a declared size above the limit is rejected up front and decoding is hard-capped while streaming.
- A whole-file CRC32 is verified on decompression.
- v1 streams (`HPRX` + version 1) still decompress.

## HPRX v2 Format

```
magic    4 B   "HPRX"
version  1 B   2
mode     1 B   0 = WHOLE, 1 = BLOCKS
size     varint (LEB128)   original length
crc32    4 B   little endian, CRC32 of the original data

mode WHOLE:   method (1 B) + payload
mode BLOCKS:  nblocks (varint), then per block:
              osz varint, csz varint, preproc 1 B, backend 1 B, payload
```

Fixed overhead is a few bytes (header + varints); filter parameters are implied by the method id. See [`docs/SPEC-v2.md`](docs/SPEC-v2.md) for the full method table.

## Limits

- Pure Python plus the stdlib codecs: slower than a single `xz`/`bz2` call, since many candidates are tried sequentially.
- Memory use grows with input size (candidates are compressed in memory).
- zstd candidates are only available on Python 3.14+; a stream that uses zstd cannot be decoded on an older Python (`HyperPressError`).
- Random or already-compressed data is stored essentially as-is.

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

The suite covers roundtrips, CRC/corruption handling, the size guarantee, bomb guard and fuzzing.

## Requirements

- **Python 3.8+**
- **Zero external dependencies** — stdlib only (`zlib`, `lzma`, `bz2`, optional `compression.zstd`)

## License

MIT License — Copyright 2025 Belkis Aslani

---

<p align="center">
  Built by <strong>Belkis Aslani</strong><br>
  <a href="https://beko2210.github.io/HyperPress/">Live Demo</a> · <a href="https://github.com/BEKO2210/HyperPress">GitHub</a>
</p>
