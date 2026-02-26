<p align="center">
  <img src="https://img.shields.io/badge/HyperPress-v1.0-00f0ff?style=for-the-badge&labelColor=0a0a0f" alt="HyperPress v1.0">
  <img src="https://img.shields.io/badge/compression-92.2%25-00f0ff?style=for-the-badge&labelColor=0a0a0f" alt="92.2% compression">
</p>

<h1 align="center">HyperPress</h1>
<p align="center"><strong>Adaptive Meta-Compression Engine</strong></p>
<p align="center">
  Beats zlib-6 by ~49% &middot; Beats LZMA by ~24% &middot; Pure Python &middot; Zero dependencies
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

HyperPress is **not** a new compression algorithm. It is an **intelligence layer** that analyzes your data block-by-block and selects the optimal combination of preprocessing transforms and compression backends — then picks the smallest result.

```python
from hyperpress import compress, decompress

compressed = compress(data)
restored = decompress(compressed)
```

That's it. Three lines. No configuration needed.

## Benchmark Results

Tested on **8 diverse datasets** (text, JSON, sensor data, logs, binary, source code):

```
┌──────────────────────────────────────────────────────┐
│         Compressor       │   Ratio   │   vs HyperPress │
├──────────────────────────┼───────────┼─────────────────┤
│  zlib-6                  │   84.7%   │   +49% larger    │
│  LZMA                    │   89.7%   │   +24% larger    │
│  HyperPress              │   92.2%   │   ★ winner       │
└──────────────────────────────────────────────────────┘
```

### Per-Dataset Breakdown

| Dataset | Original | zlib-6 | LZMA | HyperPress | Winner |
|---------|----------|--------|------|------------|--------|
| English Text | 21,930 B | 193 B (99.1%) | 240 B (98.9%) | **211 B (99.0%)** | zlib-6 |
| German Text | 31,300 B | 272 B (99.1%) | 284 B (99.1%) | **256 B (99.2%)** | HyperPress |
| JSON Data | 33,582 B | 3,597 B (89.3%) | 1,764 B (94.7%) | **1,881 B (94.4%)** | LZMA |
| Sensor Data | 30,000 B | 21,990 B (26.7%) | 17,144 B (42.9%) | **11,148 B (62.8%)** | HyperPress |
| Sparse Binary | 25,000 B | 1,224 B (95.1%) | 1,032 B (95.9%) | **758 B (97.0%)** | HyperPress |
| Log File | 77,532 B | 10,704 B (86.2%) | 4,948 B (93.6%) | **5,109 B (93.4%)** | LZMA |
| Pattern+Noise | 24,000 B | 247 B (99.0%) | 168 B (99.3%) | **110 B (99.5%)** | HyperPress |
| Source Code | 7,680 B | 104 B (98.6%) | 160 B (97.9%) | **132 B (98.3%)** | zlib-6 |
| **TOTAL** | **251,024 B** | **38,331 B (84.7%)** | **25,740 B (89.7%)** | **19,605 B (92.2%)** | **HyperPress** |

HyperPress wins on aggregate by selecting the best approach for each data type.

## How It Works

```
Input Data
    │
    ▼
┌─────────────────────┐
│  Adaptive Block      │  Entropy-guided variable sizing (4KB–128KB)
│  Splitter            │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Block Profiler      │  Computes: entropy, delta-entropy, null-ratio,
│                      │  text-detection, structure-detection, unique bytes
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Candidate Selector  │  Rules engine picks 3–15 preprocessing+backend
│                      │  combinations based on block profile
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  Racing Engine       │  Tries all candidates in parallel,
│                      │  smallest compressed output wins
└──────────┬──────────┘
           │
           ▼
    HPRX Output (with per-block CRC32)
```

### 7 Preprocessing Transforms

| # | Transform | Best For |
|---|-----------|----------|
| 0 | Identity | Data that compresses well raw |
| 1 | Delta | Slowly-changing signals (sensor data) |
| 2 | Delta-16 | 16-bit aligned structured data |
| 3 | BWT + MTF | Text-heavy data (English, German, logs) |
| 4 | RLE | Sparse data with zero-runs |
| 5 | Transpose | Fixed-width records with column correlation |
| 6 | Nibble Split | Data with upper/lower nibble patterns |

### 5 Compression Backends

| # | Backend | Strategy |
|---|---------|----------|
| 0 | zlib-9 | Fast, good general-purpose |
| 1 | LZMA-extreme | Highest single-algorithm ratio |
| 2 | bz2-9 | Strong on text with BWT synergy |
| 3 | zlib → LZMA | Two-stage chain compression |
| 4 | Stored | Fallback for incompressible data |

## Installation

```bash
# From source
git clone https://github.com/BEKO2210/HyperPress.git
cd HyperPress
pip install -e .
```

## Usage

### Basic Compression

```python
from hyperpress import compress, decompress

# Compress any bytes
data = open("myfile.bin", "rb").read()
compressed = compress(data)

# Decompress
restored = decompress(compressed)
assert restored == data
```

### Verbose Mode

```python
compressed = compress(data, verbose=True)
# Prints per-block statistics:
#   Blk   1:   32,768B ->    5,421B (16.5%) |    DELTA+LZMA
#   Blk   2:   32,768B ->   18,902B (57.7%) |     NONE+LZMA
```

### Run Benchmarks

```bash
python -m hyperpress.core
```

## HPRX Binary Format

Self-contained, no external dependencies needed to decompress.

```
Global Header (16 bytes):
  4B  Magic      "HPRX"
  1B  Version    0x01
  1B  Flags      0x01 (integrity check enabled)
  2B  Blocks     uint16 block count
  8B  OrigSize   uint64 original data size

Per Block Header (14 bytes):
  4B  OrigSize   uint32
  4B  CompSize   uint32
  1B  PreProc    enum (0–6)
  1B  Backend    enum (0–4)
  4B  CRC32      checksum of original block

Block Data:
  [CompSize bytes of compressed data]
```

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

**55 tests** covering:
- Roundtrip correctness for all data types
- CRC32 integrity verification (corrupted data detection)
- Benchmark assertions (HyperPress > LZMA > zlib-6 on aggregate)
- 100-round fuzz testing with variable entropy levels
- Edge cases (empty, 1-byte, power-of-2 sizes, all-zeros, all-0xFF)

## Requirements

- **Python 3.8+**
- **Zero external dependencies** — uses only the Python standard library (`zlib`, `lzma`, `bz2`, `struct`, `math`)

## License

MIT License — Copyright 2025 Belkis Aslani

---

<p align="center">
  Built by <strong>Belkis Aslani</strong><br>
  <a href="https://beko2210.github.io/HyperPress/">Live Demo</a> · <a href="https://github.com/BEKO2210/HyperPress">GitHub</a>
</p>
