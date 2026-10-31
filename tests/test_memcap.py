"""SPEC v2.1 memory cap: peak allocation <= max_output_size + 64 KiB
(2 * max_output_size + 64 KiB on LZMA paths, which need a dictionary).

Crafted BLOCKS and v1 streams whose codecs would expand far past a 100 KiB
cap. Peak is tracemalloc after the input blob exists, so the input itself
is not counted. Strict peaks are asserted only on paths that raise.
"""

import bz2
import gc
import lzma
import signal
import struct
import tracemalloc
import zlib

import pytest

from hyperpress import HyperPressError, decompress
from hyperpress.core import (
    Backend,
    PreProc,
    _lzma_filters,
    bwt_mtf_enc,
    delta16_enc,
    delta_enc,
    nibble_dec,
    nibble_enc,
    rle_enc,
    transpose_enc,
)


CAP = 100 * 1024
BUDGET = CAP + 64 * 1024
# LZMA needs a dictionary as large as the decoded stream next to the output.
LZMA_BUDGET = 2 * CAP + 64 * 1024


def _uvarint(n):
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def _v2_blocks(osz, pp, be, payload, size=None, crc=0):
    if size is None:
        size = osz
    body = (
        _uvarint(1)
        + _uvarint(osz)
        + _uvarint(len(payload))
        + bytes((int(pp), int(be)))
        + payload
    )
    return b"HPRX" + bytes((2, 1)) + _uvarint(size) + struct.pack("<I", crc) + body


def _v1_block(osz, pp, be, payload, size=None, crc=0):
    if size is None:
        size = osz
    header = struct.pack("<4sBBHQ", b"HPRX", 1, 1, 1, size)
    block = struct.pack("<IIBBI", osz, len(payload), int(pp), int(be), crc)
    return header + block + payload


def _v2_whole(size, method, payload, crc=0):
    return (
        b"HPRX"
        + bytes((2, 0))
        + _uvarint(size)
        + struct.pack("<I", crc)
        + bytes((method,))
        + payload
    )


def _peak_raises(blob, budget=BUDGET):
    gc.collect()
    tracemalloc.start()
    try:
        with pytest.raises(HyperPressError):
            decompress(blob, max_output_size=CAP)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak <= budget, "peak %d > budget %d" % (peak, budget)
    return peak


def _zlib_bomb(n):
    return zlib.compress(b"\x00" * n, 9)


def test_v2_nibble_zlib_bomb_within_budget():
    # Backend expands to 4*osz; the nibble cap used to buffer 2*osz.
    payload = _zlib_bomb(4 * CAP)
    _peak_raises(_v2_blocks(CAP, PreProc.NIBBLE, Backend.ZLIB9, payload))


def test_v1_nibble_zlib_bomb_within_budget():
    payload = _zlib_bomb(4 * CAP)
    _peak_raises(_v1_block(CAP, PreProc.NIBBLE, Backend.ZLIB9, payload))


def test_v2_rle_zlib_bomb_within_budget():
    payload = zlib.compress(b"\x01" * (4 * CAP), 9)
    _peak_raises(_v2_blocks(CAP, PreProc.RLE, Backend.ZLIB9, payload))


def test_v1_rle_zlib_bomb_within_budget():
    payload = zlib.compress(b"\x01" * (4 * CAP), 9)
    _peak_raises(_v1_block(CAP, PreProc.RLE, Backend.ZLIB9, payload))


def test_v2_zlib_lzma_bomb_within_budget():
    # Raw LZMA2 of zeros, larger than osz + 64 KiB. Default dict is 8 MiB.
    raw = b"\x00" * (CAP + 65536 + 50000)
    payload = lzma.compress(
        raw, format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 0}],
    )
    _peak_raises(_v2_blocks(CAP, PreProc.NONE, Backend.ZLIB_LZMA, payload), LZMA_BUDGET)


def test_v1_zlib_lzma_bomb_within_budget():
    raw = b"\x00" * (CAP + 65536 + 50000)
    payload = lzma.compress(
        raw, format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 0}],
    )
    _peak_raises(_v1_block(CAP, PreProc.NONE, Backend.ZLIB_LZMA, payload), LZMA_BUDGET)


def test_v2_stored_payload_not_sliced():
    payload = b"Z" * (2 * 1024 * 1024)
    _peak_raises(_v2_blocks(CAP, PreProc.NONE, Backend.STORED, payload))


def test_v1_stored_payload_not_sliced():
    payload = b"Z" * (2 * 1024 * 1024)
    _peak_raises(_v1_block(CAP, PreProc.NONE, Backend.STORED, payload))


def test_v2_bwt_index_not_allocated_past_budget():
    # osz+4 zeros decode, then the inverse BWT index is ~4 bytes * osz.
    payload = _zlib_bomb(CAP + 4)
    _peak_raises(_v2_blocks(CAP, PreProc.BWT_MTF, Backend.ZLIB9, payload))


def test_v2_whole_raw_zlib_bomb_within_budget():
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    chunk = b"\x00" * (256 * 1024)
    parts = []
    left = 8 * 1024 * 1024
    while left:
        take = min(left, len(chunk))
        parts.append(comp.compress(chunk[:take]))
        left -= take
    parts.append(comp.flush())
    _peak_raises(_v2_whole(CAP, 11, b"".join(parts)))


def test_v2_whole_lzma_bomb_within_budget():
    filters = _lzma_filters(1, CAP)
    payload = lzma.compress(
        b"\x00" * (CAP + 65536), format=lzma.FORMAT_RAW, filters=filters,
    )
    _peak_raises(_v2_whole(CAP, 1, payload), LZMA_BUDGET)


def test_v2_whole_text_bz2_bomb_within_budget():
    # TEXT inner stream may exceed size, but never max_output_size + slack.
    payload = bz2.compress(b"HPt" + b"\x00" * (4 * 1024 * 1024), 9)
    _peak_raises(_v2_whole(CAP, 14, payload))


def test_v2_whole_text_lzma_bomb_within_budget():
    payload = lzma.compress(
        b"HPt" + b"\x00" * (4 * 1024 * 1024), format=lzma.FORMAT_RAW,
        filters=_lzma_filters(15, CAP),
    )
    _peak_raises(_v2_whole(CAP, 15, payload), LZMA_BUDGET)


def test_zlib_trailing_tail_does_not_hang():
    """CPython zlib leaves unconsumed_tail set at eof (issue 158169).

    Feeding that tail back forever grows unused_data. A block-sized stream
    plus a trailer must raise, and must do so without spinning.
    """
    source = b"\x00" * CAP
    payload = zlib.compress(source, 9) + b"extra"
    blob = _v2_blocks(CAP, PreProc.NONE, Backend.ZLIB9, payload)

    def _alarm(signum, frame):
        raise TimeoutError("bounded decode hung")

    old = signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, 2.0)
    try:
        _peak_raises(blob)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, old)


def _pack(data, pp, be, version):
    if pp == PreProc.NIBBLE:
        pre = nibble_enc(data)
    elif pp == PreProc.RLE:
        pre = rle_enc(data)
    elif pp == PreProc.DELTA:
        pre = delta_enc(data)
    elif pp == PreProc.DELTA16:
        pre = delta16_enc(data)
    elif pp == PreProc.TRANSPOSE:
        pre = transpose_enc(data)
    elif pp == PreProc.BWT_MTF:
        pre = bwt_mtf_enc(data)
    else:
        pre = data
    if be == Backend.ZLIB9:
        payload = zlib.compress(pre, 9)
    elif be == Backend.LZMA:
        payload = lzma.compress(
            pre, format=lzma.FORMAT_RAW,
            filters=[{
                "id": lzma.FILTER_LZMA2,
                "preset": 9 | lzma.PRESET_EXTREME,
                "dict_size": max(4096, min(len(pre) * 2, 8 * 1024 * 1024)),
            }],
        )
    elif be == Backend.BZ2:
        import bz2
        payload = bz2.compress(pre, 9)
    elif be == Backend.ZLIB_LZMA:
        inner = zlib.compress(pre, 1)
        payload = lzma.compress(
            inner, format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}],
        )
    else:
        payload = pre
    crc = zlib.crc32(data) & 0xFFFFFFFF
    if version == 1:
        return _v1_block(len(data), pp, be, payload, crc=crc)
    return _v2_blocks(len(data), pp, be, payload, crc=crc)


@pytest.mark.parametrize("version", (2, 1))
@pytest.mark.parametrize(
    "pp,be",
    [
        (PreProc.NONE, Backend.ZLIB9),
        (PreProc.NONE, Backend.LZMA),
        (PreProc.NONE, Backend.BZ2),
        (PreProc.NONE, Backend.ZLIB_LZMA),
        (PreProc.NONE, Backend.STORED),
        (PreProc.DELTA, Backend.ZLIB9),
        (PreProc.DELTA16, Backend.ZLIB9),
        (PreProc.RLE, Backend.ZLIB9),
        (PreProc.TRANSPOSE, Backend.ZLIB9),
        (PreProc.NIBBLE, Backend.ZLIB9),
        (PreProc.NIBBLE, Backend.STORED),
        (PreProc.BWT_MTF, Backend.ZLIB9),
    ],
)
def test_small_block_roundtrip(version, pp, be):
    data = bytes((i * 17 + 3) & 0xFF for i in range(64))
    assert decompress(_pack(data, pp, be, version)) == data


def test_bwt_8192_roundtrip():
    data = (b"abracadabra " * 700)[:8192]
    blob = _pack(data, PreProc.BWT_MTF, Backend.ZLIB9, 2)
    assert decompress(blob) == data


def test_nibble_100k_roundtrip_default_cap():
    data = bytes(i & 0xFF for i in range(CAP))
    blob = _pack(data, PreProc.NIBBLE, Backend.ZLIB9, 2)
    assert decompress(blob, max_output_size=CAP) == data


def test_rle_100k_roundtrip_default_cap():
    data = b"\x00" * (CAP - 50) + b"\x01" * 50
    blob = _pack(data, PreProc.RLE, Backend.LZMA, 2)
    assert decompress(blob, max_output_size=CAP) == data


def test_hostile_nibble_matches_reference():
    raw = bytes([0x1F, 0x00, 0x0A, 0x10, 0x0B, 0x01, 0xFF, 0x02])
    try:
        expected = nibble_dec(raw)
    except ValueError:
        blob = _v2_blocks(4, PreProc.NIBBLE, Backend.STORED, raw)
        with pytest.raises(HyperPressError):
            decompress(blob)
        return
    crc = zlib.crc32(expected) & 0xFFFFFFFF
    blob = _v2_blocks(4, PreProc.NIBBLE, Backend.STORED, raw, crc=crc)
    assert decompress(blob) == expected


def test_rle_zero_run_past_osz_is_invalid():
    # One zero-run longer than osz. Backend is stored, so no extra buffer.
    payload = bytes([0, 10])
    blob = _v2_blocks(4, PreProc.RLE, Backend.STORED, payload)
    with pytest.raises(HyperPressError):
        decompress(blob)


@pytest.mark.parametrize("level", ["best", "fast"])
@pytest.mark.parametrize("kind", ["text", "binary", "zeros", "random", "far"])
def test_valid_stream_decodes_at_exact_limit(level, kind):
    """The cap must never break a valid stream (dictionary shrink did)."""
    import os
    import random
    rnd = random.Random(7)
    words = [b"alpha", b"beta", b"gamma", b"delta", b"omega", b"Theta"]
    data = {
        "text": b" ".join(rnd.choice(words) for _ in range(30000)) + b"\n",
        "binary": bytes(rnd.randrange(16) * 17 for _ in range(150000)),
        "zeros": bytes(70000),
        "random": os.urandom(5000),
        # Matches 40 KiB back: needs a dictionary of about the stream size.
        "far": bytes(rnd.randrange(256) for _ in range(40000)) * 3,
    }[kind]
    from hyperpress import compress
    assert decompress(compress(data, level=level), max_output_size=len(data)) == data


class _DrainThenNeedInput:
    """Codec that drains its buffer to nothing once, then wants more input.

    liblzma does this on real data (Silesia mozilla) at buffer boundaries.
    """

    def __init__(self, data):
        self.data = data
        self.eof = False
        self.needs_input = True
        self.fed = 0
        self.drained = False

    def decompress(self, chunk, max_length):
        self.fed += len(chunk)
        if chunk and not self.drained:
            self.needs_input = False
            return b""
        if not chunk and not self.needs_input:
            self.drained = True
            self.needs_input = True
            return b""
        if self.fed >= len(self.data):
            self.eof = True
            self.needs_input = False
        return self.data[:0] if not chunk else chunk[:max_length]


def test_empty_drain_with_input_left_is_not_truncation():
    from hyperpress.core import _PullDecoder
    payload = b"x" * 10000
    dec = _PullDecoder(payload, "bz2", 1 << 20, 1 << 20)
    dec.obj = _DrainThenNeedInput(payload)
    out = bytearray()
    while True:
        part = dec.read(4096)
        if not part:
            break
        out += part
    assert len(out) > 0


def test_text_crlf_newline_bomb_within_budget():
    # Hostile CRLF stream of newlines: size check must run before replace().
    n = 1024 * 1024
    inner = b"HPt" + bytes((2, 2)) + _uvarint(0) + b"\n" * (n - 16)
    blob = _v2_whole(n, 14, bz2.compress(inner, 9))
    del inner
    gc.collect()
    tracemalloc.start()
    try:
        with pytest.raises(HyperPressError):
            decompress(blob, max_output_size=n)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # TEXT holds the inner stream and the growing output (bytearray slack).
    assert peak <= 2.25 * n + 64 * 1024, peak


@pytest.mark.parametrize("preset", range(10))
def test_fit_keeps_preset_dictionary_for_large_streams(preset):
    # A missing dict_size used to mean 8 MiB; preset 9 is 64 MiB, so xz
    # streams above 8 MiB failed with "Corrupt input data" (Silesia mozilla).
    from hyperpress.core import _fit_lzma_filters
    props = lzma._encode_filter_properties({"id": lzma.FILTER_LZMA2, "preset": preset})
    real = lzma._decode_filter_properties(lzma.FILTER_LZMA2, props)["dict_size"]
    filters = [{"id": lzma.FILTER_LZMA2, "preset": preset | lzma.PRESET_EXTREME}]
    assert _fit_lzma_filters(filters, 1 << 30)[0]["dict_size"] == real
    assert _fit_lzma_filters(filters, 5000)[0]["dict_size"] == min(real, 5000)
