# HyperPress

[![CI](https://github.com/BEKO2210/HyperPress/actions/workflows/ci.yml/badge.svg)](https://github.com/BEKO2210/HyperPress/actions/workflows/ci.yml)
[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Adaptive Meta-Compression Engine** — beats zlib-6 by ~49% and LZMA by ~24% on aggregate benchmarks.

## How It Works

HyperPress is not a new compression algorithm. It is an **intelligence layer** that selects the optimal combination of preprocessing transforms and compression backends on a per-block basis:

1. **Block Analysis** — entropy, delta-entropy, null-ratio, structure detection
2. **Preprocessing Racing** — Delta, BWT+MTF, RLE, Transpose, Nibble-Split, Delta-16
3. **Backend Competition** — zlib-9, LZMA-extreme, bz2-9, zlib→LZMA chain, stored
4. **Per-Block Winner Selection** — smallest result wins

## Benchmark Results (8 diverse datasets)

| Compressor | Compression Ratio |
|------------|-------------------|
| zlib-6     | ~84.7%            |
| LZMA       | ~89.7%            |
| **HyperPress** | **~92.2%**    |

## Installation

```bash
pip install -e .
```

## Usage

```python
from hyperpress import compress, decompress

compressed = compress(data)
restored = decompress(compressed)
assert restored == data
```

## Run Benchmarks

```bash
python -m hyperpress.core
```

## Run Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Format: HPRX

HyperPress uses a custom binary format (HPRX) with per-block CRC32 integrity verification:

- **Global Header** (16 bytes): magic, version, flags, block count, original size
- **Per Block Header** (14 bytes): original size, compressed size, preprocessing method, backend, CRC32
- **Block Data**: compressed bytes

## Architecture

```
Input Data
    │
    ▼
┌─────────────────┐
│  Block Splitter  │  Entropy-guided adaptive splitting
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Block Analyzer  │  Entropy, delta-entropy, null-ratio, structure
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Candidate       │  Context-aware selection of preprocessing +
│  Selector        │  backend combinations to try
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Racing Engine   │  Try all candidates, pick smallest output
└────────┬────────┘
         │
         ▼
    HPRX Output
```

## License

MIT License — Copyright 2025 Belkis / BEL KI (AI Consultancy)

## Built by

**BEL KI** — AI Consultancy
