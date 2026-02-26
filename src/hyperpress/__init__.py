"""
HyperPress — Adaptive Meta-Compression Engine

Usage:
    from hyperpress import compress, decompress

    compressed = compress(data)
    restored = decompress(compressed)
"""

from hyperpress.core import compress, decompress

__version__ = "1.0.0"
__all__ = ["compress", "decompress"]
