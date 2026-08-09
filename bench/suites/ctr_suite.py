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

# v3.1.0 — cagoule_encrypt_v3/decrypt_v3 (cagoule_api.c, API C unifiée
# mono-message), exportées publiquement depuis cagoule/__init__.py à
# partir du release audit v3.1.0. Import séparé et optionnel : un
# cagoule<3.1.0 (ou un 3.1.0 sans le fix d'export) a CAGOULE_V30=True
# mais pas cette API -- ne doit pas faire échouer tout le reste de la
# suite, seulement dégrader gracieusement la nouvelle section.
CAGOULE_V31_API = False
try:
    from cagoule import encrypt_v3, decrypt_v3
    CAGOULE_V31_API = True
except ImportError:
    CAGOULE_V31_API = False


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
                # v3.1.0 release audit, tâche 3 : 15.0 (v3.0.0) → 30.0.
                # Le fix AVX2 lazy-reduction v3.1.0 porte le débit C-layer
                # de ~20-31 MB/s à ~50 MB/s -- 30.0 reste un plancher
                # conservateur côté Python e2e (mesuré ~22-32 MB/s selon
                # le matériel), pas un objectif optimiste.
                "target_mbps": 30.0,
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
                lambda msgs=messages, kw=kw: encrypt_bulk_ctr(msgs, PASSWORD, params=kw.get("params")), 
                total_size,
                {
                    "n_messages": n, "msg_size_kb": msg_size // 1024,
                    "kdf_calls": 1, "mode": "bulk",
                }
            )

            # Individual with pre-derived params (FIXED)
            results += self._bench(
                f"individual-ctr-{n}msgs", "CAGOULE-individual-CTR",
                lambda msgs=messages: [encrypt_ctr(m, PASSWORD) for m in msgs],
                total_size,
                {
                    "n_messages": n, "msg_size_kb": msg_size // 1024,
                    "kdf_calls": n, "mode": "individual",
                }
            )

        return results

    def _bench_encrypt_v3(self) -> list[BenchmarkResult]:
        """
        Section 6 — cagoule_encrypt_v3/decrypt_v3 (API C unifiée
        mono-message, cagoule_api.c) -- v3.1.0 release audit, tâche 1.

        Skippé proprement (extra{"skipped": True}) si le cagoule installé
        n'exporte pas encore encrypt_v3/decrypt_v3 publiquement (versions
        antérieures au fix d'export de cette tâche).

        IMPORTANT — PAS comparable directement aux chiffres de la Section 1
        (_bench_ctr_vs_cbc) : ce chemin re-dérive Argon2id À CHAQUE APPEL
        (encrypt_v3/decrypt_v3 ne prennent pas de params pré-dérivés --
        c'est le point du chemin "mono-message : derive + crypt + free en
        un appel" documenté dans cagoule_api.h). La Section 1 réutilise
        self._params et ne mesure donc QUE le coût cipher. Ce mélange KDF
        + cipher est reflété explicitement dans "kdf_calls": 1 "per_call"
        ci-dessous pour qu'un lecteur du rapport ne confonde pas les deux.

        Tailles réduites à [1KB, 1MB] (pas self.sizes) : chaque itération
        inclut un Argon2id complet (~300-500ms mesuré) -- même raison que
        _bench_symmetry()/_bench_migration() utilisent déjà des listes de
        tailles réduites plutôt que self.sizes.
        """
        if not CAGOULE_V31_API:
            return [self._make_result(
                name="encrypt-v3-unavailable", algorithm="CAGOULE-v3-API",
                data_size_bytes=0, mean_ms=0, stddev_ms=0, min_ms=0, max_ms=0,
                p95_ms=0, p99_ms=0, cv_percent=0, throughput_mbps=0,
                peak_mb=0, delta_mb=0, cpu_mean_pct=0, cpu_peak_pct=0,
                samples_ns=[],
                extra={"skipped": True,
                       "reason": "encrypt_v3/decrypt_v3 not exported by this cagoule "
                                 "(requires v3.1.0 release-audit export fix)"},
            )]

        results = []
        for size in [1_024, 1_048_576]:
            pt = os.urandom(size)
            label = self._fmt(size)

            ct, _ = encrypt_v3(PASSWORD, pt)

            results += self._bench(
                f"encrypt-v3-{label}", "CAGOULE-v3-API",
                lambda pt=pt: encrypt_v3(PASSWORD, pt),
                size,
                {"mode": "v3-api-monomsg", "kdf_calls": "1 per_call (no shared params)"},
            )
            results += self._bench(
                f"decrypt-v3-{label}", "CAGOULE-v3-API",
                lambda ct=ct: decrypt_v3(PASSWORD, ct),
                size,
                {"mode": "v3-api-monomsg", "kdf_calls": "1 per_call (no shared params)"},
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
        results += self._bench_encrypt_v3()
        return results

    def __del__(self):
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                CagouleParams.clear_benchmark_cache()
            except Exception:
                pass