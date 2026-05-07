"""
ParallelSuite — benchmark parallélisme ProcessPoolExecutor.

Mesure le speedup du chiffrement parallèle avec 1, 2, 4, 8 workers.
CPU-bound uniquement — GIL non-impactant.

v2.0.0 : CAGOULE réel avec params pré-dérivés (remplace mock XOR).
"""

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult

# Configuration
WORKER_COUNTS = [1, 2, 4, 8]
NUM_OPERATIONS = 200  # Réduit pour cible < 90s (200 × 1 MB = 200 MB)
DATA_SIZE = 1024 * 1024  # 1MB par opération

# Données de test
TEST_DATA = os.urandom(DATA_SIZE)
PASSWORD = b"cagoule-bench-v2-parallel-test"
BENCHMARK_SALT = b'\xca\xf0' * 16  # 32 octets fixes, reproductible

# ── CAGOULE v2.2.0 import ─────────────────────────────────────────────────────

CAGOULE_AVAILABLE = False
CAGOULE_PARAMS = None

try:
    from cagoule import encrypt as cagoule_encrypt
    from cagoule.params import CagouleParams
    CAGOULE_AVAILABLE = True
    # Pré-dérivation UNE SEULE FOIS dans le processus parent
    # Avec fork (Linux), les workers héritent de cette variable
    CAGOULE_PARAMS = CagouleParams.derive_for_benchmark(
        PASSWORD, fast_mode=True, salt=BENCHMARK_SALT
    )
except ImportError:
    def cagoule_encrypt(plaintext: bytes, password: bytes, **kwargs) -> bytes:
        """Fallback mock — NOT real crypto, benchmark harness only."""
        key = password * (len(plaintext) // len(password) + 1)
        return bytes(p ^ k for p, k in zip(plaintext, key[:len(plaintext)]))


def _encrypt_single(_: int) -> bytes:
    """
    Opération de chiffrement individuelle avec CAGOULE réel.
    L'argument _ est ignoré (utilisé pour map avec range).
    
    Re-dérive CagouleParams dans chaque worker pour éviter
    le partage de pointeurs C via fork().
    fast_mode=True (Scrypt ~5ms) est négligeable vs 1MB encryption (~43ms).
    """
    if CAGOULE_AVAILABLE:
        from cagoule.params import CagouleParams
        params = CagouleParams.derive_for_benchmark(
            PASSWORD, fast_mode=True, salt=BENCHMARK_SALT
        )
        return cagoule_encrypt(TEST_DATA, PASSWORD, params=params)
    return cagoule_encrypt(TEST_DATA, PASSWORD)


def run_parallel(workers: int, num_ops: int) -> tuple[float, float]:
    """
    Exécute num_ops opérations en parallèle avec workers processus.
    
    Returns:
        (duration_seconds, cpu_percent_avg)
    """
    import psutil
    
    process = psutil.Process()
    cpu_before = process.cpu_percent(interval=None)
    
    start = time.perf_counter()
    
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # Soumettre toutes les tâches
        futures = [executor.submit(_encrypt_single, i) for i in range(num_ops)]
        
        # Attendre la completion
        results = []
        for future in as_completed(futures):
            results.append(future.result())
    
    duration = time.perf_counter() - start
    
    cpu_after = process.cpu_percent(interval=None)
    cpu_avg = (cpu_before + cpu_after) / 2
    
    return duration, cpu_avg


def run_sequential(num_ops: int) -> float:
    """Exécution séquentielle (baseline pour speedup)."""
    start = time.perf_counter()
    for i in range(num_ops):
        _encrypt_single(i)
    return time.perf_counter() - start


class ParallelSuite(BaseSuite):
    NAME = "parallel"
    DESCRIPTION = "ProcessPoolExecutor scaling — chiffrement CPU-bound"

    def __init__(
        self,
        iterations: int = 3,  # 3 runs par configuration pour stabilité
        warmup: int = 1,
        worker_counts: list[int] | None = None,
        num_operations: int = NUM_OPERATIONS,
        total_ops: int | None = None,  # Alias pour compatibilité tests
    ):
        super().__init__(iterations=iterations, warmup=warmup)
        # Support both parameter names (for test compatibility)
        if total_ops is not None:
            num_operations = total_ops
        self.worker_counts = worker_counts or WORKER_COUNTS
        self.num_operations = num_operations
        self._timer = TimeCollector()
        self._mem = MemoryCollector()
        self._cpu = CpuCollector()

    def run(self) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        
        # ── 1. Baseline séquentielle (workers=1) ──────────────────────
        def _sequential():
            return run_sequential(self.num_operations)
        
        # Mesure baseline
        seq_duration = self._timer.measure(
            _sequential,
            iterations=self.iterations,
            warmup=self.warmup,
            label="sequential-baseline",
        )
        
        baseline_time_ms = seq_duration.mean_ms
        
        results.append(self._make_result(
            name=f"sequential-{self.num_operations}ops",
            algorithm="CAGOULE-Sequential" if CAGOULE_AVAILABLE else "CAGOULE-Mock-Sequential",
            data_size_bytes=self.num_operations * DATA_SIZE,
            mean_ms=baseline_time_ms,
            stddev_ms=seq_duration.stddev_ms,
            min_ms=seq_duration.min_ms,
            max_ms=seq_duration.max_ms,
            p95_ms=seq_duration.p95_ms,
            p99_ms=seq_duration.p99_ms,
            cv_percent=seq_duration.cv_percent,
            throughput_mbps=(self.num_operations * DATA_SIZE / 1_048_576) / (baseline_time_ms / 1000),
            peak_mb=0.0,
            delta_mb=0.0,
            cpu_mean_pct=0.0,
            cpu_peak_pct=0.0,
            samples_ns=seq_duration.samples_ns,
            extra={
                "workers": 1,
                "num_operations": self.num_operations,
                "data_size_mb": DATA_SIZE / 1_048_576,
                "is_baseline": True,
                "cagoule_available": CAGOULE_AVAILABLE,
            },
        ))
        
        # ── 2. Tests parallèles pour chaque nombre de workers ──────────
        for workers in self.worker_counts:
            if workers == 1:
                continue  # Déjà fait comme baseline
                
            label = f"workers-{workers}"
            
            def _parallel():
                duration, _ = run_parallel(workers, self.num_operations)
                return duration
            
            # Mesure mémoire
            _, mem = self._mem.measure(_parallel, label=label)
            
            # Mesure timing
            timing = self._timer.measure(
                _parallel,
                iterations=self.iterations,
                warmup=self.warmup,
                label=label,
            )
            
            # Mesure CPU
            _, cpu = self._cpu.measure(_parallel, label=label)
            
            # Calcul du speedup
            speedup_ratio = baseline_time_ms / timing.mean_ms if timing.mean_ms > 0 else 1.0
            parallel_efficiency = (speedup_ratio / workers) * 100
            
            # Throughput total (MB/s agrégé)
            total_data_mb = (self.num_operations * DATA_SIZE) / 1_048_576
            throughput_mbps = total_data_mb / (timing.mean_ms / 1000)
            
            results.append(self._make_result(
                name=f"parallel-{self.num_operations}ops-{workers}workers",
                algorithm=f"CAGOULE-Parallel-{workers}w" if CAGOULE_AVAILABLE else f"CAGOULE-Mock-Parallel-{workers}w",
                data_size_bytes=self.num_operations * DATA_SIZE,
                mean_ms=timing.mean_ms,
                stddev_ms=timing.stddev_ms,
                min_ms=timing.min_ms,
                max_ms=timing.max_ms,
                p95_ms=timing.p95_ms,
                p99_ms=timing.p99_ms,
                cv_percent=timing.cv_percent,
                throughput_mbps=throughput_mbps,
                peak_mb=mem.peak_mb,
                delta_mb=mem.delta_mb,
                cpu_mean_pct=cpu.cpu_mean_pct,
                cpu_peak_pct=cpu.cpu_peak_pct,
                samples_ns=timing.samples_ns,
                extra={
                    "workers": workers,
                    "num_operations": self.num_operations,
                    "data_size_mb": DATA_SIZE / 1_048_576,
                    "speedup_ratio": round(speedup_ratio, 3),
                    "parallel_efficiency_pct": round(parallel_efficiency, 1),
                    "ops_per_sec": round(self.num_operations / (timing.mean_ms / 1000), 0),
                    "is_baseline": False,
                    "cagoule_available": CAGOULE_AVAILABLE,
                },
            ))
        
        # ── 3. ThreadPoolExecutor — Preuve empirique GIL ──────────────
        # La roadmap v2.0.0 §4.1.2 exige cette section pour publication
        from concurrent.futures import ThreadPoolExecutor
        
        for workers in [2, 4, 8]:
            def _thread_pool():
                start = time.perf_counter()
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    list(pool.map(_encrypt_single, range(self.num_operations)))
                return time.perf_counter() - start
            
            thread_timing = self._timer.measure(
                _thread_pool,
                iterations=max(2, self.iterations // 2),
                warmup=1,
                label=f"thread-pool-{workers}w",
            )
            
            thread_speedup = baseline_time_ms / thread_timing.mean_ms if thread_timing.mean_ms > 0 else 1.0
            
            results.append(self._make_result(
                name=f"thread-pool-{workers}workers",
                algorithm="ThreadPoolExecutor",
                data_size_bytes=self.num_operations * DATA_SIZE,
                mean_ms=thread_timing.mean_ms,
                stddev_ms=thread_timing.stddev_ms,
                min_ms=thread_timing.min_ms,
                max_ms=thread_timing.max_ms,
                p95_ms=thread_timing.p95_ms,
                p99_ms=thread_timing.p99_ms,
                cv_percent=thread_timing.cv_percent,
                throughput_mbps=total_data_mb / (thread_timing.mean_ms / 1000),
                peak_mb=0.0,
                delta_mb=0.0,
                cpu_mean_pct=0.0,
                cpu_peak_pct=0.0,
                samples_ns=thread_timing.samples_ns,
                extra={
                    "workers": workers,
                    "pool_type": "ThreadPoolExecutor",
                    "speedup_ratio": round(thread_speedup, 3),
                    "gil_impact": "speedup ≈ 1.0 attendu (GIL)",
                    "note": "ThreadPoolExecutor est INVALIDE pour benchmarks académiques — inclus comme preuve empirique de l'impact du GIL",
                },
            ))
        
        return results

    def measure_speedup_curve(self) -> dict:
        """
        Mesure la courbe de speedup complète pour analyse académique.
        Retourne les données pour publication (tableau/plot).
        """
        results = {}
        
        # Baseline
        seq_time = run_sequential(self.num_operations)
        results[1] = {"time_ms": seq_time * 1000, "speedup": 1.0, "efficiency": 100.0}
        
        # Tests parallèles
        for workers in self.worker_counts:
            if workers == 1:
                continue
            
            # Moyenne sur iterations
            times = []
            for _ in range(self.iterations):
                duration, _ = run_parallel(workers, self.num_operations)
                times.append(duration)
            
            avg_time = sum(times) / len(times)
            speedup = seq_time / avg_time
            
            results[workers] = {
                "time_ms": avg_time * 1000,
                "speedup": round(speedup, 3),
                "efficiency": round((speedup / workers) * 100, 1),
            }
        
        return results

    def get_optimal_workers(self) -> int:
        """
        Détermine le nombre optimal de workers basé sur la courbe de speedup.
        Utile pour les recommandations de déploiement.
        """
        curve = self.measure_speedup_curve()
        
        optimal = 1
        best_efficiency = 100.0
        
        for workers, metrics in curve.items():
            if metrics["efficiency"] > best_efficiency and metrics["efficiency"] > 70:
                best_efficiency = metrics["efficiency"]
                optimal = workers
        
        return optimal