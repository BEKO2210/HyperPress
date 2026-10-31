"""SPEC-v2 contract tests against the public API only.

These tests encode docs/SPEC-v2.md. They are expected to fail against the
v1 implementation; they must pass once the v2 core lands.
"""

import bz2
import lzma
import os
import random
import struct
import zlib

import pytest

from hyperpress import compress, decompress


EDGE_SIZES = (0, 1, 2, 3, 4095, 4096, 4097, 65535, 65536, 65537, 300 * 1024)
LEVELS = ("best", "fast")
KINDS = ("random", "zeros", "text", "structured")
HEADER_MAX = 16
_PANGGRAM = b"The quick brown fox jumps over the lazy dog. "


def _hp_error():
    try:
        from hyperpress import HyperPressError
    except ImportError:
        pytest.fail("hyperpress.HyperPressError is not exported")
    return HyperPressError


def _format_version():
    try:
        from hyperpress import FORMAT_VERSION
    except ImportError:
        pytest.fail("hyperpress.FORMAT_VERSION is not exported")
    return FORMAT_VERSION


def _uvarint(n):
    if n < 0:
        raise ValueError("unsigned varint")
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _read_uvarint(buf, offset):
    n = 0
    shift = 0
    i = offset
    while True:
        if i >= len(buf):
            raise AssertionError("truncated LEB128 at offset %d" % offset)
        byte = buf[i]
        i += 1
        n |= (byte & 0x7F) << shift
        if byte & 0x80 == 0:
            return n, i
        shift += 7
        if shift > 63:
            raise AssertionError("LEB128 too long")


def _random_bytes(n, seed):
    rng = random.Random(seed)
    buf = bytearray(n)
    i = 0
    while i + 4 <= n:
        struct.pack_into("<I", buf, i, rng.getrandbits(32))
        i += 4
    while i < n:
        buf[i] = rng.getrandbits(8)
        i += 1
    return bytes(buf)


def _text_bytes(n):
    if n == 0:
        return b""
    return (_PANGGRAM * (n // len(_PANGGRAM) + 1))[:n]


def _structured_bytes(n):
    if n == 0:
        return b""
    out = bytearray()
    i = 0
    while len(out) < n:
        out.extend(struct.pack("<IHffH", i, i & 0xFFFF, float(i % 1000), float((i * 3) % 500), 0xABCD))
        i += 1
    return bytes(out[:n])


def _make(kind, size):
    if kind == "random":
        return _random_bytes(size, seed=0xC0FFEE ^ size)
    if kind == "zeros":
        return b"\x00" * size
    if kind == "text":
        return _text_bytes(size)
    if kind == "structured":
        return _structured_bytes(size)
    raise ValueError("unknown kind %r" % (kind,))


def _parse_v2_prefix(blob):
    assert len(blob) >= 4, "stream shorter than magic"
    assert blob[:4] == b"HPRX", "magic %r" % (blob[:4],)
    assert len(blob) >= 6, "stream shorter than magic+version+mode"
    version = blob[4]
    mode = blob[5]
    size, i = _read_uvarint(blob, 6)
    assert i + 4 <= len(blob), "stream truncated in crc32"
    crc = struct.unpack_from("<I", blob, i)[0]
    i += 4
    return version, mode, size, crc, i


def _xz_raw_9e(data):
    return lzma.compress(
        data,
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}],
    )


def _opponent_min_len(data):
    sizes = [len(_xz_raw_9e(data)), len(bz2.compress(data, 9))]
    try:
        from compression import zstd
    except ImportError:
        zstd = None
    if zstd is not None:
        sizes.append(len(zstd.compress(data, level=19)))
    return min(sizes)


class TestPublicAPI:
    def test_format_version_is_2(self):
        assert _format_version() == 2

    def test_hyperpress_error_is_valueerror(self):
        err = _hp_error()
        assert issubclass(err, ValueError)
        from hyperpress import HyperPressError
        assert HyperPressError is err

    def test_compress_default_matches_best(self):
        data = _text_bytes(2048)
        assert compress(data) == compress(data, level="best")

    def test_compress_decompress_return_bytes(self):
        data = b"api-types"
        out = compress(data, level="fast")
        assert type(out) is bytes
        assert type(decompress(out)) is bytes


class TestRoundtrip:
    @pytest.mark.parametrize("level", LEVELS)
    @pytest.mark.parametrize("kind", KINDS)
    @pytest.mark.parametrize("size", EDGE_SIZES)
    def test_roundtrip_edge_sizes(self, size, kind, level):
        data = _make(kind, size)
        assert decompress(compress(data, level=level)) == data


class TestDeterminism:
    @pytest.mark.parametrize("level", LEVELS)
    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"\x00",
            _text_bytes(4096),
            _structured_bytes(8192),
            _random_bytes(1024, seed=7),
            b"\x00" * 65536,
        ],
        ids=["empty", "one-zero", "text-4k", "struct-8k", "rand-1k", "zeros-64k"],
    )
    def test_same_input_same_bytes(self, level, data):
        a = compress(data, level=level)
        b = compress(data, level=level)
        assert a == b
        assert decompress(a) == data


class TestHeader:
    def test_empty_is_whole_stored(self):
        blob = compress(b"", level="best")
        version, mode, size, crc, i = _parse_v2_prefix(blob)
        assert version == 2
        assert version == _format_version()
        assert mode == 0
        assert size == 0
        assert crc == 0
        assert i < len(blob)
        method = blob[i]
        assert method == 0
        assert blob[i + 1 :] == b""
        assert _uvarint(0) == blob[6:7]

    @pytest.mark.parametrize("size", [0, 1, 2, 3, 127, 128, 4095, 4096, 4097, 65535, 65536, 65537, 300 * 1024])
    def test_header_bytes(self, size):
        data = b"\x00" * size
        blob = compress(data, level="best")
        version, mode, size_field, crc, i = _parse_v2_prefix(blob)
        assert blob[:4] == b"HPRX"
        assert version == 2
        assert mode in (0, 1)
        assert size_field == size
        assert crc == (zlib.crc32(data) & 0xFFFFFFFF)
        varint = _uvarint(size)
        assert blob[6:6 + len(varint)] == varint
        if mode == 0:
            assert i < len(blob)
            method = blob[i]
            assert 0 <= method <= 13
            if size == 0:
                assert method == 0
                assert i + 1 == len(blob)

    def test_header_crc_covers_original_not_payload(self):
        data = _text_bytes(2048)
        blob = compress(data, level="best")
        _version, _mode, size_field, crc, _i = _parse_v2_prefix(blob)
        assert size_field == len(data)
        assert crc == (zlib.crc32(data) & 0xFFFFFFFF)


class TestSizeGuarantee:
    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"\x00",
            b"x",
            _text_bytes(200),
            _text_bytes(8192),
            b"\x00" * 4096,
            b"\x00" * 65536,
            _structured_bytes(8192),
            _random_bytes(4096, seed=99),
            _text_bytes(300 * 1024)[: 50 * 1024],
        ],
        ids=[
            "empty",
            "zero",
            "x",
            "text-200",
            "text-8k",
            "zeros-4k",
            "zeros-64k",
            "struct-8k",
            "rand-4k",
            "text-50k",
        ],
    )
    def test_not_worse_than_opponents_plus_header(self, data):
        out = compress(data, level="best")
        cap = _opponent_min_len(data) + HEADER_MAX
        assert len(out) <= cap, "len(compress)=%d opponent_min+16=%d" % (len(out), cap)


def test_fast_level_never_expands_incompressible_data_beyond_header():
    # Regression: "fast" lacked STORED and grew random data by 21 bytes.
    data = os.urandom(100000)
    assert len(compress(data, level="fast")) <= len(data) + 16
