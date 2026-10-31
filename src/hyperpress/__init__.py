"""
HyperPress — Adaptive Meta-Compression Engine

Usage:
    from hyperpress import compress, decompress

    compressed = compress(data)
    restored = decompress(compressed)
"""

from hyperpress.core import compress, decompress, HyperPressError, FORMAT_VERSION

__version__ = "2.0.1"
__all__ = ["compress", "decompress", "HyperPressError", "FORMAT_VERSION"]
