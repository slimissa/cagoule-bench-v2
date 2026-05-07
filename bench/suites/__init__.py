"""bench/suites — suites de benchmarks."""

from bench.suites.base import BaseSuite, BenchmarkResult
from bench.suites.encryption_suite import EncryptionSuite
from bench.suites.kdf_suite import KdfSuite
from bench.suites.memory_suite import MemorySuite
from bench.suites.parallel_suite import ParallelSuite
from bench.suites.streaming_suite import StreamingSuite
from bench.suites.avx2_suite import AVX2Suite

ALL_SUITES = {
    "encryption": EncryptionSuite,
    "kdf": KdfSuite,
    "memory": MemorySuite,
    "parallel": ParallelSuite,
    "streaming": StreamingSuite,
    "avx2": AVX2Suite,
}

__all__ = [
    "BaseSuite",
    "BenchmarkResult",
    "EncryptionSuite",
    "KdfSuite",
    "MemorySuite",
    "ParallelSuite",
    "StreamingSuite",
    "AVX2Suite",
    "ALL_SUITES",
]
