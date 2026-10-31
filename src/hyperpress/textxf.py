"""
HyperPress TEXT transform (WHOLE methods 14/15 inner payload).

Payload layout (before outer bz2/lzma):

  magic     3 B   b"HPt"
  version   1 B   1 = varint token stream, 2 = compact escape body
  flags     1 B   bit0: identity; bit1: payload newlines are LF (decode emits CRLF)
  -- if not identity --
  ndict     uvarint
  dictionary: ndict entries of (wlen uvarint, wbytes[wlen]) lowercase a-z
  -- version 1 body: uvarint tokens (0=literal run, 1=space, 2=nl, 3=tab, n>=4 word)
  -- version 2 body: bytes:
              0x00 0x00           literal 0x00
              0x00 0x01           literal space
              0x00 0x02           literal newline
              0x00 0x03           literal tab
              0x00 0x04 + uvarint(len) + bytes   literal run
              0x00 (5..254)       word code (wid<<2)|case + 5
              0x00 0xFF + uvarint code   extended word code
                wid in dictionary, case 0=lower, 1=title, 2=ALLCAPS (len>1)
              any other byte      literal that byte (except 0x00)

Identity mode: flags&1, then raw input bytes (lossless for any input).

encode() tries stream (v1) and compact (v2) codings and keeps the payload with
smallest bz2-9 size; if none beat identity, returns identity.

decode(payload, limit) raises HyperPressError on malformed data; respects limit
before allocating more than limit + 64 KiB beyond payload.
"""

import bz2
from collections import Counter

from hyperpress.core import HyperPressError, _read_varint, _varint

_MAGIC = b"HPt"
_VER_STREAM = 1
_VER_COMPACT = 2
_FLAG_IDENTITY = 1
_FLAG_CRLF = 2

_CODE_LITERAL = 0
_CODE_SPACE = 1
_CODE_NL = 2
_CODE_TAB = 3
_CODE_WORD_BASE = 4

_ESC = 0x00
_LIT_ZERO = 0x00
_LIT_SPACE = 0x01
_LIT_NL = 0x02
_LIT_TAB = 0x03
_LIT_RUN = 0x04
_EXT_WORD = 0xFF
_WORD_CODE_BASE = 5

_SINGLE_ESC = {
    0x00: (_LIT_ZERO, None),
    0x20: (_LIT_SPACE, None),
    0x0A: (_LIT_NL, None),
    0x09: (_LIT_TAB, None),
}


def _uvarint_write(n):
    return _varint(n)


def _uvarint_read(data, off):
    return _read_varint(data, off)


def _is_alpha(b):
    return 97 <= b <= 122 or 65 <= b <= 90


def _lower_word(word):
    return bytes(b + 32 if 65 <= b <= 90 else b for b in word)


def _word_case(word):
    if not word:
        return 0, word
    lower = _lower_word(word)
    if word == lower:
        return 0, lower
    if len(word) > 1 and all(65 <= b <= 90 for b in word):
        return 2, lower
    if 65 <= word[0] <= 90 and all(97 <= b <= 122 for b in word[1:]):
        return 1, lower
    return 3, lower


def _apply_case(lower, case):
    if case == 0:
        return lower
    if case == 1:
        return bytes((lower[0] - 32,)) + lower[1:]
    if case == 2 and len(lower) > 1:
        return bytes(b - 32 if 97 <= b <= 122 else b for b in lower)
    return lower


def _can_crlf_norm(data):
    if b"\r\n" not in data:
        return False
    stripped = data.replace(b"\r\n", b"")
    return b"\r" not in stripped and b"\n" not in stripped


def _maybe_norm_crlf(data):
    if _can_crlf_norm(data):
        return data.replace(b"\r\n", b"\n"), _FLAG_CRLF
    return data, 0


def _denorm_crlf(data):
    return data.replace(b"\n", b"\r\n")


def _tokenize(data):
    i = 0
    n = len(data)
    while i < n:
        if _is_alpha(data[i]):
            j = i + 1
            while j < n and _is_alpha(data[j]):
                j += 1
            yield ("w", data[i:j])
            i = j
        else:
            j = i + 1
            while j < n and not _is_alpha(data[j]):
                j += 1
            yield ("l", data[i:j])
            i = j


def _dict_entry_cost(w):
    ln = len(w)
    return (1 if ln < 128 else 2) + ln


def _build_dictionary(tokens, max_words=4096):
    counts = Counter()
    for kind, chunk in tokens:
        if kind != "w":
            continue
        case, lower = _word_case(chunk)
        if case != 3 and all(97 <= b <= 122 for b in lower):
            counts[lower] += 1
    items = []
    for w, c in counts.items():
        if c < 2:
            continue
        save = c * max(0, len(w) - 2) - _dict_entry_cost(w)
        if save > 0:
            items.append((save, w))
    items.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))
    return [w for _, w in items[:max_words]]


def _emit_literal_byte(out, b):
    if b in _SINGLE_ESC:
        out.extend((_ESC, _SINGLE_ESC[b][0]))
    else:
        out.append(b)


def _emit_literal_run(out, chunk):
    if len(chunk) == 1:
        _emit_literal_byte(out, chunk[0])
        return
    out.extend((_ESC, _LIT_RUN))
    out.extend(_uvarint_write(len(chunk)))
    out.extend(chunk)


def _emit_word(out, windex, lower, case):
    code = (windex << 2) | case
    packed = _WORD_CODE_BASE + code
    if packed <= 254:
        out.extend((_ESC, packed))
    else:
        out.extend((_ESC, _EXT_WORD))
        out.extend(_uvarint_write(code))


def _emit_stream_literal(out, chunk):
    if len(chunk) == 1 and chunk == b" ":
        out.extend(_uvarint_write(_CODE_SPACE))
        return
    if len(chunk) == 1 and chunk == b"\n":
        out.extend(_uvarint_write(_CODE_NL))
        return
    if len(chunk) == 1 and chunk == b"\t":
        out.extend(_uvarint_write(_CODE_TAB))
        return
    out.extend(_uvarint_write(_CODE_LITERAL))
    out.extend(_uvarint_write(len(chunk)))
    out.extend(chunk)


def _encode_stream(data):
    tokens = list(_tokenize(data))
    words = _build_dictionary(tokens)
    windex = {w: i for i, w in enumerate(words)}
    out = bytearray()
    out.extend(_MAGIC)
    out.append(_VER_STREAM)
    out.append(0)
    out.extend(_uvarint_write(len(words)))
    for w in words:
        out.extend(_uvarint_write(len(w)))
        out.extend(w)
    for kind, chunk in tokens:
        if kind == "l":
            _emit_stream_literal(out, chunk)
            continue
        case, lower = _word_case(chunk)
        if case == 3 or lower not in windex:
            _emit_stream_literal(out, chunk)
            continue
        if case == 2 and len(lower) <= 1:
            _emit_stream_literal(out, chunk)
            continue
        out.extend(_uvarint_write(_CODE_WORD_BASE + (windex[lower] << 2) + case))
    return bytes(out)


def _encode_compact(data):
    tokens = list(_tokenize(data))
    words = _build_dictionary(tokens)
    windex = {w: i for i, w in enumerate(words)}
    out = bytearray()
    out.extend(_MAGIC)
    out.append(_VER_COMPACT)
    out.append(0)
    out.extend(_uvarint_write(len(words)))
    for w in words:
        out.extend(_uvarint_write(len(w)))
        out.extend(w)
    for kind, chunk in tokens:
        if kind == "l":
            _emit_literal_run(out, chunk)
            continue
        case, lower = _word_case(chunk)
        if case == 3 or lower not in windex:
            _emit_literal_run(out, chunk)
            continue
        if case == 2 and len(lower) <= 1:
            _emit_literal_run(out, chunk)
            continue
        _emit_word(out, windex[lower], lower, case)
    return bytes(out)


def _identity_payload(data, extra_flags=0):
    body, crlf = _maybe_norm_crlf(data)
    flags = _FLAG_IDENTITY | crlf | extra_flags
    return _MAGIC + bytes((_VER_COMPACT, flags)) + body


def _wrap_encode(fn, data):
    body, crlf = _maybe_norm_crlf(data)
    raw = fn(body)
    if crlf and not (raw[4] & _FLAG_IDENTITY):
        out = bytearray(raw)
        out[4] = raw[4] | crlf
        return bytes(out)
    if crlf and (raw[4] & _FLAG_IDENTITY):
        return _identity_payload(data)
    return raw


def encode(data):
    """Return self-describing TEXT payload (not yet bz2/lzma wrapped)."""
    if not isinstance(data, (bytes, bytearray)):
        raise HyperPressError("TEXT encode expects bytes")
    if not data:
        return _MAGIC + bytes((_VER_COMPACT, _FLAG_IDENTITY))
    ident = _identity_payload(data)
    best = ident
    best_len = len(bz2.compress(ident, 9))
    for fn in (_encode_stream, _encode_compact):
        try:
            cand = _wrap_encode(fn, data)
        except Exception:
            continue
        try:
            blen = len(bz2.compress(cand, 9))
        except Exception:
            continue
        if blen < best_len:
            best_len = blen
            best = cand
    return best


def _decode_identity(body, limit, flags):
    if flags & _FLAG_CRLF:
        if len(body) > limit:
            raise HyperPressError("Output exceeds limit")
        out = _denorm_crlf(body)
        if len(out) != limit:
            raise HyperPressError("Size mismatch")
        return out
    if len(body) != limit:
        raise HyperPressError("Size mismatch")
    return bytes(body)


def _finish_decode(out, flags, limit):
    if flags & _FLAG_CRLF:
        out = _denorm_crlf(out)
    if len(out) != limit:
        raise HyperPressError("Size mismatch")
    return bytes(out)


def _decode_stream_body(payload, off, words, limit):
    out = bytearray()
    while off < len(payload):
        code, off = _uvarint_read(payload, off)
        if code == _CODE_LITERAL:
            ln, off = _uvarint_read(payload, off)
            if ln > limit - len(out) or off + ln > len(payload):
                raise HyperPressError("Invalid TEXT literal")
            out.extend(payload[off:off + ln])
            off += ln
        elif code == _CODE_SPACE:
            if len(out) + 1 > limit:
                raise HyperPressError("Output exceeds limit")
            out.append(0x20)
        elif code == _CODE_NL:
            if len(out) + 1 > limit:
                raise HyperPressError("Output exceeds limit")
            out.append(0x0A)
        elif code == _CODE_TAB:
            if len(out) + 1 > limit:
                raise HyperPressError("Output exceeds limit")
            out.append(0x09)
        elif code >= _CODE_WORD_BASE:
            wid = (code - _CODE_WORD_BASE) >> 2
            case = (code - _CODE_WORD_BASE) & 3
            if wid >= len(words):
                raise HyperPressError("Invalid TEXT word index")
            piece = _apply_case(words[wid], case)
            if len(out) + len(piece) > limit:
                raise HyperPressError("Output exceeds limit")
            out.extend(piece)
        else:
            raise HyperPressError("Invalid TEXT token")
    if len(out) > limit:
        raise HyperPressError("Output exceeds limit")
    return bytes(out)


def _read_body_byte(payload, off):
    if off >= len(payload):
        raise HyperPressError("Truncated TEXT body")
    b = payload[off]
    if b != _ESC:
        return b, off + 1
    if off + 1 >= len(payload):
        raise HyperPressError("Truncated TEXT escape")
    sub = payload[off + 1]
    off += 2
    if sub == _LIT_ZERO:
        return 0, off
    if sub == _LIT_SPACE:
        return 0x20, off
    if sub == _LIT_NL:
        return 0x0A, off
    if sub == _LIT_TAB:
        return 0x09, off
    if sub == _LIT_RUN:
        ln, off = _uvarint_read(payload, off)
        if ln > 65536 or off + ln > len(payload):
            raise HyperPressError("Invalid TEXT literal run")
        return ("run", payload[off:off + ln]), off + ln
    if sub == _EXT_WORD:
        code, off = _uvarint_read(payload, off)
        return ("word", code), off
    if sub >= _WORD_CODE_BASE:
        return ("word", sub - _WORD_CODE_BASE), off
    raise HyperPressError("Invalid TEXT escape")


def decode(payload, limit):
    """Inverse of encode; ``limit`` is max output bytes (original size)."""
    if not isinstance(payload, (bytes, bytearray)):
        raise HyperPressError("TEXT decode expects bytes")
    if limit < 0:
        raise HyperPressError("Invalid limit")
    if len(payload) < 5 or payload[:3] != _MAGIC:
        raise HyperPressError("Invalid TEXT payload")
    ver = payload[3]
    if ver not in (_VER_STREAM, _VER_COMPACT):
        raise HyperPressError("Unsupported TEXT version")
    flags = payload[4]
    off = 5
    if flags & _FLAG_IDENTITY:
        return _decode_identity(payload[off:], limit, flags)
    ndict, off = _uvarint_read(payload, off)
    if ndict > 65536:
        raise HyperPressError("TEXT dictionary too large")
    words = []
    for _ in range(ndict):
        wlen, off = _uvarint_read(payload, off)
        if wlen > 64 or off + wlen > len(payload):
            raise HyperPressError("Truncated TEXT dictionary")
        wb = payload[off:off + wlen]
        off += wlen
        if not all(97 <= b <= 122 for b in wb):
            raise HyperPressError("Invalid dictionary word")
        words.append(wb)
    if sum(len(w) for w in words) > limit + 65536:
        raise HyperPressError("Output exceeds limit")
    if ver == _VER_STREAM:
        return _finish_decode(_decode_stream_body(payload, off, words, limit), flags, limit)
    out = bytearray()
    while off < len(payload):
        item, off = _read_body_byte(payload, off)
        if isinstance(item, tuple):
            kind, val = item
            if kind == "run":
                if len(out) + len(val) > limit:
                    raise HyperPressError("Output exceeds limit")
                out.extend(val)
            else:
                code = val
                wid = code >> 2
                case = code & 3
                if wid >= len(words):
                    raise HyperPressError("Invalid TEXT word index")
                piece = _apply_case(words[wid], case)
                if len(out) + len(piece) > limit:
                    raise HyperPressError("Output exceeds limit")
                out.extend(piece)
        else:
            if len(out) + 1 > limit:
                raise HyperPressError("Output exceeds limit")
            out.append(item)
    return _finish_decode(out, flags, limit)
