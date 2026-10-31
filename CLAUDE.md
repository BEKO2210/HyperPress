# CLAUDE.md — HyperPress Project

## What is HyperPress?
HyperPress is an adaptive meta-compressor: it tries many established codec configurations and keeps the smallest result. It is not a new algorithm and does not win on all data.

**v2 guarantee:** `len(compress(d)) <= min(xz-raw-9e, bz2-9, zstd-19*) + 16` (`*` only on Python 3.14+). Binding contract: `docs/SPEC-v2.md`.

**Design:** WHOLE candidates (xz/LZMA2 9e with delta, x86 BCJ, lc/lp/pb tuning; bz2-9; zstd-19; zlib-9; STORED) plus a BLOCKS path (block profiler, preprocessors, backends). Candidates run sequentially (no parallel racing). Never quote benchmark numbers that are not produced by `benchmarks/fair_bench.py` (full container size, real files, xz at 9e).

## Project Structure
```
src/hyperpress/          - Core library (compress/decompress)
tests/                   - Test suite (unit, benchmark, fuzz)
website/                 - Demo website
```

## Development
```bash
pip install -e .
python -m pytest tests/ -v
```

## Rules
- Python 3.8+ compatibility
- No external Python dependencies (stdlib only)
- MIT License — Copyright 2025 Belkis / BEL KI
- Commit messages in English, conventional format
