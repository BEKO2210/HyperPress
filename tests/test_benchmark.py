"""Synthetic datasets: roundtrip and the v2 size guarantee.

These datasets are self-generated and highly repetitive. They are test
inputs only; v1 used them for marketing numbers, which were misleading.
Real-file numbers come from benchmarks/fair_bench.py.
"""

import bz2
import json
import lzma
import random

from hyperpress import compress, decompress
from hyperpress.core import HAVE_ZSTD


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


def _baseline(data):
    sizes = [
        len(lzma.compress(data, format=lzma.FORMAT_RAW,
                          filters=[{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}])),
        len(bz2.compress(data, 9)),
    ]
    if HAVE_ZSTD:
        from compression import zstd
        sizes.append(len(zstd.compress(data, level=19)))
    return min(sizes)


class TestSyntheticDatasets:

    def setup_method(self):
        self.datasets = gen_data()

    def test_all_datasets_exist(self):
        expected = [
            "English Text", "German Text", "JSON Data", "Sensor Data",
            "Sparse Binary", "Log File", "Pattern+Noise", "Source Code",
        ]
        for name in expected:
            assert name in self.datasets, "Missing dataset: %s" % name

    def test_datasets_have_reasonable_size(self):
        for name, data in self.datasets.items():
            assert len(data) >= 1000, "%s is too small: %d bytes" % (name, len(data))

    def test_all_datasets_roundtrip(self):
        for name, data in self.datasets.items():
            for level in ("best", "fast"):
                assert decompress(compress(data, level=level)) == data, (name, level)

    def test_guarantee_on_every_dataset(self):
        for name, data in self.datasets.items():
            hp = len(compress(data))
            assert hp <= _baseline(data) + 16, (name, hp, _baseline(data))


def test_no_legacy_benchmark_in_library():
    # v1's bench() printed "netto" sizes with the header subtracted.
    import hyperpress.core as core
    assert not hasattr(core, "bench")
    assert not hasattr(core, "gen_data")
