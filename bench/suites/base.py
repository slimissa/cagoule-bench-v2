"""
bench/suites/base.py — Interface abstraite pour toutes les suites.

v2.0 : BenchmarkResult enrichi avec :
  - samples_ns: liste des mesures brutes (pour Mann-Whitney U)
  - arch: détection automatique x86_64 / arm64
  - has_aes_ni: présence AES-NI hardware (impact benchmarks)
  - run_id: UUID pour lien avec l'historique SQLite
"""

from __future__ import annotations

import platform
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def _detect_arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "x86_64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return m


def _detect_aes_ni() -> bool:
    """Détecte AES-NI sur x86_64 via /proc/cpuinfo (Linux)."""
    try:
        # BUG6 FIX: with + encoding explicite → plus de file handle leak
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            return "aes" in f.read()
    except Exception:
        return platform.machine().lower() in ("x86_64", "amd64")


@dataclass
class BenchmarkResult:
    """Résultat structuré d'un benchmark individuel — v2.0."""

    suite: str
    name: str
    algorithm: str
    data_size_bytes: int = 0
    iterations: int = 0
    warmup: int = 0

    # Métriques temps
    mean_ms: float = 0.0
    stddev_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    cv_percent: float = 0.0

    # Débit
    throughput_mbps: float = 0.0

    # Mémoire
    peak_mb: float = 0.0
    delta_mb: float = 0.0

    # CPU
    cpu_mean_pct: float = 0.0
    cpu_peak_pct: float = 0.0

    # v2.0 — Samples bruts (pour comparaisons statistiques)
    samples_ns: list[int] = field(default_factory=list, repr=False)

    # v2.0 — Metadata enrichie
    platform: str = field(default_factory=lambda: platform.machine())
    arch: str = field(default_factory=_detect_arch)
    has_aes_ni: bool = field(default_factory=_detect_aes_ni)
    python_version: str = field(default_factory=lambda: platform.python_version())
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    extra: dict = field(default_factory=dict)

    def overhead_vs(self, other: "BenchmarkResult") -> float:
        """Overhead en % par rapport à un autre résultat."""
        if other.throughput_mbps == 0:
            return 0.0
        return (self.throughput_mbps - other.throughput_mbps) / other.throughput_mbps * 100

    def samples_ms(self) -> list[float]:
        """Convertit samples_ns → ms pour analyses statistiques."""
        return [s / 1_000_000 for s in self.samples_ns]

    def to_dict(self) -> dict:
        return {
            "suite": self.suite,
            "name": self.name,
            "algorithm": self.algorithm,
            "data_size_bytes": self.data_size_bytes,
            "iterations": self.iterations,
            "warmup": self.warmup,
            "timing": {
                "mean_ms": round(self.mean_ms, 4),
                "stddev_ms": round(self.stddev_ms, 4),
                "min_ms": round(self.min_ms, 4),
                "max_ms": round(self.max_ms, 4),
                "p95_ms": round(self.p95_ms, 4),
                "p99_ms": round(self.p99_ms, 4),
                "cv_percent": round(self.cv_percent, 2),
            },
            "throughput_mbps": round(self.throughput_mbps, 3),
            "memory": {
                "peak_mb": round(self.peak_mb, 4),
                "delta_mb": round(self.delta_mb, 4),
            },
            "cpu": {
                "mean_pct": round(self.cpu_mean_pct, 2),
                "peak_pct": round(self.cpu_peak_pct, 2),
            },
            "meta": {
                "platform": self.platform,
                "arch": self.arch,
                "has_aes_ni": self.has_aes_ni,
                "python_version": self.python_version,
                "timestamp": self.timestamp,
                "run_id": self.run_id,
            },
            "extra": self.extra,
        }


class BaseSuite(ABC):
    """Interface abstraite pour les suites de benchmarks."""

    NAME: str = "base"
    DESCRIPTION: str = ""

    def __init__(self, iterations: int = 1000, warmup: int = 10):
        self.iterations = iterations
        self.warmup = warmup

    @abstractmethod
    def run(self) -> list[BenchmarkResult]:
        """Exécute la suite et retourne les résultats."""

    def _make_result(self, name: str, algorithm: str, **kwargs) -> BenchmarkResult:
        return BenchmarkResult(
            suite=self.NAME,
            name=name,
            algorithm=algorithm,
            iterations=self.iterations,
            warmup=self.warmup,
            **kwargs,
        )
