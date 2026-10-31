"""Compression speed selection must preserve mandatory full-input candidates."""

import pytest

from hyperpress import compress, decompress
from hyperpress import core


@pytest.mark.parametrize("data", [
    b"\x00" * (2 * 1024 * 1024),
    b"alpha beta gamma\n" * 131072,
    bytes(range(256)) * 8192,
])
def test_mandatory_methods_run_on_full_input(monkeypatch, data):
    calls = []

    def record(payload, method):
        calls.append((method, len(payload)))
        return payload if method == 0 else payload + b"\x00"

    monkeypatch.setattr(core, "_whole_compress", record)
    monkeypatch.setattr(core, "_probe_candidates", lambda payload: ([], False))
    compressed = compress(data, level="best")
    assert decompress(compressed) == data
    for method in ((1, 2, 3) if core.HAVE_ZSTD else (1, 2)):
        assert (method, len(data)) in calls


@pytest.mark.parametrize("level", ["best", "fast"])
def test_deterministic_large_input(level):
    data = b"record,00042,abc\n" * 131072
    first = compress(data, level=level)
    assert first == compress(data, level=level)
    assert decompress(first) == data
