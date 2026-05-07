"""
KdfSuite v2.0 — benchmark des paramètres KDF.

Nouveautés v2.0 :
  - scrypt (hashlib) ajouté comme troisième comparatif
  - Samples bruts stockés pour comparaisons statistiques
  - Security score enrichi (entropie résistance GPU)
  - Paramètres configurables depuis BenchConfig

Algorithmes :
  - Argon2id (27 combinaisons t × m × p)
  - PBKDF2-SHA256 (3 niveaux)
  - scrypt (3 configurations)
"""

import hashlib
import itertools
import math
import os

from argon2.low_level import Type, hash_secret_raw

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult

PASSWORD = b"cagoule-bench-kdf-v2-test-password"
SALT = os.urandom(16)

# Grille Argon2id
TIME_COSTS   = [1, 3, 5]
MEMORY_COSTS = [16_384, 65_536, 131_072]   # KiB : 16MB, 64MB, 128MB
PARALLELISM  = [1, 2, 4]

# PBKDF2 comparatifs
PBKDF2_ITERATIONS = [100_000, 300_000, 600_000]

# scrypt configurations (N, r, p) — OWASP recommended + minimal
SCRYPT_CONFIGS = [
    (16_384,  8, 1),   # N=2^14 — minimal (interactive, fast)
    (65_536,  8, 1),   # N=2^16 — recommended (interactive, secure)
    (131_072, 8, 2),   # N=2^17 — paranoid (offline, high-security)
]


class KdfSuite(BaseSuite):
    NAME = "kdf"
    DESCRIPTION = "Argon2id grid + PBKDF2-SHA256 + scrypt comparison"

    def __init__(
        self,
        iterations: int = 5,
        warmup: int = 1,
        time_costs: list[int] | None = None,
        memory_costs: list[int] | None = None,
        parallelism: list[int] | None = None,
        include_scrypt: bool = True,
    ):
        super().__init__(iterations=iterations, warmup=warmup)
        self.time_costs   = time_costs   or TIME_COSTS
        self.memory_costs = memory_costs or MEMORY_COSTS
        self.parallelism  = parallelism  or PARALLELISM
        self.include_scrypt = include_scrypt
        self._timer = TimeCollector()
        self._mem   = MemoryCollector()
        self._cpu   = CpuCollector()

    def run(self) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []

        # ── Argon2id grid ─────────────────────────────────────────────
        combos = list(itertools.product(self.time_costs, self.memory_costs, self.parallelism))
        for t, m, p in combos:
            m_mb = m // 1024
            label = f"t={t},m={m_mb}MB,p={p}"

            def _argon2(t=t, m=m, p=p):
                return hash_secret_raw(
                    secret=PASSWORD, salt=SALT,
                    time_cost=t, memory_cost=m, parallelism=p,
                    hash_len=32, type=Type.ID,
                )

            for _ in range(2):
                self._mem.measure(_argon2)
            _, mem = self._mem.measure(_argon2, label=f"argon2id-{label}")
            timing = self._timer.measure(_argon2, iterations=self.iterations, warmup=self.warmup, label=label)
            _, cpu = self._cpu.measure(_argon2, label=f"argon2id-{label}")

            # GPU resistance: Argon2id needs m_cost RAM per thread → GPU parallelism blocked
            gpu_resistance = round(math.log2(m * p), 1)  # log2(RAM × threads)
            security_score = round(math.log2(t * m * p), 1)

            results.append(self._make_result(
                name=f"argon2id-{label}",
                algorithm="Argon2id",
                data_size_bytes=0,
                mean_ms=timing.mean_ms,
                stddev_ms=timing.stddev_ms,
                min_ms=timing.min_ms,
                max_ms=timing.max_ms,
                p95_ms=timing.p95_ms,
                p99_ms=timing.p99_ms,
                cv_percent=timing.cv_percent,
                throughput_mbps=0.0,
                peak_mb=mem.peak_mb,
                delta_mb=mem.delta_mb,
                cpu_mean_pct=cpu.cpu_mean_pct,
                cpu_peak_pct=cpu.cpu_peak_pct,
                samples_ns=timing.samples_ns,
                extra={
                    "t_cost": t,
                    "m_cost_mb": m_mb,
                    "parallelism": p,
                    "security_score": security_score,
                    "gpu_resistance": gpu_resistance,
                    "type": "Argon2id",
                    "owasp_compliant": (t >= 3 and m_mb >= 64),
                },
            ))

        # ── PBKDF2-SHA256 ─────────────────────────────────────────────
        for iters in PBKDF2_ITERATIONS:
            label = f"pbkdf2-sha256-{iters // 1000}k"

            def _pbkdf2(iters=iters):
                return hashlib.pbkdf2_hmac("sha256", PASSWORD, SALT, iters, dklen=32)

            for _ in range(2):
                self._mem.measure(_pbkdf2)
            _, mem = self._mem.measure(_pbkdf2, label=label)
            timing = self._timer.measure(_pbkdf2, iterations=self.iterations, warmup=self.warmup, label=label)
            _, cpu = self._cpu.measure(_pbkdf2, label=label)

            results.append(self._make_result(
                name=label,
                algorithm="PBKDF2-SHA256",
                data_size_bytes=0,
                mean_ms=timing.mean_ms,
                stddev_ms=timing.stddev_ms,
                min_ms=timing.min_ms,
                max_ms=timing.max_ms,
                p95_ms=timing.p95_ms,
                p99_ms=timing.p99_ms,
                cv_percent=timing.cv_percent,
                throughput_mbps=0.0,
                peak_mb=mem.peak_mb,
                delta_mb=mem.delta_mb,
                cpu_mean_pct=cpu.cpu_mean_pct,
                cpu_peak_pct=cpu.cpu_peak_pct,
                samples_ns=timing.samples_ns,
                extra={
                    "iterations": iters,
                    "security_score": round(math.log2(iters), 1),
                    "gpu_resistance": 0.0,  # PBKDF2 has no memory hardness → GPU vulnerable
                    "type": "PBKDF2-SHA256",
                    "owasp_compliant": iters >= 600_000,
                },
            ))

        # ── scrypt (v2.0 new) ─────────────────────────────────────────
        if self.include_scrypt:
            for N, r, p in SCRYPT_CONFIGS:
                label = f"scrypt-N{N//1024}k-r{r}-p{p}"
                mem_usage_mb = round((128 * N * r * p) / 1_048_576, 1)

                def _scrypt(N=N, r=r, p=p):
                    return hashlib.scrypt(PASSWORD, salt=SALT, n=N, r=r, p=p, dklen=32)

                try:
                    for _ in range(2):
                        self._mem.measure(_scrypt)
                    _, mem = self._mem.measure(_scrypt, label=label)
                    timing = self._timer.measure(_scrypt, iterations=self.iterations, warmup=self.warmup, label=label)
                    _, cpu = self._cpu.measure(_scrypt, label=label)
                except (ValueError, MemoryError, OSError) as e:
                    # scrypt memory limit exceeded (OpenSSL/sandbox constraint)
                    # Mark as failed and continue — do not crash the suite
                    results.append(self._make_result(
                        name=label, algorithm="scrypt",
                        extra={
                            "N": N, "r": r, "p": p,
                            "memory_mb_theoretical": mem_usage_mb,
                            "security_score": security_score,
                            "gpu_resistance": round(math.log2(N * r), 1),
                            "type": "scrypt",
                            "owasp_compliant": N >= 65_536,
                            "error": str(e),
                            "skipped": True,
                        },
                    ))
                    continue

                # scrypt security score: log2(N * r * p)
                security_score = round(math.log2(N * r * p), 1)

                results.append(self._make_result(
                    name=label,
                    algorithm="scrypt",
                    data_size_bytes=0,
                    mean_ms=timing.mean_ms,
                    stddev_ms=timing.stddev_ms,
                    min_ms=timing.min_ms,
                    max_ms=timing.max_ms,
                    p95_ms=timing.p95_ms,
                    p99_ms=timing.p99_ms,
                    cv_percent=timing.cv_percent,
                    throughput_mbps=0.0,
                    peak_mb=mem.peak_mb,
                    delta_mb=mem.delta_mb,
                    cpu_mean_pct=cpu.cpu_mean_pct,
                    cpu_peak_pct=cpu.cpu_peak_pct,
                    samples_ns=timing.samples_ns,
                    extra={
                        "N": N,
                        "r": r,
                        "p": p,
                        "memory_mb_theoretical": mem_usage_mb,
                        "security_score": security_score,
                        "gpu_resistance": round(math.log2(N * r), 1),
                        "type": "scrypt",
                        "owasp_compliant": N >= 65_536,
                    },
                ))

        return results
