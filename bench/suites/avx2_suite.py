"""
AVX2Suite v2.1.0 — benchmark spécifique CAGOULE v2.3.0.

BUG CRITIQUE CORRIGÉ (v2.0.0) :
  Le dispatch AVX2 de CAGOULE est initialisé UNE SEULE FOIS via un flag C
  atomique (_g_avx2_ready). Modifier os.environ["CAGOULE_FORCE_SCALAR"]
  APRÈS le premier appel cagoule_encrypt() est donc SANS EFFET sur le C.

SOLUTION : mesure scalaire via subprocess isolé.
  CAGOULE_FORCE_SCALAR=1 est positionné AVANT tout import cagoule dans le
  subprocess → dispatch initialisé en mode scalaire dès le premier appel.
  L'env du processus parent n'est jamais modifié.

Nouveautés v2.1.0 (CAGOULE v2.3.0) :
  - Utilise get_backend_info_v230() pour exposer 'sbox_backend' (avx2|scalar)
  - CAGOULE_V23 flag détectant la présence de la nouvelle API
  - DESCRIPTION mise à jour
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from bench.metrics import MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult

# BUG3 FIX: CAGOULE_AVAILABLE défini AVANT la classe (plus d'assignation fantôme en bas de fichier)
CAGOULE_V22 = False
CAGOULE_V23 = False   # v2.3.0 : get_backend_info_v230() + sbox_backend
CAGOULE_V31 = False   # v3.1.0 : get_backend_info_v310() + neon_backend
CAGOULE_CTR_API = False  # v3.1.0 : encrypt_ctr/decrypt_ctr (chemin AVX2 lazy)
CAGOULE_AVAILABLE = False
CAGOULE_PARAMS = False
cagoule_backend_info: dict = {}

try:
    from cagoule import encrypt as cagoule_encrypt

    # v3.1.0 release audit, tâche 2 : encrypt_ctr/decrypt_ctr, pour exercer
    # le VRAI chemin AVX2 lazy-reduction (cagoule_matrix_mul_avx2_lazy),
    # distinct du chemin CBC (cagoule_matrix_mul_avx2, réduction complète)
    # que cagoule_encrypt() ci-dessus a toujours exercé. Avant ce fix,
    # AVX2Suite ne testait JAMAIS le code changé par le fix de perf v3.1.0.
    CAGOULE_CTR_API = False
    try:
        from cagoule import encrypt_ctr, decrypt_ctr
        CAGOULE_CTR_API = True
    except ImportError:
        CAGOULE_CTR_API = False

    # v2.2.0 API : backend_info dict (matrix_backend, omega_backend)
    try:
        from cagoule import backend_info as _cag_backend
        cagoule_backend_info = _cag_backend
        CAGOULE_V22 = True
    except ImportError:
        cagoule_backend_info = {"matrix_backend": "unknown", "omega_backend": "unknown"}

    # v2.3.0 API : get_backend_info_v230() ajoute sbox_backend
    try:
        from cagoule._binding import get_backend_info_v230 as _get_v230
        cagoule_backend_info = _get_v230()
        CAGOULE_V23 = True
    except (ImportError, Exception):
        pass

    # v3.1.0 API : get_backend_info_v310() ajoute neon_backend + matrix_backend
    # peut valoir "neon" -- v3.1.0 release audit, tâche 3. Optionnel comme
    # les blocs précédents : dégrade vers cagoule_backend_info déjà posé
    # (v2.3.0 ou v2.2.0) si absent, ne fait jamais échouer l'import.
    try:
        from cagoule._binding import get_backend_info_v310 as _get_v310
        cagoule_backend_info = _get_v310()
        CAGOULE_V31 = True
    except (ImportError, Exception):
        CAGOULE_V31 = False

    CAGOULE_AVAILABLE = True
except ImportError:
    CAGOULE_V31 = False

    def cagoule_encrypt(plaintext: bytes, password: bytes, **kwargs) -> bytes:  # type: ignore[misc]
        key = password * (len(plaintext) // len(password) + 1)
        return bytes(p ^ k for p, k in zip(plaintext, key[: len(plaintext)]))


try:
    from cagoule.params import CagouleParams

    CAGOULE_PARAMS = True
except ImportError:
    pass

BENCHMARK_SALT = b"\xca\xf0" * 16
PASSWORD = b"cagoule-bench-v2-avx2-test"

DELTA_SIZES = [
    65_536,  # 64 KB
    1_048_576,  # 1 MB
    10_485_760,  # 10 MB
]

# ── Subprocess worker script ──────────────────────────────────────────────────
# Injecté comme code Python inline, exécuté avec CAGOULE_FORCE_SCALAR=1 dans env

_SCALAR_WORKER_SCRIPT = r"""
import os, sys, json, time, statistics

# CRITIQUE : env var positionnée AVANT tout import cagoule
# Le processus parent passe cette valeur via subprocess env, pas os.environ
# donc aucun risque de contamination de session

try:
    from cagoule import encrypt as cagoule_encrypt
    try:
        from cagoule.params import CagouleParams
        HAS_PARAMS = True
    except ImportError:
        HAS_PARAMS = False
except ImportError:
    HAS_PARAMS = False
    def cagoule_encrypt(pt, pw, **kw):
        key = pw * (len(pt) // len(pw) + 1)
        return bytes(p ^ k for p, k in zip(pt, key[:len(pt)]))

args = json.loads(sys.argv[1])
size      = args["size"]
iters     = args["iterations"]
warmup    = args["warmup"]
password  = args["password"].encode()
salt      = bytes(args["salt"])

plaintext = os.urandom(size)
params = None
if HAS_PARAMS:
    try:
        params = CagouleParams.derive_for_benchmark(password, fast_mode=False, salt=salt)
    except Exception:
        pass

def _op():
    return cagoule_encrypt(plaintext, password, **({"params": params} if params else {}))

for _ in range(warmup):
    _op()

samples_ns = []
for _ in range(iters):
    t0 = time.perf_counter_ns()
    _op()
    samples_ns.append(time.perf_counter_ns() - t0)

mean_ms = statistics.mean(samples_ns) / 1e6
std_ms  = (statistics.stdev(samples_ns) / 1e6) if len(samples_ns) > 1 else 0.0
ss      = sorted(samples_ns)
p95_ms  = ss[int(len(ss) * 0.95)] / 1e6
p99_ms  = ss[min(int(len(ss) * 0.99), len(ss)-1)] / 1e6
tp      = (size / 1_048_576) / (mean_ms / 1000) if mean_ms > 0 else 0.0

print(json.dumps({
    "mean_ms": round(mean_ms, 4),
    "stddev_ms": round(std_ms, 4),
    "min_ms": round(min(samples_ns) / 1e6, 4),
    "max_ms": round(max(samples_ns) / 1e6, 4),
    "p95_ms": round(p95_ms, 4),
    "p99_ms": round(p99_ms, 4),
    "cv_percent": round((std_ms / mean_ms * 100) if mean_ms > 0 else 0.0, 2),
    "throughput_mbps": round(tp, 3),
    "samples_ns": samples_ns,
    "backend": "scalar_forced_subprocess",
}))
"""


def _run_scalar_subprocess(size: int, iterations: int, warmup: int, salt: bytes) -> dict:
    """
    Mesure scalaire dans un subprocess isolé.

    BUG1+BUG2 FIX :
      - BUG1 : CAGOULE_FORCE_SCALAR=1 passé via env du subprocess →
               dispatch C initialisé scalaire dès le premier appel.
      - BUG2 : L'env du processus parent n'est JAMAIS modifié,
               même en cas d'exception dans le subprocess.
    """
    payload = json.dumps(
        {
            "size": size,
            "iterations": iterations,
            "warmup": warmup,
            "password": PASSWORD.decode(),
            "salt": list(salt),
        }
    )
    child_env = {**os.environ, "CAGOULE_FORCE_SCALAR": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _SCALAR_WORKER_SCRIPT, payload],
            capture_output=True,
            text=True,
            timeout=300,
            env=child_env,
        )
        if proc.returncode != 0:
            return {"skipped": True, "error": proc.stderr.strip()[:500]}
        return json.loads(proc.stdout.strip())
    except subprocess.TimeoutExpired:
        return {"skipped": True, "error": "subprocess timeout (>300s)"}
    except Exception as exc:
        return {"skipped": True, "error": str(exc)}


# ── Suite ─────────────────────────────────────────────────────────────────────


class AVX2Suite(BaseSuite):
    NAME = "avx2"
    DESCRIPTION = "CAGOULE v3.1.0 — AVX2/NEON vs scalaire (subprocess isolé), S-box Feistel + Vandermonde"

    def __init__(self, iterations: int = 200, warmup: int = 10, sizes: list[int] | None = None):
        super().__init__(iterations=iterations, warmup=warmup)
        self.sizes = sizes or DELTA_SIZES
        self._timer = TimeCollector()
        self._mem = MemoryCollector()
        self._params = None
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                self._params = CagouleParams.derive_for_benchmark(
                    PASSWORD, fast_mode=False, salt=BENCHMARK_SALT
                )
            except Exception:
                pass

    def run(self) -> list[BenchmarkResult]:
        if not CAGOULE_V22:
            return [
                self._make_result(
                    name="avx2-unavailable",
                    algorithm="CAGOULE",
                    extra={
                        "error": "CAGOULE v2.2.0 non disponible",
                        "tip": "pip install cagoule>=2.2.0",
                    },
                )
            ]

        backend = cagoule_backend_info
        # v3.1.0 : matrix_backend peut valoir "neon" (ARM) en plus de
        # "avx2"/"scalar"/"python" -- traiter les deux comme "backend
        # vectorisé actif" pour is_avx2_active plutôt que de mal étiqueter
        # un run ARM NEON comme "scalar_runtime".
        is_neon_active = backend.get("matrix_backend") == "neon"
        is_avx2_active = backend.get("matrix_backend") == "avx2" or is_neon_active
        results: list[BenchmarkResult] = []

        for size in self.sizes:
            plaintext = os.urandom(size)
            size_label = self._fmt_size(size)

            if self._params is not None:

                def _op_avx2(pt=plaintext):
                    return cagoule_encrypt(pt, PASSWORD, params=self._params)

            else:

                def _op_avx2(pt=plaintext):
                    return cagoule_encrypt(pt, PASSWORD)

            # ── 1. AVX2 (dispatch normal, in-process) ─────────────────
            timing_avx2 = self._timer.measure(
                _op_avx2,
                iterations=self.iterations,
                warmup=self.warmup,
                label=f"avx2-{size_label}",
            )
            _, mem_avx2 = self._mem.measure(_op_avx2)

            results.append(
                self._make_result(
                    name=f"encrypt-{size_label}",
                    algorithm="CAGOULE-AVX2",
                    data_size_bytes=size,
                    mean_ms=timing_avx2.mean_ms,
                    stddev_ms=timing_avx2.stddev_ms,
                    min_ms=timing_avx2.min_ms,
                    max_ms=timing_avx2.max_ms,
                    p95_ms=timing_avx2.p95_ms,
                    p99_ms=timing_avx2.p99_ms,
                    cv_percent=timing_avx2.cv_percent,
                    throughput_mbps=timing_avx2.throughput_mbps(size),
                    peak_mb=mem_avx2.peak_mb,
                    delta_mb=mem_avx2.delta_mb,
                    samples_ns=timing_avx2.samples_ns,
                    extra={
                        "backend": backend.get("matrix_backend", "scalar_runtime") if is_avx2_active else "scalar_runtime",
                        "avx2_available": is_avx2_active,
                        "neon_available": is_neon_active,
                        "matrix_backend": backend.get("matrix_backend"),
                        "sbox_backend": backend.get("sbox_backend", "unknown"),
                        "omega_backend": backend.get("omega_backend"),
                        "cagoule_v23": CAGOULE_V23,
                        "cagoule_v31": CAGOULE_V31,
                        "neon_backend": backend.get("neon_backend", False),
                        "forced_scalar": False,
                        "size_label": size_label,
                        "measurement_method": "in_process",
                    },
                )
            )

            # ── 2. Scalaire (subprocess isolé) ────────────────────────
            scalar = _run_scalar_subprocess(
                size=size,
                iterations=self.iterations,
                warmup=self.warmup,
                salt=BENCHMARK_SALT,
            )

            if scalar.get("skipped"):
                results.append(
                    self._make_result(
                        name=f"encrypt-{size_label}",
                        algorithm="CAGOULE-Scalar",
                        data_size_bytes=size,
                        extra={
                            "backend": "scalar_subprocess_failed",
                            "error": scalar.get("error", "unknown"),
                            "forced_scalar": True,
                            "avx2_gain_pct": None,
                        },
                    )
                )
                continue

            avx2_gain_pct = (
                round((scalar["mean_ms"] - timing_avx2.mean_ms) / scalar["mean_ms"] * 100, 1)
                if scalar["mean_ms"] > 0
                else 0.0
            )

            results.append(
                self._make_result(
                    name=f"encrypt-{size_label}",
                    algorithm="CAGOULE-Scalar",
                    data_size_bytes=size,
                    mean_ms=scalar["mean_ms"],
                    stddev_ms=scalar["stddev_ms"],
                    min_ms=scalar["min_ms"],
                    max_ms=scalar["max_ms"],
                    p95_ms=scalar["p95_ms"],
                    p99_ms=scalar["p99_ms"],
                    cv_percent=scalar["cv_percent"],
                    throughput_mbps=scalar["throughput_mbps"],
                    samples_ns=scalar.get("samples_ns", []),
                    extra={
                        "backend": scalar.get("backend", "scalar_forced_subprocess"),
                        "avx2_available": is_avx2_active,
                        "matrix_backend": "scalar",
                        "sbox_backend": "scalar",
                        "omega_backend": backend.get("omega_backend"),
                        "cagoule_v23": CAGOULE_V23,
                        "forced_scalar": True,
                        "size_label": size_label,
                        "measurement_method": "subprocess_isolated",
                        "avx2_speedup": (
                            round(scalar["mean_ms"] / timing_avx2.mean_ms, 3)
                            if timing_avx2.mean_ms > 0
                            else 1.0
                        ),
                        "avx2_gain_pct": avx2_gain_pct,
                    },
                )
            )

        # v3.1.0 release audit, tâche 2 : ajoute le chemin CTR-lazy
        # (cagoule_matrix_mul_avx2_lazy), jamais exercé par les sections
        # ci-dessus (CBC uniquement, cagoule_matrix_mul_avx2 inchangé).
        results += self._bench_ctr_lazy_path()

        return results

    def _bench_ctr_lazy_path(self) -> list[BenchmarkResult]:
        """
        Section CTR-lazy-path -- v3.1.0 release audit, tâche 2.

        Exerce cagoule_matrix_mul_avx2_lazy (le VRAI code changé par le fix
        de perf v3.1.0, ~2x throughput CTR sur ce chemin), via
        encrypt_ctr()/decrypt_ctr(). Distinct des sections ci-dessus
        (cagoule_encrypt() = CBC, cagoule_matrix_mul_avx2 inchangé).

        Réutilise self._params (pré-dérivé une fois dans __init__, comme
        le reste de la suite) -- mesure le coût cipher seul, pas le KDF.

        Rapporte ctr_backend / ctr_4x_available via get_backend_info_v310()
        pour chaque résultat, comme demandé.
        """
        if not (CAGOULE_V22 and CAGOULE_CTR_API):
            return [
                self._make_result(
                    name="ctr-lazy-path-unavailable",
                    algorithm="CAGOULE-CTR-AVX2-lazy",
                    extra={
                        "skipped": True,
                        "reason": "encrypt_ctr/decrypt_ctr not available "
                                  "(requires cagoule>=3.0.0)",
                    },
                )
            ]

        backend = cagoule_backend_info
        ctr_backend = backend.get("ctr_backend", "unknown")
        ctr_4x_available = backend.get("ctr_4x_available", False)

        results: list[BenchmarkResult] = []
        kw = {"params": self._params} if self._params is not None else {}

        for size in self.sizes:
            plaintext = os.urandom(size)
            size_label = self._fmt_size(size)

            timing_enc = self._timer.measure(
                lambda pt=plaintext: encrypt_ctr(pt, PASSWORD, **kw),
                iterations=self.iterations, warmup=self.warmup,
            )
            ciphertext = encrypt_ctr(plaintext, PASSWORD, **kw)
            timing_dec = self._timer.measure(
                lambda ct=ciphertext: decrypt_ctr(ct, PASSWORD, **kw),
                iterations=self.iterations, warmup=self.warmup,
            )

            for op_name, timing in (("encrypt", timing_enc), ("decrypt", timing_dec)):
                results.append(
                    self._make_result(
                        name=f"ctr-lazy-{op_name}-{size_label}",
                        algorithm="CAGOULE-CTR-AVX2-lazy",
                        data_size_bytes=size,
                        mean_ms=timing.mean_ms,
                        stddev_ms=timing.stddev_ms,
                        min_ms=timing.min_ms,
                        max_ms=timing.max_ms,
                        p95_ms=timing.p95_ms,
                        p99_ms=timing.p99_ms,
                        cv_percent=timing.cv_percent,
                        throughput_mbps=timing.throughput_mbps(size),
                        samples_ns=timing.samples_ns,
                        extra={
                            "matrix_path": "cagoule_matrix_mul_avx2_lazy",
                            "matrix_backend": backend.get("matrix_backend"),
                            "ctr_backend": ctr_backend,
                            "ctr_4x_available": ctr_4x_available,
                            "cagoule_v31": CAGOULE_V31,
                            "params_precomputed": self._params is not None,
                            "size_label": size_label,
                            "measurement_method": "in_process",
                        },
                    )
                )

        return results

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        if size < 1_048_576:
            return f"{size // 1024}KB"
        return f"{size // 1_048_576}MB"