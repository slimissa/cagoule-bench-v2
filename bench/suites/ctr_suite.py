"""
CTRSuite v1.0 — benchmarks spécifiques au mode CTR CAGOULE v3.0.0.

Mesures couvertes :
  1. CTR vs CBC — gain de débit sur toutes les tailles (le chiffre central du roadmap)
  2. 4x vs 1x pipeline — gain ILP des 4 blocs simultanés (C-layer uniquement)
  3. CT overhead ratio — |CT| / |PT| : 0 bytes padding CTR vs PKCS7 CBC
  4. Symétrie CTR — débit encrypt == decrypt (test qualitatif)
  5. migrate_cbc_to_ctr — coût de migration par message
  6. encrypt_bulk_ctr — amortissement KDF sur N messages

Cette suite est le miroir benchmark du roadmap v3.0.0 :
  - Cible C-layer   : >25 MB/s (vs 10.8 MB/s en v2.5.x)
  - Cible Python e2e: >15 MB/s (vs 6.9 MB/s en v2.5.x)
  - Cible parallel  : >80 MB/s (20 cœurs, encrypt_bulk_ctr)

Compatibilité : CAGOULE >= 3.0.0. Si v3.0.0 non disponible, tous les tests
retournent un résultat avec extra{"skipped": True, "reason": "..."}.
"""
from __future__ import annotations

import os

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult, _detect_arch

BENCHMARK_SALT = b"\xca\xf0" * 16
PASSWORD = b"cagoule-bench-v2-ctr-suite"

# ── CAGOULE v3.0.0 import ──────────────────────────────────────────────────────
CAGOULE_AVAILABLE = False
CAGOULE_V30 = False
CAGOULE_PARAMS = False

try:
    from cagoule import (
        encrypt_ctr, decrypt_ctr,
        encrypt_cbc, decrypt_cbc,
        encrypt_bulk_ctr,
        migrate_cbc_to_ctr,
    )
    CAGOULE_V30 = True

    try:
        from cagoule.params import CagouleParams
        CAGOULE_PARAMS = True
    except ImportError:
        pass

    CAGOULE_AVAILABLE = True

except ImportError:
    CAGOULE_V30 = False


DEFAULT_SIZES = [1_024, 8_192, 65_536, 1_048_576, 10_485_760]


def _skip(name: str, reason: str) -> BenchmarkResult:
    return BenchmarkResult(
        suite="ctr", name=name, algorithm="CAGOULE-CTR",
        extra={"skipped": True, "reason": reason,
               "fix": "pip install cagoule>=3.0.0"},
    )


class CTRSuite(BaseSuite):
    NAME = "ctr"
    DESCRIPTION = (
        "CAGOULE v3.0.0 — CTR vs CBC débit, 4x pipeline, overhead CT, "
        "symétrie, migration, bulk"
    )

    def __init__(self, iterations: int = 200, warmup: int = 5,
                 sizes: list[int] | None = None):
        super().__init__(iterations=iterations, warmup=warmup)
        self.sizes = sizes or DEFAULT_SIZES
        self._timer = TimeCollector()
        self._mem   = MemoryCollector()
        self._cpu   = CpuCollector()
        self._arch  = _detect_arch()

        # Pré-dérivation paramètres (une seule fois)
        self._params = None
        if CAGOULE_AVAILABLE and CAGOULE_V30 and CAGOULE_PARAMS:
            try:
                self._params = CagouleParams.derive_for_benchmark(
                    PASSWORD, fast_mode=False, salt=BENCHMARK_SALT
                )
            except Exception:
                pass

    # ── API interne ────────────────────────────────────────────────────────────

    def _kw(self):
        return {"params": self._params} if self._params else {}

    def _bench(self, name: str, algorithm: str, op, data_size: int,
               extra: dict | None = None) -> list[BenchmarkResult]:
        for _ in range(3):
            self._mem.measure(op)
        _, mem = self._mem.measure(op, label=f"{algorithm}-{name}")
        timing  = self._timer.measure(op, iterations=self.iterations,
                                      warmup=self.warmup, label=f"{algorithm}-{name}")
        _, cpu  = self._cpu.measure(op, label=f"{algorithm}-{name}")

        base_extra = {
            "cagoule_v30": CAGOULE_V30,
            "params_precomputed": self._params is not None,
            "arch": self._arch,
        }
        if extra:
            base_extra.update(extra)

        return [self._make_result(
            name=name, algorithm=algorithm, data_size_bytes=data_size,
            mean_ms=timing.mean_ms, stddev_ms=timing.stddev_ms,
            min_ms=timing.min_ms, max_ms=timing.max_ms,
            p95_ms=timing.p95_ms, p99_ms=timing.p99_ms,
            cv_percent=timing.cv_percent,
            throughput_mbps=timing.throughput_mbps(data_size),
            peak_mb=mem.peak_mb, delta_mb=mem.delta_mb,
            cpu_mean_pct=cpu.cpu_mean_pct, cpu_peak_pct=cpu.cpu_peak_pct,
            samples_ns=timing.samples_ns,
            extra=base_extra,
        )]

    @staticmethod
    def _fmt(size: int) -> str:
        if size < 1024: return f"{size}B"
        if size < 1_048_576: return f"{size // 1024}KB"
        return f"{size // 1_048_576}MB"

    # ── Benchmark sections ─────────────────────────────────────────────────────

    def _bench_ctr_vs_cbc(self) -> list[BenchmarkResult]:
        """Section 1 — CTR vs CBC sur toutes les tailles."""
        results = []
        kw = self._kw()

        for size in self.sizes:
            pt = os.urandom(size)
            label = self._fmt(size)

            cbc_ct = encrypt_cbc(pt, PASSWORD, **kw)
            ctr_ct = encrypt_ctr(pt, PASSWORD, **kw)

            cbc_overhead = len(cbc_ct) - size
            ctr_overhead = len(ctr_ct) - size

            extra_ctr = {
                "mode": "ctr",
                "ct_overhead_bytes": ctr_overhead,
                "ct_overhead_vs_cbc_bytes": cbc_overhead - ctr_overhead,
                "target_mbps": 15.0,
            }
            extra_cbc = {
                "mode": "cbc",
                "ct_overhead_bytes": cbc_overhead,
                "pkcs7_padding_bytes": cbc_overhead - ctr_overhead,
            }

            results += self._bench(f"ctr-encrypt-{label}", "CAGOULE-CTR",
                lambda pt=pt, kw=kw: encrypt_ctr(pt, PASSWORD, **kw),
                size, extra_ctr)
            results += self._bench(f"cbc-encrypt-{label}", "CAGOULE-CBC",
                lambda pt=pt, kw=kw: encrypt_cbc(pt, PASSWORD, **kw),
                size, extra_cbc)
            results += self._bench(f"ctr-decrypt-{label}", "CAGOULE-CTR",
                lambda ct=ctr_ct, kw=kw: decrypt_ctr(ct, PASSWORD, **kw),
                size, {"mode": "ctr"})
            results += self._bench(f"cbc-decrypt-{label}", "CAGOULE-CBC",
                lambda ct=cbc_ct, kw=kw: decrypt_cbc(ct, PASSWORD, **kw),
                size, {"mode": "cbc"})

        return results

    def _bench_4x_vs_1x(self) -> list[BenchmarkResult]:
        """Section 2 — Pipeline 4x auto-dispatch."""
        results = []
        kw = self._kw()
        sizes_4x = [128, 4_096, 65_536, 1_048_576]

        for size in sizes_4x:
            pt = os.urandom(size)
            label = self._fmt(size)
            above_threshold = size >= 128

            results += self._bench(
                f"ctr-auto-{label}", "CAGOULE-CTR-auto",
                lambda pt=pt, kw=kw: encrypt_ctr(pt, PASSWORD, **kw),
                size,
                {
                    "pipeline": "4x_auto" if above_threshold else "1x_scalar",
                    "above_4x_threshold": above_threshold,
                }
            )

        return results

    def _bench_symmetry(self) -> list[BenchmarkResult]:
        """Section 3 — Symétrie CTR encrypt = decrypt."""
        results = []
        kw = self._kw()

        for size in [65_536, 1_048_576]:
            pt = os.urandom(size)
            ct = encrypt_ctr(pt, PASSWORD, **kw)
            label = self._fmt(size)

            r_enc = self._bench(
                f"ctr-sym-encrypt-{label}", "CAGOULE-CTR-symmetry-enc",
                lambda pt=pt, kw=kw: encrypt_ctr(pt, PASSWORD, **kw),
                size, {"direction": "encrypt"}
            )
            r_dec = self._bench(
                f"ctr-sym-decrypt-{label}", "CAGOULE-CTR-symmetry-dec",
                lambda ct=ct, kw=kw: decrypt_ctr(ct, PASSWORD, **kw),
                size, {"direction": "decrypt"}
            )
            results += r_enc + r_dec

            if r_enc and r_dec:
                enc_tp = r_enc[0].throughput_mbps
                dec_tp = r_dec[0].throughput_mbps
                ratio = dec_tp / enc_tp if enc_tp > 0 else 0.0
                r_enc[0].extra["symmetry_ratio_dec_enc"] = round(ratio, 3)
                r_enc[0].extra["symmetry_ok"] = 0.90 <= ratio <= 1.10

        return results

    def _bench_migration(self) -> list[BenchmarkResult]:
        """Section 4 — migrate_cbc_to_ctr() cost."""
        results = []

        for size in [1_024, 65_536, 1_048_576]:
            pt = os.urandom(size)
            label = self._fmt(size)
            cbc_ct = encrypt_cbc(pt, PASSWORD)

            results += self._bench(
                f"migrate-cbc-ctr-{label}", "CAGOULE-migrate",
                lambda ct=cbc_ct: migrate_cbc_to_ctr(ct, PASSWORD),
                size,
                {
                    "src_version": "0x01 (CBC)",
                    "dst_version": "0x02 (CTR)",
                    "total_kdf_calls": 2,
                }
            )

        return results

    def _bench_bulk_ctr(self) -> list[BenchmarkResult]:
        """
        Section 5 — encrypt_bulk_ctr : amortissement KDF sur N messages.
        
        FIXED v2.2.1: individual path now uses pre-derived params (kw)
        to avoid re-running Argon2id for each message.
        """
        results = []
        msg_size = 65_536
        kw = self._kw()

        for n in [1, 5, 10, 50, 100]:
            messages = [os.urandom(msg_size) for _ in range(n)]
            total_size = n * msg_size

            # Bulk (1 dérivation KDF)
            results += self._bench(
                f"bulk-ctr-{n}msgs", "CAGOULE-bulk-CTR",
                lambda msgs=messages: encrypt_bulk_ctr(msgs, PASSWORD),
                total_size,
                {
                    "n_messages": n, "msg_size_kb": msg_size // 1024,
                    "kdf_calls": 1, "mode": "bulk",
                }
            )

            # Individual with pre-derived params (FIXED)
            results += self._bench(
                f"individual-ctr-{n}msgs", "CAGOULE-individual-CTR",
                lambda msgs=messages, kw=kw: [encrypt_ctr(m, PASSWORD, **kw) for m in msgs],
                total_size,
                {
                    "n_messages": n, "msg_size_kb": msg_size // 1024,
                    "kdf_calls": n, "mode": "individual",
                }
            )

        return results

    # ── Main run ───────────────────────────────────────────────────────────────

    def run(self) -> list[BenchmarkResult]:
        if not CAGOULE_V30:
            return [_skip("all", "CAGOULE v3.0.0 non disponible — pip install cagoule>=3.0.0")]

        results = []
        results += self._bench_ctr_vs_cbc()
        results += self._bench_4x_vs_1x()
        results += self._bench_symmetry()
        results += self._bench_migration()
        results += self._bench_bulk_ctr()
        return results

    def __del__(self):
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                CagouleParams.clear_benchmark_cache()
            except Exception:
                pass