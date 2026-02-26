"""Unit tests for HyperPress core compress/decompress functionality."""

import os
import struct
import zlib
import pytest

from hyperpress import compress, decompress


class TestRoundtrip:
    """Test that decompress(compress(data)) == data for various data types."""

    def test_empty_data(self):
        compressed = compress(b"")
        assert decompress(compressed) == b""

    def test_single_byte_zero(self):
        data = b"\x00"
        assert decompress(compress(data)) == data

    def test_single_byte_ff(self):
        data = b"\xff"
        assert decompress(compress(data)) == data

    def test_single_byte_ascii(self):
        data = b"A"
        assert decompress(compress(data)) == data

    def test_two_bytes(self):
        data = b"\x00\xff"
        assert decompress(compress(data)) == data

    def test_english_text(self):
        data = b"The quick brown fox jumps over the lazy dog."
        assert decompress(compress(data)) == data

    def test_german_text_utf8(self):
        data = "Kuenstliche Intelligenz revolutioniert die Datenverarbeitung.".encode("utf-8")
        assert decompress(compress(data)) == data

    def test_ascii_text(self):
        data = b"Hello, World! This is a test of ASCII text compression."
        assert decompress(compress(data)) == data

    def test_repeated_pattern(self):
        data = b"ABCDEFGH" * 500
        assert decompress(compress(data)) == data

    def test_all_zeros(self):
        data = b"\x00" * 10000
        assert decompress(compress(data)) == data

    def test_all_ones(self):
        data = b"\xff" * 10000
        assert decompress(compress(data)) == data

    def test_alternating_bytes(self):
        data = b"\x00\xff" * 5000
        assert decompress(compress(data)) == data

    def test_sequential_bytes(self):
        data = bytes(range(256)) * 40
        assert decompress(compress(data)) == data

    def test_binary_with_many_nulls(self):
        data = bytearray(20000)
        for i in range(0, 20000, 50):
            data[i] = 0xAB
        data = bytes(data)
        assert decompress(compress(data)) == data

    def test_large_random_data(self):
        data = os.urandom(1024 * 1024)  # 1 MB
        assert decompress(compress(data)) == data

    def test_medium_random_data(self):
        data = os.urandom(100000)
        assert decompress(compress(data)) == data

    def test_small_random_data(self):
        data = os.urandom(100)
        assert decompress(compress(data)) == data

    def test_json_like_data(self):
        import json
        records = [{"id": i, "name": "item_%04d" % i, "value": i * 17 % 1000} for i in range(200)]
        data = json.dumps(records, indent=2).encode()
        assert decompress(compress(data)) == data

    def test_log_data(self):
        lines = []
        for i in range(500):
            level = ["INFO", "WARN", "ERROR", "DEBUG"][i % 4]
            lines.append("2025-01-01T00:%02d:%02dZ [%s] service: msg #%d\n" % (
                i // 60, i % 60, level, i))
        data = "".join(lines).encode()
        assert decompress(compress(data)) == data

    def test_source_code(self):
        code = "def fib(n):\n  a,b=0,1\n  for _ in range(n): a,b=b,a+b\n  return b\n" * 50
        data = code.encode()
        assert decompress(compress(data)) == data

    def test_sensor_data(self):
        import random
        random.seed(99)
        s = bytearray()
        v = 128
        for _ in range(10000):
            v = max(0, min(255, v + random.randint(-3, 3)))
            s.append(v)
        data = bytes(s)
        assert decompress(compress(data)) == data


class TestCRCIntegrity:
    """Test that corrupted data raises AssertionError."""

    def test_corrupted_block_data_raises(self):
        data = b"Test data for CRC integrity check. " * 100
        compressed = bytearray(compress(data))
        # Corrupt a byte near the end of compressed data
        if len(compressed) > 30:
            compressed[-5] ^= 0xFF
        with pytest.raises((AssertionError, Exception)):
            decompress(bytes(compressed))

    def test_corrupted_magic_raises(self):
        data = b"Some test data here"
        compressed = bytearray(compress(data))
        compressed[0] = ord('X')  # Corrupt magic byte
        with pytest.raises((AssertionError, Exception)):
            decompress(bytes(compressed))

    def test_corrupted_crc_field_raises(self):
        data = b"More test data for corruption testing. " * 50
        compressed = bytearray(compress(data))
        hdr_size = struct.calcsize("<4sBBHQ")
        # BLK = "<IIBBI" -> CRC32 is at offset 10 within the block header
        crc_offset = hdr_size + 10
        if len(compressed) > crc_offset + 4:
            compressed[crc_offset] ^= 0xFF
            compressed[crc_offset + 1] ^= 0xFF
            compressed[crc_offset + 2] ^= 0xFF
            compressed[crc_offset + 3] ^= 0xFF
        with pytest.raises((AssertionError, Exception)):
            decompress(bytes(compressed))


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_exactly_4096_bytes(self):
        data = os.urandom(4096)
        assert decompress(compress(data)) == data

    def test_exactly_32768_bytes(self):
        data = os.urandom(32768)
        assert decompress(compress(data)) == data

    def test_exactly_65536_bytes(self):
        data = os.urandom(65536)
        assert decompress(compress(data)) == data

    def test_power_of_two_sizes(self):
        for exp in range(0, 14):  # 1 to 8192
            size = 2 ** exp
            data = os.urandom(size)
            assert decompress(compress(data)) == data

    def test_compress_returns_bytes(self):
        assert isinstance(compress(b"hello"), bytes)

    def test_decompress_returns_bytes(self):
        assert isinstance(decompress(compress(b"hello")), bytes)

    def test_compressed_starts_with_magic(self):
        compressed = compress(b"test data")
        assert compressed[:4] == b"HPRX"

    def test_verbose_mode(self, capsys):
        data = b"Testing verbose mode output. " * 200
        compress(data, verbose=True)
        captured = capsys.readouterr()
        assert "Blk" in captured.out
