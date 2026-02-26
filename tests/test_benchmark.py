"""Benchmark tests: HyperPress vs zlib-6 vs LZMA on all 8 datasets."""

import time
import zlib
import lzma

from hyperpress import compress, decompress
from hyperpress.core import gen_data


class TestBenchmark:
    """Verify HyperPress beats both zlib-6 and LZMA on aggregate benchmarks."""

    def setup_method(self):
        self.datasets = gen_data()
        assert len(self.datasets) == 8, "Expected 8 benchmark datasets"

    def test_all_datasets_roundtrip(self):
        """Every dataset must compress and decompress correctly."""
        for name, data in self.datasets.items():
            compressed = compress(data)
            restored = decompress(compressed)
            assert restored == data, "Roundtrip failed for: %s" % name

    def test_hyperpress_beats_zlib6_aggregate(self):
        """HyperPress total compressed size must be smaller than zlib-6 total."""
        total_zlib = 0
        total_hp = 0
        for name, data in self.datasets.items():
            total_zlib += len(zlib.compress(data, 6))
            total_hp += len(compress(data))
        assert total_hp < total_zlib, (
            "HyperPress (%d) did not beat zlib-6 (%d) on aggregate" % (total_hp, total_zlib)
        )

    def test_hyperpress_beats_lzma_aggregate(self):
        """HyperPress total compressed size must be smaller than LZMA total."""
        total_lzma = 0
        total_hp = 0
        for name, data in self.datasets.items():
            total_lzma += len(lzma.compress(data))
            total_hp += len(compress(data))
        assert total_hp < total_lzma, (
            "HyperPress (%d) did not beat LZMA (%d) on aggregate" % (total_hp, total_lzma)
        )

    def test_compression_ratios(self):
        """Compute and verify compression ratios are in expected range."""
        total_orig = 0
        total_hp = 0
        for name, data in self.datasets.items():
            total_orig += len(data)
            total_hp += len(compress(data))
        ratio = (1 - total_hp / total_orig) * 100
        # HyperPress should achieve at least 85% compression ratio overall
        assert ratio > 85, "Overall compression ratio %.1f%% is below 85%%" % ratio

    def test_per_dataset_compression_rates(self, capsys):
        """Print per-dataset compression rates and timing."""
        print("\n%-20s %10s %10s %10s %10s" % (
            "Dataset", "Original", "zlib-6", "LZMA", "HyperPress"))
        print("-" * 62)

        for name, data in self.datasets.items():
            orig_size = len(data)

            t0 = time.time()
            zlib_size = len(zlib.compress(data, 6))
            t_zlib = time.time() - t0

            t0 = time.time()
            lzma_size = len(lzma.compress(data))
            t_lzma = time.time() - t0

            t0 = time.time()
            hp_size = len(compress(data))
            t_hp = time.time() - t0

            zlib_ratio = (1 - zlib_size / orig_size) * 100
            lzma_ratio = (1 - lzma_size / orig_size) * 100
            hp_ratio = (1 - hp_size / orig_size) * 100

            print("%-20s %9dB %7.1f%%(%4.0fms) %7.1f%%(%4.0fms) %7.1f%%(%4.0fms)" % (
                name, orig_size,
                zlib_ratio, t_zlib * 1000,
                lzma_ratio, t_lzma * 1000,
                hp_ratio, t_hp * 1000))

    def test_all_datasets_exist(self):
        """Verify all 8 expected datasets are present."""
        expected = [
            "English Text", "German Text", "JSON Data", "Sensor Data",
            "Sparse Binary", "Log File", "Pattern+Noise", "Source Code",
        ]
        for name in expected:
            assert name in self.datasets, "Missing dataset: %s" % name

    def test_datasets_have_reasonable_size(self):
        """Each dataset should be at least 1KB."""
        for name, data in self.datasets.items():
            assert len(data) >= 1000, "%s is too small: %d bytes" % (name, len(data))
