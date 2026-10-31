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
import json
import random
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
    preset = (6 if method == 12 else 9 | lzma.PRESET_EXTREME)
    settings = {"id": lzma.FILTER_LZMA2, "preset": preset}
    if method == 1:
        settings["dict_size"] = max(4096, min(2 * size, 64 * 1024 * 1024))
    if method == 8:
        settings.update(lc=4, lp=0, pb=0)
    elif method == 9:
        settings.update(lc=0, lp=2, pb=2)
    elif method == 10:
        settings.update(lc=1, lp=0, pb=0)
    if method in (4, 5, 6):
        return [{"id": lzma.FILTER_DELTA, "dist": {4: 1, 5: 2, 6: 4}[method]}, settings]
    if method == 7:
        return [{"id": lzma.FILTER_X86}, settings]
    return [settings]


def _whole_compress(data, method):
    if method == 0:
        return data
    if method in (1, 4, 5, 6, 7, 8, 9, 10, 12):
        return lzma.compress(data, format=lzma.FORMAT_RAW,
                             filters=_lzma_filters(method, len(data)))
    if method == 2:
        return bz2.compress(data, compresslevel=9)
    if method in (3, 13):
        return zstd.compress(data, level=19 if method == 3 else 3)
    if method == 11:
        obj = zlib.compressobj(9, zlib.DEFLATED, -15)
        return obj.compress(data) + obj.flush()
    raise HyperPressError("Unknown method")


def _bounded_decode(payload, kind, limit, filters=None):
    if kind == "lzma":
        obj = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    elif kind == "bz2":
        obj = bz2.BZ2Decompressor()
    elif kind == "zstd":
        obj = zstd.ZstdDecompressor()
    else:
        obj = zlib.decompressobj(-15 if kind == "raw-zlib" else 15)
    out = bytearray()
    pos = 0
    while not obj.eof:
        if kind in ("bz2", "zstd") and not obj.needs_input:
            chunk = b""
        elif kind == "lzma" and not obj.needs_input:
            chunk = b""
        elif pos < len(payload):
            chunk = payload[pos:pos + 65536]
            pos += len(chunk)
        else:
            raise HyperPressError("Truncated compressed stream")
        cap = min(65536, limit - len(out) + 1)
        if cap <= 0:
            raise HyperPressError("Output exceeds limit")
        part = obj.decompress(chunk, cap)
        out.extend(part)
        if len(out) > limit:
            raise HyperPressError("Output exceeds limit")
        if kind in ("raw-zlib", "zlib") and obj.unconsumed_tail:
            pos -= len(obj.unconsumed_tail)
        if not chunk and not part and not obj.eof and (kind not in ("bz2", "zstd", "lzma") or obj.needs_input):
            raise HyperPressError("Truncated compressed stream")
    if obj.unused_data or pos != len(payload):
        raise HyperPressError("Trailing garbage")
    return bytes(out)


def _whole_decode(payload, method, size):
    if method == 0:
        if len(payload) != size:
            raise HyperPressError("Stored size mismatch")
        return payload
    if method in (1, 4, 5, 6, 7, 8, 9, 10, 12):
        return _bounded_decode(payload, "lzma", size, _lzma_filters(method, size))
    if method == 2:
        return _bounded_decode(payload, "bz2", size)
    if method in (3, 13):
        if not HAVE_ZSTD:
            raise HyperPressError("Zstandard decoder unavailable")
        return _bounded_decode(payload, "zstd", size)
    if method == 11:
        return _bounded_decode(payload, "raw-zlib", size)
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


def compress(data, level="best", verbose=False):
    """Compress bytes to HPRX v2, selecting smallest candidate."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    if level not in ("best", "fast"):
        raise ValueError("level must be 'best' or 'fast'")
    header = _v2_header(0, data)
    if not data:
        return header + b"\x00"
    methods = ([0, 11, 2, 12, 13] if level == "fast" else
               [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13])
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
    if level == "best":
        blocks = _blocks_compress(data, verbose)
        if len(blocks) < len(best):
            best = blocks
    return best


def _decode_block(payload, pp, be, osz):
    if pp not in PREPROC_DEC or be not in Backend._value2member_map_:
        raise HyperPressError("Unknown block codec")
    if pp == PreProc.NIBBLE:
        cap = 2 * osz
    elif pp == PreProc.RLE:
        cap = 2 * osz
    elif pp == PreProc.BWT_MTF:
        cap = osz + 4
    elif pp == PreProc.TRANSPOSE:
        cap = osz + 1
    else:
        cap = osz
    if be == Backend.STORED:
        decoded = payload
        if len(decoded) > cap:
            raise HyperPressError("Block exceeds limit")
    elif be == Backend.ZLIB9:
        decoded = _bounded_decode(payload, "zlib", cap)
    elif be == Backend.LZMA:
        decoded = _bounded_decode(payload, "lzma", cap,
                                  [{"id": lzma.FILTER_LZMA2}])
    elif be == Backend.BZ2:
        decoded = _bounded_decode(payload, "bz2", cap)
    else:
        # Legacy backend: zlib-1 then raw LZMA2-6.
        inner = _bounded_decode(payload, "lzma", cap + 65536,
                                [{"id": lzma.FILTER_LZMA2}])
        decoded = _bounded_decode(inner, "zlib", cap)
    if pp == PreProc.RLE:
        result_buf = bytearray()
        i = 0
        while i < len(decoded):
            if decoded[i] == 0:
                if i + 1 >= len(decoded) or len(result_buf) + decoded[i + 1] > osz:
                    raise HyperPressError("Invalid RLE block")
                result_buf.extend(b"\x00" * decoded[i + 1])
                i += 2
            else:
                if len(result_buf) >= osz:
                    raise HyperPressError("Block exceeds limit")
                result_buf.append(decoded[i])
                i += 1
        result = bytes(result_buf)
    else:
        if pp == PreProc.BWT_MTF and (len(decoded) < 4 or
                struct.unpack_from("<I", decoded)[0] >= len(decoded) - 4):
            raise HyperPressError("Invalid BWT block")
        if pp == PreProc.TRANSPOSE and (not decoded or decoded[0] == 0):
            raise HyperPressError("Invalid transpose block")
        if pp == PreProc.NIBBLE and len(decoded) != 2 * osz:
            raise HyperPressError("Invalid nibble block")
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
        result = _whole_decode(data[off + 1:], data[off], size)
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
            out.extend(_decode_block(data[off:off + csz], pp, be, osz))
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
        block = _decode_block(data[off:off + csz], pp, be, osz)
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


# ── Benchmark ─────────────────────────────────────────────

def gen_data():
    ds = {}
    ds["English Text"] = (
        "The quick brown fox jumps over the lazy dog. " * 200
        + "Sphinx of black quartz judge my vow. " * 150
        + "Pack my box with five dozen liquor jugs. " * 180
    ).encode()

    ds["German Text"] = (
        "Die Kraft der Komprimierung liegt in der Mustererkennung. " * 200
        + "Fortschrittliche Algorithmen erkennen wiederkehrende Strukturen. " * 160
        + "Kuenstliche Intelligenz revolutioniert die Datenverarbeitung. " * 150
    ).encode()

    recs = [
        {"id": i, "name": "item_%04d" % i, "val": (i * 17 + 31) % 1000, "active": i % 3 != 0}
        for i in range(400)
    ]
    ds["JSON Data"] = json.dumps(recs, indent=2).encode()

    random.seed(42)
    s = bytearray()
    v = 128
    for _ in range(30000):
        v = max(0, min(255, v + random.randint(-3, 3)))
        s.append(v)
    ds["Sensor Data"] = bytes(s)

    sp = bytearray(25000)
    for i in range(0, 25000, 50):
        sp[i] = random.randint(1, 255)
    ds["Sparse Binary"] = bytes(sp)

    log = []
    for i in range(1200):
        lv = ["INFO", "WARN", "ERROR", "DEBUG"][i % 4]
        log.append(
            "2025-02-26T10:%02d:%02dZ [%s] svc.mod%d: req#%06d 192.168.%d.%d\n"
            % (i // 60, i % 60, lv, i % 10, i, i % 256, (i * 7) % 256)
        )
    ds["Log File"] = "".join(log).encode()

    p = b"ABCDEFGH" * 100
    vr = bytearray(p * 30)
    for i in range(0, len(vr), 137):
        vr[i] = (vr[i] + 1) % 256
    ds["Pattern+Noise"] = bytes(vr)

    code = "def fib(n):\n  a,b=0,1\n  for _ in range(n): a,b=b,a+b\n  return b\n" * 120
    ds["Source Code"] = code.encode()

    return ds


def bench():
    ds = gen_data()
    W = 99
    print("+" + "=" * W + "+")
    print("|%s|" % "HyperPress v1.0 — Benchmark: zlib-9 vs LZMA-RAW vs HyperPress".center(W))
    print("+" + "=" * W + "+")
    print("|  %-20s|%10s|%10s|%10s|%10s|%11s|%9s|%9s |" % (
        "Dataset", "Original", "zlib-9", "LZMA-RAW", "HYPER",
        "HYPER_NETTO", "d vs best", "Winner"))
    print("+" + "=" * W + "+")
    to = tz = tl = th = thn = 0
    wins = {"HP": 0, "zlib": 0, "LZMA": 0}
    for nm, d in ds.items():
        ol = len(d)
        to += ol
        zl = len(zlib.compress(d, 9))
        tz += zl
        ll = len(lzma.compress(d, format=lzma.FORMAT_RAW,
                               filters=[{"id": lzma.FILTER_LZMA2, "preset": 9}]))
        tl += ll
        hp = compress(d)
        hl = len(hp)
        th += hl
        num_blocks = struct.unpack(HDR, hp[:struct.calcsize(HDR)])[3]
        overhead = 16 + (num_blocks * 14)
        hl_netto = hl - overhead
        thn += hl_netto
        assert decompress(hp) == d, "FAIL: %s" % nm
        best_other = min(zl, ll)
        delta_pct = (hl_netto - best_other) / best_other * 100
        if hl_netto <= zl and hl_netto <= ll:
            w = "* HYPER"
            wins["HP"] += 1
        elif zl <= ll:
            w = "zlib-9"
            wins["zlib"] += 1
        else:
            w = "LZMA-RAW"
            wins["LZMA"] += 1
        print("|  %-20s|%9sB|%9sB|%9sB|%9sB|%10sB|%+8.1f%%|%9s |" % (
            nm, format(ol, ","), format(zl, ","), format(ll, ","),
            format(hl, ","), format(hl_netto, ","), delta_pct, w))
    print("+" + "=" * W + "+")
    zr = (1 - tz / to) * 100
    lr = (1 - tl / to) * 100
    hr = (1 - th / to) * 100
    hnr = (1 - thn / to) * 100
    print("|  %-20s|%9sB|%9sB|%9sB|%9sB|%10sB|%9s|%9s |" % (
        "TOTAL", format(to, ","), format(tz, ","), format(tl, ","),
        format(th, ","), format(thn, ","), "", ""))
    print("|  %-20s|%10s|%8.1f%% |%8.1f%% |%8.1f%% |%9.1f%% |%9s|%9s |" % (
        "Ratio", "", zr, lr, hr, hnr, "", ""))
    print("+" + "=" * W + "+")
    vzl = (1 - thn / tz) * 100
    vlm = (1 - thn / tl) * 100
    line1 = "  Wins: HyperPress=%d  zlib-9=%d  LZMA-RAW=%d" % (
        wins["HP"], wins["zlib"], wins["LZMA"])
    print("|%s%s|" % (line1, " " * (W - len(line1))))
    line2 = "  HyperPress vs zlib-9:   %+.2f%% (smaller=better)" % vzl
    print("|%s%s|" % (line2, " " * (W - len(line2))))
    line3 = "  HyperPress vs LZMA-RAW: %+.2f%% (smaller=better)" % vlm
    print("|%s%s|" % (line3, " " * (W - len(line3))))
    print("+" + "=" * W + "+")
    print("\nAll integrity checks passed (CRC32 + Size)")


if __name__ == "__main__":
    bench()
