# CLAUDE.md — HyperPress Project

## What is HyperPress?
HyperPress is an adaptive meta-compression engine that beats both zlib-6 and LZMA.

**Core concept:** Not a new algorithm, but an intelligence layer:
- Block Analysis (entropy, delta-entropy, null-ratio, structure detection)
- Preprocessing Racing (Delta, BWT+MTF, RLE, Transpose, Nibble-Split)
- Backend Competition (zlib-9, LZMA-extreme, bz2-9, zlib->LZMA chain)
- Per-Block Winner Selection: smallest result wins

**Benchmark results (8 datasets):**
- zlib-6: 84.7% compression
- LZMA: 89.7% compression
- HyperPress: 92.2% compression

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
