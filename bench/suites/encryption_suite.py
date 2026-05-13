"""
EncryptionSuite v2.0 — benchmark chiffrement/déchiffrement.

Nouveautés v2.0 :
  - Stockage des samples_ns bruts pour comparaisons statistiques
  - Compatibilité CAGOULE v2.1 API (derive_session_key)
  - Détection architecturale (ARM64 sans AES-NI → avantage ChaCha20)
  - 5 tailles de messages : 1KB → 10MB
  - Stats complètes : mean, stddev, p95, p99, CV
"""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, BenchmarkResult, _detect_arch

# ── CAGOULE v2.2.0 import ─────────────────────────────────────────────────────
BENCHMARK_SALT = b"\xca\xf0" * 16  # 32 octets fixes, reproductible

CAGOULE_AVAILABLE = False
CAGOULE_V22 = False  # AVX2 + DiffusionMatrixC.free() + backend_info
CAGOULE_V23 = False  # S-box AVX2 + get_backend_info_v230() + sbox_backend
CAGOULE_PARAMS = False
CAGOULE_BACKEND: dict = {}

try:
    from cagoule import encrypt as cagoule_encrypt

    # v2.2.0 API
    try:
        from cagoule import backend_info as _cagoule_backend_info
        CAGOULE_BACKEND = _cagoule_backend_info
        CAGOULE_V22 = True
    except ImportError:
        CAGOULE_BACKEND = {"matrix_backend": "unknown", "omega_backend": "unknown"}

    # v2.3.0 API — get_backend_info_v230() ajoute sbox_backend
    try:
        from cagoule._binding import get_backend_info_v230 as _get_v230
        CAGOULE_BACKEND = _get_v230()
        CAGOULE_V23 = True
    except (ImportError, Exception):
        pass

    try:
        from cagoule.params import CagouleParams
        CAGOULE_PARAMS = True
    except ImportError:
        pass

    CAGOULE_AVAILABLE = True

except ImportError:

    def cagoule_encrypt(plaintext: bytes, password: bytes, **kwargs) -> bytes:
        """Mock XOR — NOT real crypto, benchmark harness only."""
        key = password * (len(plaintext) // len(password) + 1)
        return bytes(p ^ k for p, k in zip(plaintext, key[: len(plaintext)]))


try:
    from cagoule import decrypt as cagoule_decrypt
except ImportError:
    cagoule_decrypt = None

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_SIZES = [
    1_024,  # 1 KB
    8_192,  # 8 KB
    65_536,  # 64 KB
    1_048_576,  # 1 MB
    10_485_760,  # 10 MB
]

PASSWORD = b"cagoule-bench-v2-reference-password"
AES_KEY = AESGCM.generate_key(bit_length=256)
CHACHA_KEY = os.urandom(32)


# ── Primitives ────────────────────────────────────────────────────────────────


def _aes_encrypt(plaintext: bytes) -> bytes:
    aes = AESGCM(AES_KEY)
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, plaintext, None)


def _aes_decrypt(ciphertext: bytes) -> bytes:
    nonce, ct = ciphertext[:12], ciphertext[12:]
    return AESGCM(AES_KEY).decrypt(nonce, ct, None)


def _chacha_encrypt(plaintext: bytes) -> bytes:
    chacha = ChaCha20Poly1305(CHACHA_KEY)
    nonce = os.urandom(12)
    return nonce + chacha.encrypt(nonce, plaintext, None)


def _chacha_decrypt(ciphertext: bytes) -> bytes:
    nonce, ct = ciphertext[:12], ciphertext[12:]
    return ChaCha20Poly1305(CHACHA_KEY).decrypt(nonce, ct, None)


def _cagoule_decrypt(ciphertext: bytes, password: bytes, **kwargs) -> bytes:
    if CAGOULE_AVAILABLE and cagoule_decrypt is not None:
        return cagoule_decrypt(ciphertext, password, **kwargs)
    return cagoule_encrypt(ciphertext, password)


# ── Suite ─────────────────────────────────────────────────────────────────────


class EncryptionSuite(BaseSuite):
    NAME = "encryption"
    DESCRIPTION = "CAGOULE vs AES-256-GCM vs ChaCha20-Poly1305 — chiffrement/déchiffrement"

    def __init__(
        self,
        iterations: int = 500,
        warmup: int = 10,
        sizes: list[int] | None = None,
        store_samples: bool = True,
    ):
        super().__init__(iterations=iterations, warmup=warmup)
        self.sizes = sizes or DEFAULT_SIZES
        self.store_samples = store_samples
        self._timer = TimeCollector()
        self._mem = MemoryCollector()
        self._cpu = CpuCollector()

        # ── Pré-dérivation CAGOULE (une seule fois) ──────────────────
        self._cagoule_params = None
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                self._cagoule_params = CagouleParams.derive_for_benchmark(
                    PASSWORD, fast_mode=False, salt=BENCHMARK_SALT
                )
            except Exception:
                pass

        self._arch = _detect_arch()

    def run(self) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []

        for size in self.sizes:
            plaintext = os.urandom(size)
            size_label = self._fmt_size(size)

            # Pre-compute ciphertexts for decrypt tests
            if self._cagoule_params is not None:
                cagoule_ct = cagoule_encrypt(plaintext, PASSWORD, params=self._cagoule_params)
            else:
                cagoule_ct = cagoule_encrypt(plaintext, PASSWORD)
            aes_ct = _aes_encrypt(plaintext)
            chacha_ct = _chacha_encrypt(plaintext)

            # ── CAGOULE ──────────────────────────────────────────────
            if self._cagoule_params is not None:
                _enc_cag = lambda pt=plaintext: cagoule_encrypt(
                    pt, PASSWORD, params=self._cagoule_params
                )
                _dec_cag = lambda ct=cagoule_ct: _cagoule_decrypt(
                    ct, PASSWORD, params=self._cagoule_params
                )
            else:
                _enc_cag = lambda pt=plaintext: cagoule_encrypt(pt, PASSWORD)
                _dec_cag = lambda ct=cagoule_ct: _cagoule_decrypt(ct, PASSWORD)

            results.extend(self._bench(f"encrypt-{size_label}", "CAGOULE", _enc_cag, size))
            results.extend(self._bench(f"decrypt-{size_label}", "CAGOULE", _dec_cag, size))

            # ── AES-256-GCM ───────────────────────────────────────────
            results.extend(
                self._bench(
                    f"encrypt-{size_label}", "AES-256-GCM", lambda: _aes_encrypt(plaintext), size
                )
            )
            results.extend(
                self._bench(
                    f"decrypt-{size_label}", "AES-256-GCM", lambda: _aes_decrypt(aes_ct), size
                )
            )

            # ── ChaCha20-Poly1305 ─────────────────────────────────────
            results.extend(
                self._bench(
                    f"encrypt-{size_label}",
                    "ChaCha20-Poly1305",
                    lambda: _chacha_encrypt(plaintext),
                    size,
                )
            )
            results.extend(
                self._bench(
                    f"decrypt-{size_label}",
                    "ChaCha20-Poly1305",
                    lambda: _chacha_decrypt(chacha_ct),
                    size,
                )
            )

        return results

    def _bench(self, name: str, algorithm: str, op, data_size: int) -> list[BenchmarkResult]:
        """Mesure time + memory + CPU pour une opération."""
        # Warmup mémoire
        for _ in range(3):
            self._mem.measure(op)
        _, mem = self._mem.measure(op, label=f"{algorithm}-{name}")

        timing = self._timer.measure(
            op, iterations=self.iterations, warmup=self.warmup, label=f"{algorithm}-{name}"
        )
        _, cpu = self._cpu.measure(op, label=f"{algorithm}-{name}")

        return [
            self._make_result(
                name=name,
                algorithm=algorithm,
                data_size_bytes=data_size,
                mean_ms=timing.mean_ms,
                stddev_ms=timing.stddev_ms,
                min_ms=timing.min_ms,
                max_ms=timing.max_ms,
                p95_ms=timing.p95_ms,
                p99_ms=timing.p99_ms,
                cv_percent=timing.cv_percent,
                throughput_mbps=timing.throughput_mbps(data_size),
                peak_mb=mem.peak_mb,
                delta_mb=mem.delta_mb,
                cpu_mean_pct=cpu.cpu_mean_pct,
                cpu_peak_pct=cpu.cpu_peak_pct,
                # v2.0 : samples bruts pour Mann-Whitney
                samples_ns=timing.samples_ns if self.store_samples else [],
                extra={
                    "cagoule_available": CAGOULE_AVAILABLE,
                    "cagoule_v22": CAGOULE_V22,
                    "cagoule_v23": CAGOULE_V23,
                    "matrix_backend": CAGOULE_BACKEND.get("matrix_backend", "mock"),
                    "sbox_backend": CAGOULE_BACKEND.get("sbox_backend", "unknown"),
                    "omega_backend": CAGOULE_BACKEND.get("omega_backend", "mock"),
                    "params_precomputed": self._cagoule_params is not None,
                    "arch": self._arch,
                },
            )
        ]

    def __del__(self):
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                CagouleParams.clear_benchmark_cache()
            except Exception:
                pass

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size}B"
        if size < 1_048_576:
            return f"{size // 1024}KB"
        return f"{size // 1_048_576}MB"