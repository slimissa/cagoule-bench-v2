"""
cagoule-bench v2.0.0 — Suite de benchmarking académique pour CAGOULE.

Nouveautés v2.0 :
  - Config file support (cagoule_bench.toml / pyproject.toml)
  - SQLite history database + trend detection
  - Statistical comparison (Mann-Whitney U + effect size)
  - StreamingSuite — large-file streaming benchmarks
  - scrypt dans KdfSuite
  - Notebook reporter (Jupyter .ipynb)
  - CLI : history, profile, compare-history
  - HTML dashboard : dark mode, filtres, delta vs baseline
  - CAGOULE v2.1 API compatibility
"""

__version__ = "2.0.0"

from bench.db.history import HistoryDB, RunRecord
from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.metrics.stats import MannWhitneyResult, StatComparison
from bench.reporters import (
    ConsoleReporter,
    CsvReporter,
    HtmlReporter,
    JsonReporter,
    MarkdownReporter,
)
from bench.suites import (
    ALL_SUITES,
    BaseSuite,
    BenchmarkResult,
    EncryptionSuite,
    KdfSuite,
    MemorySuite,
    ParallelSuite,
    StreamingSuite,
)

__all__ = [
    # Version
    "__version__",
    # Metrics
    "TimeCollector",
    "MemoryCollector",
    "CpuCollector",
    "StatComparison",
    "MannWhitneyResult",
    # Suites
    "BaseSuite",
    "BenchmarkResult",
    "EncryptionSuite",
    "KdfSuite",
    "MemorySuite",
    "ParallelSuite",
    "StreamingSuite",
    "ALL_SUITES",
    # Reporters
    "ConsoleReporter",
    "JsonReporter",
    "CsvReporter",
    "MarkdownReporter",
    "HtmlReporter",
    # DB
    "HistoryDB",
    "RunRecord",
]
