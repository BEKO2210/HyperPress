import random

import pytest

from hyperpress import HyperPressError, compress, decompress
from hyperpress.textxf import decode as textxf_decode
from hyperpress.textxf import encode as textxf_encode


def test_roundtrip_random_bytes():
    rng = random.Random(0)
    for n in (0, 1, 2, 100, 4096):
        data = bytes(rng.getrandbits(8) for _ in range(n))
        payload = textxf_encode(data)
        assert textxf_decode(payload, len(data)) == data


def test_roundtrip_utf8_german():
    data = (
        "Die Kraft der Komprimierung liegt in der Mustererkennung. "
        "Groß und klein: äöüß ÄÖÜ."
    ).encode("utf-8")
    payload = textxf_encode(data)
    assert textxf_decode(payload, len(data)) == data


def test_decode_respects_max_output_size():
    data = b"The quick brown fox jumps over the lazy dog. " * 5
    payload = textxf_encode(data)
    with pytest.raises(HyperPressError):
        textxf_decode(payload, len(data) - 1)


def test_malformed_payloads_hyperpress_error():
    for blob in (b"", b"HPt", b"HPt\x02\x00", b"XXXX\x02\x00"):
        with pytest.raises(HyperPressError):
            textxf_decode(blob, 100)


def test_whole_method_14_roundtrip():
    data = open(
        "benchmarks/.corpus/canterbury/alice29.txt", "rb"
    ).read()
    blob = compress(data, level="best")
    assert decompress(blob) == data


def test_corrupted_textxf_payload():
    data = b"hello world"
    payload = textxf_encode(data)
    with pytest.raises(HyperPressError):
        textxf_decode(payload[:-2], len(data))
