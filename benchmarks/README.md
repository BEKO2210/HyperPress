# Fair benchmark

Measures HyperPress v2 against the strongest settings of the standard tools on
real public corpora. Every byte counts: sizes are **brutto**, HPRX header included.

```bash
python benchmarks/fair_bench.py --quick --check   # Canterbury only (~20 s)
python benchmarks/fair_bench.py --check           # Canterbury + Silesia (slow, see below)
python benchmarks/corpus.py                       # only download + verify corpora
```

## Corpora

| corpus | archive | SHA256 |
|---|---|---|
| Canterbury (11 files, 2.8 MB) | `cantrbry.tar.gz` | `f140e8a5b73d3f53198555a63bfb827889394a42f20825df33c810c3d5e3f8fb` |
| Silesia (12 files, 211 MB) | `silesia.zip` | `0626e25f45c0ffb5dc801f13b7c82a3b75743ba07e3a71835a41e3d9f63c77af` |

`corpus.py` downloads with `urllib` into `benchmarks/.corpus/` (gitignored), aborts on a
hash mismatch and extracts only the expected regular files by basename (no path traversal,
no links).

## Opponents

| name | setting |
|---|---|
| `xz-9e` | `lzma.compress`, .xz container, preset `9 \| PRESET_EXTREME` |
| `xz-raw-9e` | raw LZMA2, preset `9 \| PRESET_EXTREME`, no container |
| `bz2-9` | `bz2.compress(level=9)` |
| `zlib-9` | `zlib.compress(level=9)` |
| `zstd-19` | stdlib `compression.zstd` level 19 (Python >= 3.14); otherwise the `zstd -19 --ultra --long=27` CLI if on PATH; otherwise skipped |

HyperPress runs at `level="best"` and `level="fast"`; both are roundtrip-verified, and
compress / decompress throughput is reported in MB/s (10^6 bytes per second).

## `--check`

Fails (exit 1) if any file violates

    HP_best <= min(stdlib opponents) + 16 B

"Stdlib opponents" are all opponents except a CLI zstd (the CLI uses `--long=27`,
which is not a HyperPress candidate). CI runs `--quick --check` on Python 3.14, where
stdlib zstd-19 is part of the check.

## Output

A markdown table on stdout (per file + totals) and `benchmarks/results.json` with all
sizes, throughputs, environment and the corpus hashes. Sizes are deterministic for a given
Python / liblzma / libbz2 / zlib / libzstd version; throughputs are machine-dependent.
