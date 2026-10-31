#!/usr/bin/env python3
"""
HyperPress v2 — Adaptive Meta-Compression Engine
Beats zlib-9 and LZMA-RAW through intelligent preprocessing + backend racing.

Copyright 2025 Belkis / BEL KI (AI Consultancy)
Licensed under the MIT License.
"""

import zlib
import lzma
import bz2
import struct
import math
from collections import Counter
from enum import IntEnum

MAGIC = b"HPRX"
FORMAT_VERSION = 2
VERSION = FORMAT_VERSION

try:
    from compression import zstd
    HAVE_ZSTD = True
except ImportError:
    zstd = None
    HAVE_ZSTD = False


class HyperPressError(ValueError):
    """Invalid, corrupt, truncated, or oversized HPRX stream."""



class PreProc(IntEnum):
    NONE = 0
    DELTA = 1
    DELTA16 = 2
    BWT_MTF = 3
    RLE = 4
    TRANSPOSE = 5
    NIBBLE = 6


class Backend(IntEnum):
    ZLIB9 = 0
    LZMA = 1
    BZ2 = 2
    ZLIB_LZMA = 3
    STORED = 4


# ── Preprocessing ─────────────────────────────────────────

def delta_enc(d):
    if len(d) < 2:
        return d
    o = bytearray(len(d))
    o[0] = d[0]
    for i in range(1, len(d)):
        o[i] = (d[i] - d[i - 1]) & 0xFF
    return bytes(o)


def delta_dec(d):
    if len(d) < 2:
        return d
    o = bytearray(len(d))
    o[0] = d[0]
    for i in range(1, len(d)):
        o[i] = (o[i - 1] + d[i]) & 0xFF
    return bytes(o)


def delta16_enc(d):
    if len(d) < 4 or len(d) % 2:
        return d
    o = bytearray(len(d))
    o[0] = d[0]
    o[1] = d[1]
    for i in range(2, len(d), 2):
        v = d[i] | (d[i + 1] << 8)
        p = d[i - 2] | (d[i - 1] << 8)
        df = (v - p) & 0xFFFF
        o[i] = df & 0xFF
        o[i + 1] = (df >> 8) & 0xFF
    return bytes(o)


def delta16_dec(d):
    if len(d) < 4 or len(d) % 2:
        return d
    o = bytearray(len(d))
    o[0] = d[0]
    o[1] = d[1]
    for i in range(2, len(d), 2):
        df = d[i] | (d[i + 1] << 8)
        p = o[i - 2] | (o[i - 1] << 8)
        v = (p + df) & 0xFFFF
        o[i] = v & 0xFF
        o[i + 1] = (v >> 8) & 0xFF
    return bytes(o)


def bwt_enc(d):
    n = len(d)
    if n == 0:
        return b"", 0
    indices = sorted(range(n), key=lambda i: d[i:] + d[:i])
    pi = indices.index(0)
    return bytes(d[(i - 1) % n] for i in indices), pi


def bwt_dec(d, pi):
    n = len(d)
    if n == 0:
        return b""
    count = [0] * 256
    for b in d:
        count[b] += 1
    cum = [0] * 256
    s = 0
    for i in range(256):
        cum[i] = s
        s += count[i]
    T = [0] * n
    for i in range(n):
        T[cum[d[i]]] = i
        cum[d[i]] += 1
    o = bytearray(n)
    idx = T[pi]
    for i in range(n):
        o[i] = d[idx]
        idx = T[idx]
    return bytes(o)


def mtf_enc(d):
    a = list(range(256))
    o = bytearray(len(d))
    for i, b in enumerate(d):
        idx = a.index(b)
        o[i] = idx
        if idx > 0:
            a.pop(idx)
            a.insert(0, b)
    return bytes(o)


def mtf_dec(d):
    a = list(range(256))
    o = bytearray(len(d))
    for i, idx in enumerate(d):
        b = a[idx]
        o[i] = b
        if idx > 0:
            a.pop(idx)
            a.insert(0, b)
    return bytes(o)


def bwt_mtf_enc(d):
    bd, pi = bwt_enc(d)
    md = mtf_enc(bd)
    return struct.pack("<I", pi) + md


def bwt_mtf_dec(d):
    pi = struct.unpack("<I", d[:4])[0]
    return bwt_dec(mtf_dec(d[4:]), pi)


def rle_enc(d):
    if not d:
        return b""
    o = bytearray()
    i = 0
    n = len(d)
    while i < n:
        if d[i] == 0:
            r = 0
            while i < n and d[i] == 0 and r < 255:
                r += 1
                i += 1
            o.append(0)
            o.append(r)
        else:
            o.append(d[i])
            i += 1
    return bytes(o)


def rle_dec(d):
    if not d:
        return b""
    o = bytearray()
    i = 0
    n = len(d)
    while i < n:
        if d[i] == 0 and i + 1 < n:
            o.extend(b"\x00" * d[i + 1])
            i += 2
        else:
            o.append(d[i])
            i += 1
    return bytes(o)


def nibble_enc(d):
    n = len(d)
    h = bytearray(n)
    l = bytearray(n)
    for i in range(n):
        h[i] = (d[i] >> 4) & 0x0F
        l[i] = d[i] & 0x0F
    return bytes(h) + bytes(l)


def nibble_dec(d):
    n = len(d) // 2
    o = bytearray(n)
    for i in range(n):
        o[i] = (d[i] << 4) | d[n + i]
    return bytes(o)


def transpose_enc(d, stride=4):
    n = len(d)
    if n < stride:
        return d
    rows = n // stride
    o = bytearray()
    for c in range(stride):
        for r in range(rows):
            o.append(d[r * stride + c])
    o.extend(d[rows * stride:])
    return struct.pack("<B", stride) + bytes(o)


def transpose_dec(d):
    stride = d[0]
    d = d[1:]
    n = len(d)
    rows = n // stride
    main = rows * stride
    o = bytearray(main)
    for c in range(stride):
        for r in range(rows):
            o[r * stride + c] = d[c * rows + r]
    o.extend(d[main:])
    return bytes(o)


PREPROC_ENC = {
    PreProc.NONE: lambda d: d,
    PreProc.DELTA: delta_enc,
    PreProc.DELTA16: delta16_enc,
    PreProc.BWT_MTF: bwt_mtf_enc,
    PreProc.RLE: rle_enc,
    PreProc.TRANSPOSE: transpose_enc,
    PreProc.NIBBLE: nibble_enc,
}

PREPROC_DEC = {
    PreProc.NONE: lambda d: d,
    PreProc.DELTA: delta_dec,
    PreProc.DELTA16: delta16_dec,
    PreProc.BWT_MTF: bwt_mtf_dec,
    PreProc.RLE: rle_dec,
    PreProc.TRANSPOSE: transpose_dec,
    PreProc.NIBBLE: nibble_dec,
}


# ── Backends ──────────────────────────────────────────────

def comp_backend(d, b):
    if b == Backend.ZLIB9:
        return zlib.compress(d, 9)
    if b == Backend.LZMA:
        return lzma.compress(
            d, format=lzma.FORMAT_RAW,
            filters=[{
                "id": lzma.FILTER_LZMA2,
                "preset": 9 | lzma.PRESET_EXTREME,
                "dict_size": min(len(d) * 2, 8 * 1024 * 1024),
            }],
        )
    if b == Backend.BZ2:
        return bz2.compress(d, 9)
    if b == Backend.ZLIB_LZMA:
        s1 = zlib.compress(d, 1)
        return lzma.compress(
            s1, format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}],
        )
    if b == Backend.STORED:
        return d
    raise ValueError("Unknown backend: %s" % b)


def decomp_backend(d, b, sz):
    if b == Backend.ZLIB9:
        return zlib.decompress(d)
    if b == Backend.LZMA:
        return lzma.decompress(
            d, format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA2}],
        )
    if b == Backend.BZ2:
        return bz2.decompress(d)
    if b == Backend.ZLIB_LZMA:
        s1 = lzma.decompress(
            d, format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_LZMA2}],
        )
        return zlib.decompress(s1)
    if b == Backend.STORED:
        return d
    raise ValueError("Unknown backend: %s" % b)


# ── Analysis ──────────────────────────────────────────────

def entropy(d):
    if not d:
        return 0.0
    n = len(d)
    c = Counter(d)
    e = 0.0
    for v in c.values():
        p = v / n
        if p > 0:
            e -= p * math.log2(p)
    return e


def analyze(d):
    n = len(d)
    if n == 0:
        return {}
    c = Counter(d)
    ent = entropy(d)
    de = entropy(delta_enc(d)) if n > 1 else ent
    zr = c.get(0, 0) / n
    txt = sum(1 for b in d if 32 <= b <= 126 or b in (9, 10, 13)) / n > 0.85
    struct_ = False
    if n >= 32:
        for s in (2, 4, 8):
            m = sum(1 for i in range(s, min(n, 256)) if d[i] == d[i - s])
            if m / min(n - s, 256 - s) > 0.3:
                struct_ = True
                break
    return {
        "ent": ent,
        "de": de,
        "zr": zr,
        "txt": txt,
        "struct": struct_,
        "uniq": len(c),
    }


# ── Candidate Selection ───────────────────────────────────

def candidates(prof, dlen):
    c = set()
    c.add((PreProc.NONE, Backend.LZMA))
    c.add((PreProc.NONE, Backend.ZLIB9))
    c.add((PreProc.NONE, Backend.BZ2))

    if prof["ent"] > 7.5:
        c.add((PreProc.NIBBLE, Backend.LZMA))
        c.add((PreProc.DELTA, Backend.LZMA))
        if prof["ent"] > 7.9:
            c.add((PreProc.NONE, Backend.STORED))

    if prof["de"] < prof["ent"] - 0.3:
        c.add((PreProc.DELTA, Backend.ZLIB9))
        c.add((PreProc.DELTA, Backend.LZMA))
        c.add((PreProc.DELTA, Backend.BZ2))
        c.add((PreProc.DELTA16, Backend.LZMA))

    if prof["txt"] and dlen <= 8192:
        c.add((PreProc.BWT_MTF, Backend.ZLIB9))
        c.add((PreProc.BWT_MTF, Backend.LZMA))
        c.add((PreProc.BWT_MTF, Backend.BZ2))

    if prof["zr"] > 0.15:
        c.add((PreProc.RLE, Backend.LZMA))
        c.add((PreProc.RLE, Backend.ZLIB9))

    if prof["struct"]:
        c.add((PreProc.TRANSPOSE, Backend.ZLIB9))
        c.add((PreProc.TRANSPOSE, Backend.LZMA))

    if 4.0 < prof["ent"] < 7.0:
        c.add((PreProc.NONE, Backend.ZLIB_LZMA))
        c.add((PreProc.DELTA, Backend.ZLIB_LZMA))

    return list(c)


# ── Block Compression ─────────────────────────────────────

def compress_block(data):
    if not data:
        return b"", 0, PreProc.NONE, Backend.STORED, 0
    prof = analyze(data)
    cands = candidates(prof, len(data))
    best_d = None
    best_pp = PreProc.NONE
    best_be = Backend.STORED
    for pp, be in cands:
        try:
            pre = PREPROC_ENC[pp](data)
            comp = comp_backend(pre, be)
            if best_d is None or len(comp) < len(best_d):
                best_d = comp
                best_pp = pp
                best_be = be
        except Exception:
            pass
    if best_d is None or len(best_d) >= len(data):
        best_d = data
        best_pp = PreProc.NONE
        best_be = Backend.STORED
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return best_d, len(data), best_pp, best_be, crc


# ── Block Size Selection ──────────────────────────────────

def block_size(d):
    n = len(d)
    if n < 4096:
        return n
    if n < 65536:
        return min(n, 32768)
    ss = 1024
    ents = []
    for i in range(0, n - ss, max(n // 16, ss)):
        ents.append(entropy(d[i:i + ss]))
    if len(ents) > 1:
        m = sum(ents) / len(ents)
        v = sum((e - m) ** 2 for e in ents) / len(ents)
        if v > 1.0:
            return 32768
        if v > 0.3:
            return 65536
    return 131072


# ── Format ────────────────────────────────────────────────

HDR = "<4sBBHQ"  # Legacy v1 header.
BLK = "<IIBBI"  # Legacy v1 block header.


def _varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def _read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise HyperPressError("Truncated varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if value > (1 << 64) - 1:
                raise HyperPressError("Varint overflow")
            return value, offset
    raise HyperPressError("Varint overflow")


def _lzma_filters(method, size):
    preset = {12: 6, 16: 1}.get(method, 9 | lzma.PRESET_EXTREME)
    settings = {"id": lzma.FILTER_LZMA2, "preset": preset}
    if method == 1:
        settings["dict_size"] = max(4096, min(2 * size, 64 * 1024 * 1024))
    if method == 8:
        settings.update(lc=4, lp=0, pb=0)
    elif method == 9:
        settings.update(lc=0, lp=2, pb=2)
    elif method == 10:
        settings.update(lc=1, lp=0, pb=0)
    elif method == 15:
        settings.update(lc=4, lp=0, pb=0)
    if method in (4, 5, 6):
        return [{"id": lzma.FILTER_DELTA, "dist": {4: 1, 5: 2, 6: 4}[method]}, settings]
    if method == 7:
        return [{"id": lzma.FILTER_X86}, settings]
    return [settings]


def _looks_like_text(data):
    if len(data) < 32:
        return False
    sample = data[:8192] if len(data) > 8192 else data
    good = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
    if good * 100 // len(sample) < 85:
        return False
    return sample.count(0) == 0


def _whole_compress(data, method):
    if method == 0:
        return data
    if method in (1, 4, 5, 6, 7, 8, 9, 10, 12, 16):
        return lzma.compress(data, format=lzma.FORMAT_RAW,
                             filters=_lzma_filters(method, len(data)))
    if method == 2:
        return bz2.compress(data, compresslevel=9)
    if method in (3, 13):
        return zstd.compress(data, level=19 if method == 3 else 3)
    if method == 11:
        obj = zlib.compressobj(9, zlib.DEFLATED, -15)
        return obj.compress(data) + obj.flush()
    if method in (14, 15):
        from hyperpress.textxf import encode
        xf = encode(data)
        if len(xf) > len(data):
            # Decoder caps the inner stream at size to stay inside the budget.
            raise ValueError("TEXT transform expands input")
        if method == 14:
            return bz2.compress(xf, compresslevel=9)
        return lzma.compress(xf, format=lzma.FORMAT_RAW,
                             filters=_lzma_filters(method, len(data)))
    raise HyperPressError("Unknown method")


# Output is pulled in small pieces so a bomb cannot pin a 64 KiB chunk next
# to the capped buffer. LZMADecompressor(dict_size=N) traces about N + 34 KiB.
_CHUNK = 4 * 1024
_SLACK = 64 * 1024


# xz preset -> LZMA2 dictionary size (xz(1), stable across liblzma versions).
_PRESET_DICT = (256 << 10,) + tuple(n << 20 for n in (1, 2, 4, 4, 8, 8, 16, 32, 64))


def _fit_lzma_filters(filters, hold):
    """Size the LZMA2 dictionary to the decoded stream, never below it.

    A valid stream that decodes to at most `hold` bytes has no match distance
    >= hold, so dict_size = max(4096, hold) is lossless. Shrinking further
    breaks valid streams; the 8 MiB / 64 MiB preset default is never needed.
    Peak is therefore about 2 * hold + 40 KiB on LZMA paths.
    """
    if not filters:
        return filters
    fitted = []
    for item in filters:
        filt = dict(item)
        if filt.get("id") == lzma.FILTER_LZMA2:
            requested = filt.get("dict_size")
            if requested is None:
                requested = _PRESET_DICT[filt.get("preset", 6) & 0x1f]
            filt["dict_size"] = min(requested, max(4096, hold))
        fitted.append(filt)
    return fitted


class _PullDecoder:
    """Stream one backend. Raises HyperPressError; codec errors propagate."""

    def __init__(self, payload, kind, mem_budget, hold, filters=None, step_span=None):
        if mem_budget is None:
            mem_budget = hold + _SLACK
        if step_span is None:
            step_span = hold
        self.payload = payload
        self.kind = kind
        self.pos = 0
        self.steps = 0
        self.empty_spins = 0
        self.step_cap = len(payload) + step_span + 8
        if kind == "lzma":
            if filters is not None:
                filters = _fit_lzma_filters(filters, hold)
            self.obj = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
        elif kind == "bz2":
            self.obj = bz2.BZ2Decompressor()
        elif kind == "zstd":
            self.obj = zstd.ZstdDecompressor()
        else:
            self.obj = zlib.decompressobj(-15 if kind == "raw-zlib" else 15)

    def _trailer(self):
        unused = getattr(self.obj, "unused_data", b"")
        if unused or self.pos != len(self.payload):
            raise HyperPressError("Trailing garbage")

    def _next_chunk(self):
        kind = self.kind
        if kind in ("bz2", "zstd", "lzma") and not self.obj.needs_input:
            return b""
        if self.pos < len(self.payload):
            chunk = self.payload[self.pos:self.pos + _CHUNK]
            self.pos += len(chunk)
            if isinstance(chunk, memoryview):
                return chunk.tobytes()
            return chunk
        if kind in ("raw-zlib", "zlib"):
            # zlib can hold pending output after all input was consumed under
            # max_length; an empty feed drains it. read() raises if nothing comes.
            return b""
        raise HyperPressError("Truncated compressed stream")

    def read(self, max_length):
        if max_length <= 0:
            raise HyperPressError("Output exceeds limit")
        obj = self.obj
        if obj.eof:
            self._trailer()
            return b""
        kind = self.kind
        while not obj.eof:
            self.steps += 1
            if self.steps > self.step_cap:
                raise HyperPressError("Truncated compressed stream")
            chunk = self._next_chunk()
            part = obj.decompress(chunk, max_length)
            if kind in ("raw-zlib", "zlib") and obj.unconsumed_tail and not obj.eof:
                # After eof, unconsumed_tail aliases unused_data and feeding it
                # back grows unused_data forever (CPython issue 158169).
                consumed = len(chunk) - len(obj.unconsumed_tail)
                if consumed <= 0 and not part:
                    raise HyperPressError("Truncated compressed stream")
                self.pos -= len(obj.unconsumed_tail)
                if self.pos < 0:
                    self.pos = 0
            if part:
                return part
            if obj.eof:
                break
            if not chunk and kind not in ("bz2", "zstd", "lzma"):
                raise HyperPressError("Truncated compressed stream")
            if not chunk and obj.needs_input:
                # An empty drain can exhaust the codec's buffer with no output;
                # only a stream with no input left is truncated.
                if self.pos >= len(self.payload):
                    raise HyperPressError("Truncated compressed stream")
                continue
            if not chunk:
                self.empty_spins += 1
                if self.empty_spins > 8:
                    raise HyperPressError("Truncated compressed stream")
            else:
                self.empty_spins = 0
        self._trailer()
        return b""


def _bounded_decode(payload, kind, limit, filters=None, mem_budget=None):
    if mem_budget is None:
        mem_budget = limit + _SLACK
    dec = _PullDecoder(payload, kind, mem_budget, limit, filters)
    # Exact size avoids bytearray overallocation, which on a 100 KiB cap
    # sits on top of the zlib window and crosses the 64 KiB slack.
    if limit <= 8 * 1024 * 1024:
        out = bytearray(limit)
        n = 0
        while n <= limit:
            room = limit - n
            part = dec.read(1 if room <= 0 else min(_CHUNK, room + 1))
            if len(part) > room:
                raise HyperPressError("Output exceeds limit")
            if not part:
                break
            out[n:n + len(part)] = part
            n += len(part)
        if n == limit:
            return bytes(out)
        with memoryview(out) as view:
            return bytes(view[:n])
    out = bytearray()
    while len(out) <= limit:
        room = limit - len(out)
        part = dec.read(1 if room <= 0 else min(_CHUNK, room + 1))
        if len(part) > room:
            raise HyperPressError("Output exceeds limit")
        if not part:
            break
        out.extend(part)
    return bytes(out)


def _whole_decode(payload, method, size, mem_budget=None):
    if mem_budget is None:
        mem_budget = size + _SLACK
    if method == 0:
        if len(payload) != size:
            raise HyperPressError("Stored size mismatch")
        if isinstance(payload, memoryview):
            return payload.tobytes()
        return payload
    if method in (1, 4, 5, 6, 7, 8, 9, 10, 12, 16):
        return _bounded_decode(payload, "lzma", size, _lzma_filters(method, size), mem_budget)
    if method == 2:
        return _bounded_decode(payload, "bz2", size, None, mem_budget)
    if method in (3, 13):
        if not HAVE_ZSTD:
            raise HyperPressError("Zstandard decoder unavailable")
        return _bounded_decode(payload, "zstd", size, None, mem_budget)
    if method == 11:
        return _bounded_decode(payload, "raw-zlib", size, None, mem_budget)
    if method in (14, 15):
        from hyperpress.textxf import decode as textxf_decode
        cap = size
        if method == 14:
            inner = _bounded_decode(payload, "bz2", cap, None, mem_budget)
        else:
            inner = _bounded_decode(payload, "lzma", cap, _lzma_filters(method, size), mem_budget)
        if len(inner) >= 3 and inner[:3] == b"HPt":
            return textxf_decode(inner, size)
        raise HyperPressError("Invalid TEXT payload")
    raise HyperPressError("Unknown method")


def _v2_header(mode, data):
    return MAGIC + bytes((FORMAT_VERSION, mode)) + _varint(len(data)) + struct.pack("<I", zlib.crc32(data) & 0xffffffff)


def _blocks_compress(data, verbose):
    bs = block_size(data)
    blocks = []
    for off in range(0, len(data), bs):
        chunk = data[off:off + bs]
        cd, osz, pp, be, _ = compress_block(chunk)
        blocks.append((cd, osz, pp, be))
        if verbose:
            print("  Blk %3d: %8dB -> %8dB | %s+%s" %
                  (len(blocks), len(chunk), len(cd), pp.name, be.name))
    out = bytearray(_v2_header(1, data))
    out.extend(_varint(len(blocks)))
    for cd, osz, pp, be in blocks:
        out.extend(_varint(osz))
        out.extend(_varint(len(cd)))
        out.extend((int(pp), int(be)))
        out.extend(cd)
    return bytes(out)


def _probe_candidates(data):
    """Rank optional whole methods and predict whether splitting helps."""
    width = 32768
    n = len(data)
    offsets = (0, max(0, (n - width) // 2), n - width)
    samples = [data[off:off + width] for off in offsets]
    probe = b"".join(samples)
    baseline = min(len(_whole_compress(probe, method)) for method in (1, 2))
    optional = []
    for method in (4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
        if method == 13 and not HAVE_ZSTD:
            continue
        try:
            size = len(_whole_compress(probe, method))
        except (lzma.LZMAError, OSError, ValueError):
            continue
        if size < baseline * 0.985:
            optional.append((size, method))
    optional.sort()
    # Separate zlib streams expose abrupt changes without running block engine.
    whole_zlib = len(zlib.compress(probe, 6))
    split_zlib = sum(len(zlib.compress(sample, 6)) for sample in samples)
    blocks_worth_trying = split_zlib < whole_zlib * 0.95
    return [method for _, method in optional[:1]], blocks_worth_trying


def compress(data, level="best", verbose=False):
    """Compress bytes to HPRX v2, selecting smallest candidate."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if level not in ("best", "fast"):
        raise ValueError("level must be 'best' or 'fast'")
    header = _v2_header(0, data)
    if not data:
        return header + b"\x00"
    if level == "fast":
        methods = [0, 16, 13] if len(data) >= 131072 else [0, 11, 2, 12, 13]
        try_blocks = False
    elif len(data) >= 2 * 1024 * 1024:
        optional, try_blocks = _probe_candidates(data)
        methods = [0, 1, 2, 3] + optional
        if _looks_like_text(data):
            methods.append(14)
    else:
        methods = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]
        try_blocks = True
        if _looks_like_text(data):
            methods.extend((14, 15))
    best = None
    for method in methods:
        if method in (3, 13) and not HAVE_ZSTD:
            continue
        try:
            candidate = header + bytes((method,)) + _whole_compress(data, method)
        except (lzma.LZMAError, OSError, ValueError):
            continue
        if best is None or len(candidate) < len(best):
            best = candidate
    if try_blocks:
        blocks = _blocks_compress(data, verbose)
        if len(blocks) < len(best):
            best = blocks
    return best


def _pp_cap(pp, osz):
    if pp == PreProc.NIBBLE or pp == PreProc.RLE:
        return 2 * osz
    if pp == PreProc.BWT_MTF:
        return osz + 4
    if pp == PreProc.TRANSPOSE:
        return osz + 1
    return osz


def _iter_stored(payload, cap):
    if len(payload) > cap:
        raise HyperPressError("Block exceeds limit")
    view = payload if isinstance(payload, memoryview) else memoryview(payload)
    for off in range(0, len(view), _CHUNK):
        yield view[off:off + _CHUNK]


def _iter_codec(payload, kind, filters, cap, mem_budget, hold):
    dec = _PullDecoder(payload, kind, mem_budget, hold, filters, step_span=cap)
    produced = 0
    while produced <= cap:
        space = cap - produced
        part = dec.read(min(_CHUNK, space + 1))
        if not part:
            return
        if len(part) > space:
            raise HyperPressError("Output exceeds limit")
        produced += len(part)
        yield part


def _iter_zlib_lzma(payload, cap, mem_budget, hold):
    # Count the LZMA intermediate; do not keep it. The zlib output is what
    # the preprocessor sees, and that count stays at `cap`.
    # The zlib intermediate can be slightly longer than the block, so the
    # dictionary must cover lz_limit, not just hold.
    dec = _PullDecoder(
        payload, "lzma", mem_budget, cap + _SLACK,
        [{"id": lzma.FILTER_LZMA2}], step_span=cap + _SLACK,
    )
    zobj = zlib.decompressobj(15)
    produced = 0
    lz_count = 0
    lz_limit = cap + _SLACK
    pending = b""
    while produced <= cap:
        if not pending:
            room = lz_limit - lz_count
            if room <= 0:
                raise HyperPressError("Output exceeds limit")
            part = dec.read(min(_CHUNK, room + 1))
            if len(part) > room:
                raise HyperPressError("Output exceeds limit")
            if not part:
                break
            lz_count += len(part)
            pending = part
        space = cap - produced
        if space < 0:
            raise HyperPressError("Output exceeds limit")
        zpart = zobj.decompress(pending, min(_CHUNK, space + 1))
        used = len(pending) - len(zobj.unconsumed_tail)
        if used <= 0 and not zpart and not zobj.eof:
            raise HyperPressError("Truncated compressed stream")
        pending = b"" if zobj.eof else zobj.unconsumed_tail
        if len(zpart) > space:
            raise HyperPressError("Output exceeds limit")
        if zpart:
            produced += len(zpart)
            yield zpart
        elif not pending and zobj.eof:
            break
    while not zobj.eof and produced <= cap:
        space = cap - produced
        zpart = zobj.decompress(pending, min(_CHUNK, space + 1))
        pending = b"" if zobj.eof else zobj.unconsumed_tail
        if not zpart:
            break
        if len(zpart) > space:
            raise HyperPressError("Output exceeds limit")
        produced += len(zpart)
        yield zpart
    if not zobj.eof:
        raise HyperPressError("Truncated compressed stream")
    if zobj.unused_data or pending:
        raise HyperPressError("Trailing garbage")
    # The LZMA stream must end with the zlib stream; read() checks its trailer.
    if dec.read(1):
        raise HyperPressError("Trailing garbage")


def _iter_backend(payload, be, cap, mem_budget, hold):
    if be == Backend.STORED:
        yield from _iter_stored(payload, cap)
        return
    if be == Backend.ZLIB_LZMA:
        yield from _iter_zlib_lzma(payload, cap, mem_budget, hold)
        return
    if be == Backend.ZLIB9:
        kind, filters = "zlib", None
    elif be == Backend.LZMA:
        kind, filters = "lzma", [{"id": lzma.FILTER_LZMA2}]
    elif be == Backend.BZ2:
        kind, filters = "bz2", None
    else:
        raise HyperPressError("Unknown block codec")
    yield from _iter_codec(payload, kind, filters, cap, mem_budget, hold)


def _nibble_from_iter(parts, osz):
    need = 2 * osz
    out = bytearray(osz)
    got = 0
    for part in parts:
        if got + len(part) > need:
            raise HyperPressError("Output exceeds limit")
        for b in part:
            if got < osz:
                out[got] = b
            else:
                i = got - osz
                out[i] = (out[i] << 4) | b
            got += 1
    if got != need:
        raise HyperPressError("Invalid nibble block")
    return bytes(out)


def _rle_from_iter(parts, osz):
    out = bytearray(osz)
    n = 0
    pending = False
    for part in parts:
        for b in part:
            if pending:
                if n + b > osz:
                    raise HyperPressError("Invalid RLE block")
                if b:
                    out[n:n + b] = b"\x00" * b
                n += b
                pending = False
            elif b == 0:
                pending = True
            else:
                if n >= osz:
                    raise HyperPressError("Block exceeds limit")
                out[n] = b
                n += 1
    if pending:
        raise HyperPressError("Invalid RLE block")
    if n != osz:
        raise HyperPressError("Block size mismatch")
    return bytes(out)


def _decode_block(payload, pp, be, osz, mem_budget=None):
    if pp not in PREPROC_DEC or be not in Backend._value2member_map_:
        raise HyperPressError("Unknown block codec")
    if mem_budget is None:
        mem_budget = osz + _SLACK
    # Inverse BWT keeps one Python int per symbol (~48 B traced).
    if pp == PreProc.BWT_MTF and osz * 48 > mem_budget - osz:
        raise HyperPressError("Output exceeds limit")
    cap = _pp_cap(pp, osz)
    hold = osz if pp in (PreProc.NIBBLE, PreProc.RLE) else cap
    if pp == PreProc.NIBBLE:
        result = _nibble_from_iter(_iter_backend(payload, be, cap, mem_budget, hold), osz)
    elif pp == PreProc.RLE:
        result = _rle_from_iter(_iter_backend(payload, be, cap, mem_budget, hold), osz)
    else:
        if be == Backend.STORED and len(payload) > cap:
            raise HyperPressError("Block exceeds limit")
        if be == Backend.STORED:
            decoded = payload
        else:
            buf = bytearray()
            for part in _iter_backend(payload, be, cap, mem_budget, hold):
                buf.extend(part)
            decoded = bytes(buf)
        if pp == PreProc.BWT_MTF and (len(decoded) < 4 or
                struct.unpack_from("<I", decoded)[0] >= len(decoded) - 4):
            raise HyperPressError("Invalid BWT block")
        if pp == PreProc.TRANSPOSE and (not decoded or decoded[0] == 0):
            raise HyperPressError("Invalid transpose block")
        result = PREPROC_DEC[PreProc(pp)](decoded)
    if len(result) != osz:
        raise HyperPressError("Block size mismatch")
    return result


def _decode_v2(data, max_output_size):
    if len(data) < 6 or data[:4] != MAGIC or data[4] != FORMAT_VERSION:
        raise HyperPressError("Invalid HPRX header")
    mode = data[5]
    size, off = _read_varint(data, 6)
    if size > max_output_size:
        raise HyperPressError("Output exceeds limit")
    if len(data) < off + 4:
        raise HyperPressError("Truncated CRC")
    crc = struct.unpack_from("<I", data, off)[0]
    off += 4
    if mode == 0:
        if off >= len(data):
            raise HyperPressError("Missing method")
        result = _whole_decode(memoryview(data)[off + 1:], data[off], size,
                               max_output_size + _SLACK)
    elif mode == 1:
        count, off = _read_varint(data, off)
        if count > size or (count == 0) != (size == 0):
            raise HyperPressError("Invalid block count")
        out = bytearray()
        for _ in range(count):
            osz, off = _read_varint(data, off)
            csz, off = _read_varint(data, off)
            if osz == 0 or osz > 131072 or osz > size - len(out):
                raise HyperPressError("Invalid block size")
            if len(data) - off < 2 or csz > len(data) - off - 2:
                raise HyperPressError("Truncated block")
            pp, be = data[off], data[off + 1]
            off += 2
            out.extend(_decode_block(memoryview(data)[off:off + csz], pp, be, osz,
                                     max_output_size + _SLACK))
            off += csz
        if off != len(data):
            raise HyperPressError("Trailing garbage")
        result = bytes(out)
    else:
        raise HyperPressError("Unknown mode")
    if len(result) != size or (zlib.crc32(result) & 0xffffffff) != crc:
        raise HyperPressError("Size or CRC mismatch")
    return result


def _decode_v1(data, max_output_size):
    hsz = struct.calcsize(HDR)
    if len(data) < hsz:
        raise HyperPressError("Truncated v1 header")
    mg, ver, flag, count, size = struct.unpack_from(HDR, data)
    if mg != MAGIC or ver != 1 or size > max_output_size:
        raise HyperPressError("Invalid v1 header or output exceeds limit")
    off = hsz
    bsz = struct.calcsize(BLK)
    out = bytearray()
    if count > size or (count == 0) != (size == 0):
        raise HyperPressError("Invalid v1 block count")
    for _ in range(count):
        if len(data) - off < bsz:
            raise HyperPressError("Truncated v1 block")
        osz, csz, pp, be, crc = struct.unpack_from(BLK, data, off)
        off += bsz
        if osz == 0 or osz > 131072 or osz > size - len(out) or csz > len(data) - off:
            raise HyperPressError("Invalid v1 block size")
        block = _decode_block(memoryview(data)[off:off + csz], pp, be, osz,
                              max_output_size + _SLACK)
        if zlib.crc32(block) & 0xffffffff != crc:
            raise HyperPressError("v1 block CRC mismatch")
        out.extend(block)
        off += csz
    if off != len(data) or len(out) != size:
        raise HyperPressError("v1 size mismatch or trailing garbage")
    return bytes(out)


def decompress(data, max_output_size=1 << 30):
    """Decode HPRX v1 or v2, enforcing declared and streamed output limits."""
    if not isinstance(data, bytes):
        raise HyperPressError("Input must be bytes")
    if not isinstance(max_output_size, int) or max_output_size < 0:
        raise HyperPressError("Invalid max_output_size")
    try:
        if len(data) < 5 or data[:4] != MAGIC:
            raise HyperPressError("Invalid HPRX magic bytes")
        if data[4] == 1:
            return _decode_v1(data, max_output_size)
        if data[4] == FORMAT_VERSION:
            return _decode_v2(data, max_output_size)
        raise HyperPressError("Unknown HPRX version")
    except Exception as exc:
        if isinstance(exc, HyperPressError):
            raise
        raise HyperPressError(str(exc)) from exc
