<p align="center">
  <img src="https://img.shields.io/badge/HyperPress-v1.0-00f0ff?style=for-the-badge&labelColor=0a0a0f" alt="HyperPress v1.0">
  <img src="https://img.shields.io/badge/compression-92.3%25-00f0ff?style=for-the-badge&labelColor=0a0a0f" alt="92.3% compression">
</p>

<h1 align="center">HyperPress</h1>
<p align="center"><strong>Adaptive Meta-Compression Engine</strong></p>
<p align="center">
  Beats zlib-9 by ~49% &middot; Beats LZMA-RAW by ~23% &middot; Pure Python &middot; Zero dependencies
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
│  zlib-9                  │   84.9%   │   +49% larger    │
│  LZMA-RAW                │   89.9%   │   +23% larger    │
│  HyperPress (netto)      │   92.3%   │   ★ winner       │
└──────────────────────────────────────────────────────┘
```

### Per-Dataset Breakdown

| Dataset | Original | zlib-9 | LZMA-RAW | HyperPress (netto) | Winner |
|---------|----------|--------|----------|-------------------|--------|
| English Text | 21,930 B | 193 B (99.1%) | 181 B (99.2%) | **181 B (99.2%)** | HyperPress |
| German Text | 31,300 B | 272 B (99.1%) | 226 B (99.3%) | **226 B (99.3%)** | HyperPress |
| JSON Data | 33,582 B | 3,491 B (89.6%) | 1,705 B (94.9%) | **1,929 B (94.3%)** | LZMA-RAW |
| Sensor Data | 30,000 B | 21,990 B (26.7%) | 17,087 B (43.0%) | **11,118 B (62.9%)** | HyperPress |
| Sparse Binary | 25,000 B | 1,195 B (95.2%) | 973 B (96.1%) | **728 B (97.1%)** | HyperPress |
| Log File | 77,532 B | 10,495 B (86.5%) | 4,889 B (93.7%) | **5,079 B (93.4%)** | LZMA-RAW |
| Pattern+Noise | 24,000 B | 184 B (99.2%) | 110 B (99.5%) | **80 B (99.7%)** | HyperPress |
| Source Code | 7,680 B | 104 B (98.6%) | 102 B (98.7%) | **102 B (98.7%)** | HyperPress |
| **TOTAL** | **251,024 B** | **37,924 B (84.9%)** | **25,273 B (89.9%)** | **19,443 B (92.3%)** | **HyperPress** |

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
- Benchmark assertions (HyperPress > LZMA > zlib on aggregate)
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
