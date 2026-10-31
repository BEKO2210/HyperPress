"""SPEC-v2 robustness tests against the public API only.

Corrupt, truncated, oversize and legacy-v1 streams must raise HyperPressError
(even under python -O). A 200 MiB zeros WHOLE-xz payload must not allocate
beyond max_output_size.
"""

import binascii
import gc
import lzma
import os
import struct
import subprocess
import sys
import time
import tracemalloc
import zlib

import pytest

from hyperpress import compress, decompress


_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))


def _hp_error():
    try:
        from hyperpress import HyperPressError
    except ImportError:
        pytest.fail("hyperpress.HyperPressError is not exported")
    return HyperPressError


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


def _v2_whole(orig, method, payload, crc=None):
    """Hand-built v2 WHOLE stream (SPEC layout)."""
    if crc is None:
        crc = zlib.crc32(orig) & 0xFFFFFFFF
    return (
        b"HPRX"
        + bytes([2, 0])
        + _uvarint(len(orig))
        + struct.pack("<I", crc)
        + bytes([method & 0xFF])
        + payload
    )


def _must_raise_hp(data, label, max_output_size=None):
    HyperPressError = _hp_error()
    try:
        if max_output_size is None:
            decompress(data)
        else:
            decompress(data, max_output_size=max_output_size)
    except HyperPressError:
        return
    except Exception as e:
        pytest.fail(
            "%s: expected HyperPressError, got %s: %r" % (label, type(e).__name__, e)
        )
    pytest.fail("%s: expected HyperPressError, decompressor succeeded" % label)


def _small_stream():
    return compress(b"HyperPress robustness payload\n" * 3, level="best")


def _clamp(n, lo, hi):
    return max(lo, min(hi, n))


def _method1_payload_zeros(n, chunk=1024 * 1024):
    """LZMA2 method-1 payload of n zero bytes, without holding n in RAM."""
    dict_size = _clamp(2 * n, 4 * 1024, 64 * 1024 * 1024)
    filters = [{
        "id": lzma.FILTER_LZMA2,
        "preset": 9 | lzma.PRESET_EXTREME,
        "dict_size": dict_size,
        "lc": 3,
        "lp": 0,
        "pb": 2,
    }]
    compressor = lzma.LZMACompressor(format=lzma.FORMAT_RAW, filters=filters)
    parts = []
    crc = 0
    remaining = n
    zeros = b"\x00" * min(chunk, n)
    while remaining:
        block = zeros if remaining >= len(zeros) else b"\x00" * remaining
        crc = zlib.crc32(block, crc)
        parts.append(compressor.compress(block))
        remaining -= len(block)
    parts.append(compressor.flush())
    return b"".join(parts), crc & 0xFFFFFFFF


_OPT_SCRIPT = r"""
import os, sys, binascii
src = os.environ.get("HP_SRC", "")
if src:
    sys.path.insert(0, src)
if __debug__:
    sys.stderr.write("python -O did not disable __debug__\n")
    sys.exit(2)
from hyperpress import decompress, HyperPressError

blob = binascii.unhexlify(sys.argv[1])
bad = []

def check(data, label):
    try:
        decompress(data)
    except HyperPressError:
        return
    except Exception as e:
        bad.append("%s: %s: %r" % (label, type(e).__name__, e))
        return
    bad.append("%s: no error" % label)

for i in range(len(blob)):
    b = bytearray(blob)
    b[i] ^= 0xFF
    check(bytes(b), "xor[%d]" % i)
for n in range(len(blob)):
    check(blob[:n], "trunc[%d]" % n)
check(blob + b"\x00", "trailing-00")
check(blob + b"GARBAGE", "trailing-garbage")
check(b"HPRX" + bytes([99, 0, 0]) + b"\x00\x00\x00\x00" + b"\x00", "ver-99")
check(b"HPRX" + bytes([2, 99, 0]) + b"\x00\x00\x00\x00" + b"\x00", "mode-99")
check(b"HPRX" + bytes([2, 0, 0]) + b"\x00\x00\x00\x00" + bytes([255]), "method-255")
if bad:
    sys.stderr.write("\n".join(bad) + "\n")
    sys.exit(1)
"""


class TestCorruption:
    def test_each_byte_xor_raises_hyperpress_error(self):
        blob = _small_stream()
        assert len(blob) >= 12
        for i in range(len(blob)):
            mutated = bytearray(blob)
            mutated[i] ^= 0xFF
            _must_raise_hp(bytes(mutated), "xor byte %d/%d" % (i, len(blob)))

    def test_truncation_at_every_length_raises(self):
        blob = _small_stream()
        for n in range(len(blob)):
            _must_raise_hp(blob[:n], "truncated to %d of %d" % (n, len(blob)))

    def test_trailing_garbage_raises(self):
        blob = _small_stream()
        _must_raise_hp(blob + b"\x00", "trailing 0x00")
        _must_raise_hp(blob + b"\xff", "trailing 0xff")
        _must_raise_hp(blob + b"GARBAGE", "trailing GARBAGE")
        _must_raise_hp(blob + blob, "trailing second stream")

    def test_empty_input_raises(self):
        _must_raise_hp(b"", "empty buffer")


class TestUnknownFields:
    def test_unknown_version_raises(self):
        orig = b"x"
        payload = orig
        crc = struct.pack("<I", zlib.crc32(orig) & 0xFFFFFFFF)
        for ver in (0, 3, 4, 99, 255):
            blob = b"HPRX" + bytes([ver, 0]) + _uvarint(len(orig)) + crc + bytes([0]) + payload
            _must_raise_hp(blob, "version %d" % ver)

    def test_unknown_mode_raises(self):
        orig = b"x"
        payload = orig
        crc = struct.pack("<I", zlib.crc32(orig) & 0xFFFFFFFF)
        for mode in (2, 3, 99, 255):
            blob = b"HPRX" + bytes([2, mode]) + _uvarint(len(orig)) + crc + bytes([0]) + payload
            _must_raise_hp(blob, "mode %d" % mode)

    def test_unknown_method_raises(self):
        orig = b"hello"
        payload = orig
        for method in (14, 15, 99, 200, 255):
            blob = _v2_whole(orig, method, payload)
            _must_raise_hp(blob, "method %d" % method)

    def test_wrong_crc_raises(self):
        orig = b"hello"
        blob = _v2_whole(orig, 0, orig, crc=(zlib.crc32(orig) ^ 0xFFFFFFFF) & 0xFFFFFFFF)
        _must_raise_hp(blob, "wrong crc")

    def test_bad_magic_raises(self):
        blob = _small_stream()
        _must_raise_hp(b"XXXX" + blob[4:], "bad magic XXXX")
        _must_raise_hp(b"HPRY" + blob[4:], "bad magic HPRY")


class TestOptimizedMode:
    def test_corruption_under_python_dash_o(self):
        blob = _small_stream()
        env = os.environ.copy()
        env["HP_SRC"] = _SRC
        env["PYTHONPATH"] = _SRC + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONOPTIMIZE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-O", "-c", _OPT_SCRIPT, binascii.hexlify(blob).decode("ascii")],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        assert proc.returncode != 2, "subprocess was not running with -O"
        assert proc.returncode == 0, "python -O corruption check failed:\n%s\n%s" % (
            proc.stdout,
            proc.stderr,
        )


class TestMaxOutputSize:
    def test_declared_size_bomb_raises_quickly(self):
        huge = 10 ** 9
        blob = (
            b"HPRX"
            + bytes([2, 0])
            + _uvarint(huge)
            + struct.pack("<I", 0)
            + bytes([0])
        )
        gc.collect()
        t0 = time.perf_counter()
        tracemalloc.start()
        try:
            _must_raise_hp(blob, "declared-size bomb", max_output_size=1024)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, "declared-size bomb took %.3fs" % elapsed
        assert peak < 100 * 1024 * 1024, "peak %d bytes" % peak

    def test_declared_size_just_over_cap_raises(self):
        orig = b"abc"
        blob = _v2_whole(orig, 0, orig)
        HyperPressError = _hp_error()
        assert decompress(blob, max_output_size=len(orig)) == orig
        with pytest.raises(HyperPressError):
            decompress(blob, max_output_size=len(orig) - 1)

    def test_method1_200mb_zeros_capped(self):
        _hp_error()
        n = 200 * 1024 * 1024
        payload, crc = _method1_payload_zeros(n)
        blob = (
            b"HPRX"
            + bytes([2, 0])
            + _uvarint(n)
            + struct.pack("<I", crc)
            + bytes([1])
            + payload
        )
        del payload
        gc.collect()
        cap = 64 * 1024
        t0 = time.perf_counter()
        tracemalloc.start()
        try:
            _must_raise_hp(blob, "200MiB zeros xz WHOLE", max_output_size=cap)
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        elapsed = time.perf_counter() - t0
        assert elapsed < 5.0, "200MiB zeros bomb took %.3fs" % elapsed
        assert peak < 100 * 1024 * 1024, "peak %d bytes" % peak


class TestV1Compat:
    def test_hand_built_v1_zlib9_block_decodes(self):
        orig = b"HyperPress v1 compatibility payload\n" * 20
        payload = zlib.compress(orig, 9)
        crc = zlib.crc32(orig) & 0xFFFFFFFF
        header = struct.pack("<4sBBHQ", b"HPRX", 1, 1, 1, len(orig))
        block = struct.pack("<IIBBI", len(orig), len(payload), 0, 0, crc)
        blob = header + block + payload
        assert decompress(blob) == orig

    def test_hand_built_v1_empty_decodes(self):
        blob = struct.pack("<4sBBHQ", b"HPRX", 1, 1, 0, 0)
        assert decompress(blob) == b""
