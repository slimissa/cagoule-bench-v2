"""
MemoryCollector — mesures d'empreinte mémoire via tracemalloc.

Isole les allocations Python générées par une opération.
Retourne peak, delta, nombre d'allocations, fragmentation estimée.
"""

import tracemalloc
from dataclasses import dataclass
from typing import Any, Callable, List  # FIXED: Added List import


@dataclass
class MemoryResult:
    peak_bytes: int
    delta_bytes: int
    alloc_count: int
    label: str = ""

    @property
    def peak_mb(self) -> float:
        return self.peak_bytes / 1_048_576

    @property
    def delta_mb(self) -> float:
        return self.delta_bytes / 1_048_576

    @property
    def fragmentation_pct(self) -> float:
        """Estimation : ratio (peak - delta) / peak."""
        if self.peak_bytes == 0:
            return 0.0
        return (self.peak_bytes - self.delta_bytes) / self.peak_bytes * 100

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "peak_mb": round(self.peak_mb, 4),
            "delta_mb": round(self.delta_mb, 4),
            "alloc_count": self.alloc_count,
            "fragmentation_pct": round(self.fragmentation_pct, 2),
        }


class MemoryCollector:
    """
    Mesure les allocations mémoire d'une callable via tracemalloc.

    Usage:
        collector = MemoryCollector()
        result = collector.measure(lambda: create_vault(1000), label="vault-1000")
        print(result.peak_mb, result.delta_mb)
    """

    def measure(self, fn: Callable, label: str = "") -> tuple[Any, MemoryResult]:
        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()

        return_value = fn()

        snap_after = tracemalloc.take_snapshot()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        stats = snap_after.compare_to(snap_before, "lineno")
        delta = sum(s.size_diff for s in stats if s.size_diff > 0)
        alloc_count = sum(1 for s in stats if s.count_diff > 0)

        result = MemoryResult(
            peak_bytes=peak,
            delta_bytes=delta,
            alloc_count=alloc_count,
            label=label,
        )
        return return_value, result

    def measure_scaling(
        self,
        fn_factory: Callable[[int], Callable],
        counts: List[int],  # FIXED: Use List from typing
        label_prefix: str = "",
    ) -> List[MemoryResult]:  # FIXED: Return type annotation
        """
        Mesure la scalabilité mémoire pour une liste de tailles.
        fn_factory(n) doit retourner une callable sans args.
        """
        results = []
        for n in counts:
            _, mem = self.measure(fn_factory(n), label=f"{label_prefix}{n}")
            results.append(mem)
        return results