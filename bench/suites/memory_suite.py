"""
MemorySuite v2.0 — benchmark empreinte mémoire.

Mesure :
  - Scalabilité vault (10, 100, 1000 entrées) — linéarité RAM
  - Cache chaud vs froid — ratio speedup
  - Fragmentation mémoire via tracemalloc
  - Empreinte par entrée (objectif: < 1KB/entry)
"""

import os

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult

# Tailles de vault à tester
VAULT_SIZES = [10, 100, 1_000]

# Taille de données par entrée (1KB — simulant un secret chiffré)
ENTRY_SIZE = 1_024

# Clé simulée pour vault
VAULT_KEY = os.urandom(32)


def _create_vault(n_entries: int) -> list[bytes]:
    """Crée un vault de n_entries éléments simulés."""
    return [os.urandom(ENTRY_SIZE) for _ in range(n_entries)]


def _access_vault(vault: list[bytes]) -> int:
    """Simule un accès séquentiel complet du vault."""
    total = 0
    for entry in vault:
        total += len(entry)
    return total


class MemorySuite(BaseSuite):
    NAME = "memory"
    DESCRIPTION = "Scalabilité mémoire vault — tracemalloc + fragmentation"

    def __init__(
        self,
        iterations: int = 3,
        warmup: int = 1,
        vault_sizes: list[int] | None = None,
    ):
        super().__init__(iterations=iterations, warmup=warmup)
        self.vault_sizes = vault_sizes or VAULT_SIZES
        self._timer = TimeCollector()
        self._mem = MemoryCollector()
        self._cpu = CpuCollector()

    def run(self) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []

        # ── 1. Scalabilité vault ──────────────────────────────────────
        for n in self.vault_sizes:
            def _build_vault(n=n):
                return _create_vault(n)

            # Warmup
            for _ in range(2):
                self._mem.measure(_build_vault)

            _, mem = self._mem.measure(_build_vault, label=f"vault-{n}")
            timing = self._timer.measure(_build_vault, iterations=self.iterations, warmup=self.warmup)
            _, cpu = self._cpu.measure(_build_vault, label=f"vault-{n}")

            mb_per_entry = mem.peak_mb / n if n > 0 else 0
            entries_per_sec = n / (timing.mean_ms / 1000) if timing.mean_ms > 0 else 0

            results.append(self._make_result(
                name=f"vault-{n}-entries",
                algorithm="VaultBuild",
                data_size_bytes=n * ENTRY_SIZE,
                mean_ms=timing.mean_ms,
                stddev_ms=timing.stddev_ms,
                min_ms=timing.min_ms,
                max_ms=timing.max_ms,
                p95_ms=timing.p95_ms,
                p99_ms=timing.p99_ms,
                cv_percent=timing.cv_percent,
                throughput_mbps=(n * ENTRY_SIZE / 1_048_576) / (timing.mean_ms / 1000) if timing.mean_ms > 0 else 0,
                peak_mb=mem.peak_mb,
                delta_mb=mem.delta_mb,
                cpu_mean_pct=cpu.cpu_mean_pct,
                cpu_peak_pct=cpu.cpu_peak_pct,
                samples_ns=timing.samples_ns,
                extra={
                    "entry_count": n,
                    "entry_size_bytes": ENTRY_SIZE,
                    "mb_per_entry": round(mb_per_entry, 6),
                    "entries_per_sec": round(entries_per_sec, 0),
                    "fragmentation_pct": round(mem.fragmentation_pct, 2),
                    "linear_scaling": n > 10,  # flag pour vérification linéarité
                },
            ))

        # ── 2. Cache chaud vs froid ───────────────────────────────────
        # Construit un vault de 1000 entrées, mesure 1er accès vs accès suivants
        hot_vault = _create_vault(1_000)

        def _cold_access():
            vault = _create_vault(100)
            return _access_vault(vault)

        def _hot_access(vault=hot_vault):
            return _access_vault(vault)

        cold_timing = self._timer.measure(_cold_access, iterations=max(3, self.iterations // 10), warmup=1)
        hot_timing  = self._timer.measure(_hot_access,  iterations=max(3, self.iterations // 10), warmup=1)

        cache_speedup = cold_timing.mean_ms / hot_timing.mean_ms if hot_timing.mean_ms > 0 else 1.0

        results.append(self._make_result(
            name="cache-analysis-100entries",
            algorithm="CacheEffect",
            data_size_bytes=100 * ENTRY_SIZE,
            mean_ms=hot_timing.mean_ms,
            stddev_ms=hot_timing.stddev_ms,
            min_ms=hot_timing.min_ms,
            max_ms=hot_timing.max_ms,
            p95_ms=hot_timing.p95_ms,
            p99_ms=hot_timing.p99_ms,
            cv_percent=hot_timing.cv_percent,
            throughput_mbps=0.0,
            peak_mb=0.0,
            delta_mb=0.0,
            cpu_mean_pct=0.0,
            cpu_peak_pct=0.0,
            samples_ns=hot_timing.samples_ns,
            extra={
                "cold_ms": round(cold_timing.mean_ms, 4),
                "hot_ms": round(hot_timing.mean_ms, 4),
                "cache_speedup": round(cache_speedup, 2),
                "access_type": "sequential",
            },
        ))

        return results
