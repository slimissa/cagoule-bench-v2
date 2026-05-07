"""
TimeCollector — mesures temporelles haute précision.

Utilise time.perf_counter_ns() pour une résolution nanoseconde.
Calcule mean, stddev, p95, p99, min, max sur N itérations.
"""

import time
import statistics
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class TimingResult:
    samples_ns: list[int]
    warmup_count: int
    label: str = ""

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.samples_ns) / 1_000_000

    @property
    def stddev_ms(self) -> float:
        return (statistics.stdev(self.samples_ns) / 1_000_000) if len(self.samples_ns) > 1 else 0.0

    @property
    def min_ms(self) -> float:
        return min(self.samples_ns) / 1_000_000

    @property
    def max_ms(self) -> float:
        return max(self.samples_ns) / 1_000_000

    @property
    def p95_ms(self) -> float:
        return self._percentile(95) / 1_000_000

    @property
    def p99_ms(self) -> float:
        return self._percentile(99) / 1_000_000

    def _percentile(self, pct: int) -> float:
        sorted_s = sorted(self.samples_ns)
        idx = int(len(sorted_s) * pct / 100)
        return float(sorted_s[min(idx, len(sorted_s) - 1)])

    def throughput_mbps(self, data_size_bytes: int) -> float:
        """MB/s calculé sur la latence moyenne."""
        if self.mean_ms == 0:
            return 0.0
        return (data_size_bytes / 1_048_576) / (self.mean_ms / 1000)

    @property
    def cv_percent(self) -> float:
        """Coefficient de variation (stddev/mean*100) — indicateur de stabilité."""
        return (self.stddev_ms / self.mean_ms * 100) if self.mean_ms > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "iterations": len(self.samples_ns),
            "warmup": self.warmup_count,
            "mean_ms": round(self.mean_ms, 4),
            "stddev_ms": round(self.stddev_ms, 4),
            "min_ms": round(self.min_ms, 4),
            "max_ms": round(self.max_ms, 4),
            "p95_ms": round(self.p95_ms, 4),
            "p99_ms": round(self.p99_ms, 4),
            "cv_percent": round(self.cv_percent, 2),  # FIXED: removed parentheses
        }


class TimeCollector:
    """
    Exécute une callable N fois (après warmup) et collecte les temps.

    Usage:
        collector = TimeCollector()
        result = collector.measure(lambda: encrypt(data, pwd), iterations=1000, warmup=10)
        print(result.mean_ms, result.p95_ms)
    """

    def measure(
        self,
        fn: Callable,
        iterations: int = 1000,
        warmup: int = 10,
        label: str = "",
    ) -> TimingResult:
        # Phase de warmup — élimine JIT, cache CPU froid, import lazy
        for _ in range(warmup):
            fn()

        # Phase de mesure
        samples: list[int] = []
        for _ in range(iterations):
            t0 = time.perf_counter_ns()
            fn()
            samples.append(time.perf_counter_ns() - t0)

        return TimingResult(samples_ns=samples, warmup_count=warmup, label=label)