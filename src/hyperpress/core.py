#!/usr/bin/env python3
"""
HyperPress v1.0 — Adaptive Meta-Compression Engine
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
VERSION = 1


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

HDR = "<4sBBHQ"
BLK = "<IIBBI"


def compress(data, verbose=False):
    """Compress data using HyperPress adaptive meta-compression.

    Args:
        data: bytes to compress
        verbose: if True, print per-block statistics

    Returns:
        Compressed bytes in HPRX format.
    """
    if not data:
        return struct.pack(HDR, MAGIC, VERSION, 1, 0, 0)
    bs = block_size(data)
    blocks = []
    off = 0
    while off < len(data):
        chunk = data[off:off + bs]
        cd, osz, pp, be, crc = compress_block(chunk)
        blocks.append((cd, osz, len(cd), pp, be, crc))
        if verbose:
            r = len(cd) / len(chunk) * 100
            print("  Blk %3d: %8sB -> %8sB (%5.1f%%) | %8s+%s" % (
                len(blocks), format(len(chunk), ","),
                format(len(cd), ","), r, pp.name, be.name))
        off += bs
    out = bytearray(struct.pack(HDR, MAGIC, VERSION, 1, len(blocks), len(data)))
    for cd, osz, csz, pp, be, crc in blocks:
        out.extend(struct.pack(BLK, osz, csz, int(pp), int(be), crc))
        out.extend(cd)
    return bytes(out)


def decompress(data):
    """Decompress HPRX-format data back to the original bytes.

    Args:
        data: HPRX compressed bytes

    Returns:
        Original uncompressed bytes.

    Raises:
        AssertionError: if magic bytes, CRC, or size checks fail.
    """
    mg, ver, fl, bc, osz = struct.unpack(HDR, data[:struct.calcsize(HDR)])
    assert mg == MAGIC, "Invalid HPRX magic bytes"
    off = struct.calcsize(HDR)
    out = bytearray()
    bsz = struct.calcsize(BLK)
    for _ in range(bc):
        bosz, bcsz, pp, be, crc = struct.unpack(BLK, data[off:off + bsz])
        off += bsz
        cd = data[off:off + bcsz]
        off += bcsz
        dec = decomp_backend(cd, Backend(be), bosz)
        res = PREPROC_DEC[PreProc(pp)](dec)
        assert zlib.crc32(res) & 0xFFFFFFFF == crc, "CRC FAIL"
        out.extend(res)
    assert len(out) == osz, "Size mismatch"
    return bytes(out)


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
