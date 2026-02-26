"""Fuzz / integrity tests: random data at various entropy levels."""

import os
import random
import pytest

from hyperpress import compress, decompress


class TestFuzzRoundtrip:
    """100 rounds of random data compress/decompress."""

    def test_random_roundtrip_100_rounds(self):
        """Compress and decompress 100 random payloads (1B to 100KB)."""
        rng = random.Random(42)
        for i in range(100):
            size = rng.randint(1, 100000)
            data = os.urandom(size)
            compressed = compress(data)
            restored = decompress(compressed)
            assert restored == data, "Fuzz roundtrip failed at round %d (size=%d)" % (i, size)


class TestEntropyLevels:
    """Test with data at different entropy levels."""

    def test_low_entropy(self):
        """Data with very few unique byte values (low entropy)."""
        rng = random.Random(100)
        for _ in range(20):
            size = rng.randint(100, 10000)
            # Only use 3 different byte values
            data = bytes(rng.choice([0, 1, 2]) for _ in range(size))
            assert decompress(compress(data)) == data

    def test_mid_entropy(self):
        """Data with moderate entropy (limited alphabet)."""
        rng = random.Random(200)
        alphabet = list(range(32))  # 32 unique values
        for _ in range(20):
            size = rng.randint(100, 10000)
            data = bytes(rng.choice(alphabet) for _ in range(size))
            assert decompress(compress(data)) == data

    def test_high_entropy(self):
        """Data with maximum entropy (uniform random bytes)."""
        for _ in range(20):
            size = random.randint(100, 10000)
            data = os.urandom(size)
            assert decompress(compress(data)) == data

    def test_mixed_entropy_blocks(self):
        """Data that alternates between low and high entropy sections."""
        parts = []
        for i in range(10):
            if i % 2 == 0:
                parts.append(b"\x00" * 1000)  # low entropy
            else:
                parts.append(os.urandom(1000))  # high entropy
        data = b"".join(parts)
        assert decompress(compress(data)) == data


class TestEdgeCasePatterns:
    """Test specific edge-case byte patterns."""

    def test_all_zeros(self):
        for size in [1, 10, 100, 1000, 10000]:
            data = b"\x00" * size
            assert decompress(compress(data)) == data

    def test_all_0xff(self):
        for size in [1, 10, 100, 1000, 10000]:
            data = b"\xff" * size
            assert decompress(compress(data)) == data

    def test_alternating_00_ff(self):
        for size in [2, 10, 100, 1000, 10000]:
            data = b"\x00\xff" * (size // 2)
            assert decompress(compress(data)) == data

    def test_ascending_bytes(self):
        data = bytes(i % 256 for i in range(50000))
        assert decompress(compress(data)) == data

    def test_descending_bytes(self):
        data = bytes((255 - i % 256) for i in range(50000))
        assert decompress(compress(data)) == data

    def test_sawtooth_pattern(self):
        """Repeating 0-255 ramp."""
        data = bytes(range(256)) * 200
        assert decompress(compress(data)) == data

    def test_single_byte_repeated(self):
        """Each possible byte value repeated."""
        for b in [0, 1, 127, 128, 254, 255]:
            data = bytes([b]) * 5000
            assert decompress(compress(data)) == data

    def test_two_byte_pattern(self):
        data = b"\xAB\xCD" * 25000
        assert decompress(compress(data)) == data

    def test_sparse_with_random_positions(self):
        """Mostly zeros with random non-zero bytes."""
        rng = random.Random(42)
        data = bytearray(50000)
        for _ in range(500):
            pos = rng.randint(0, 49999)
            data[pos] = rng.randint(1, 255)
        assert decompress(compress(bytes(data))) == bytes(data)

    def test_run_length_friendly_data(self):
        """Data with long runs of the same byte."""
        parts = []
        rng = random.Random(77)
        for _ in range(50):
            byte_val = rng.randint(0, 255)
            run_len = rng.randint(1, 500)
            parts.append(bytes([byte_val]) * run_len)
        data = b"".join(parts)
        assert decompress(compress(data)) == data

    def test_structured_records(self):
        """Simulated fixed-width records."""
        import struct
        records = []
        for i in range(1000):
            records.append(struct.pack("<IHBf", i, i % 1000, i % 256, float(i) * 0.1))
        data = b"".join(records)
        assert decompress(compress(data)) == data
