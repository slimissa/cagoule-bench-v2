"""
EncryptionSuite v3.0 — benchmark chiffrement/déchiffrement.

Nouveautés v3.0 (CAGOULE v3.0.0) :
  - CAGOULE_V30 flag : détection CTR mode (encrypt_ctr, encrypt_cbc)
  - CBC historique via encrypt_cbc() — comparable aux runs v2.5.x
  - CTR nouveauté via encrypt_ctr()
  - Mode tag dans extra{} : "cbc" | "ctr" — pour HistoryDB propre
  - Overhead CT : |CT|/|PT| ratio mesuré (0 padding CTR vs PKCS7 CBC)
  - CAGOULE V30 ne casse pas la compatibilité montante (encrypt_cbc toujours dispo)
"""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

from bench.metrics import CpuCollector, MemoryCollector, TimeCollector
from bench.suites.base import BaseSuite, _detect_arch

BENCHMARK_SALT = b"\xca\xf0" * 16  # 32 octets fixes, reproductible

# ── CAGOULE version detection ──────────────────────────────────────────────────
CAGOULE_AVAILABLE = False
CAGOULE_V22 = False
CAGOULE_V23 = False
CAGOULE_V30 = False   # CTR mode (encrypt_ctr, encrypt_cbc, decrypt dispatch)
CAGOULE_PARAMS = False
CAGOULE_BACKEND: dict = {}

try:
    # v2.2.0 API
    try:
        from cagoule import backend_info as _bi
        CAGOULE_BACKEND = _bi
        CAGOULE_V22 = True
    except ImportError:
        CAGOULE_BACKEND = {"matrix_backend": "unknown", "omega_backend": "unknown"}

    # v2.3.0 API
    try:
        from cagoule._binding import get_backend_info_v230 as _get_v230
        CAGOULE_BACKEND = _get_v230()
        CAGOULE_V23 = True
    except (ImportError, Exception):
        pass

    # v3.0.0 API — CTR mode
    try:
        from cagoule import encrypt_ctr, encrypt_cbc, decrypt_ctr, decrypt_cbc
        CAGOULE_V30 = True
    except ImportError:
        from cagoule import encrypt as encrypt_cbc       # fallback: encrypt = CBC en v2.x
        from cagoule import decrypt as decrypt_cbc
        encrypt_ctr = encrypt_cbc
        decrypt_ctr = decrypt_cbc

    # Toujours disponible
    from cagoule import encrypt as cagoule_encrypt
    from cagoule import decrypt as cagoule_decrypt

    try:
        from cagoule.params import CagouleParams
        CAGOULE_PARAMS = True
    except ImportError:
        pass

    CAGOULE_AVAILABLE = True

except ImportError:
    def cagoule_encrypt(plaintext, password, **kw):
        key = password * (len(plaintext) // len(password) + 1)
        return bytes(p ^ k for p, k in zip(plaintext, key[:len(plaintext)]))
    cagoule_decrypt = None
    encrypt_cbc = cagoule_encrypt
    encrypt_ctr = cagoule_encrypt
    decrypt_cbc = None
    decrypt_ctr = None

DEFAULT_SIZES = [1_024, 8_192, 65_536, 1_048_576, 10_485_760]
PASSWORD  = b"cagoule-bench-v2-reference-password"
AES_KEY   = AESGCM.generate_key(bit_length=256)
CHACHA_KEY = os.urandom(32)


def _aes_encrypt(pt):
    aes = AESGCM(AES_KEY); n = os.urandom(12)
    return n + aes.encrypt(n, pt, None)

def _aes_decrypt(ct):
    return AESGCM(AES_KEY).decrypt(ct[:12], ct[12:], None)

def _chacha_encrypt(pt):
    c = ChaCha20Poly1305(CHACHA_KEY); n = os.urandom(12)
    return n + c.encrypt(n, pt, None)

def _chacha_decrypt(ct):
    return ChaCha20Poly1305(CHACHA_KEY).decrypt(ct[:12], ct[12:], None)


class EncryptionSuite(BaseSuite):
    NAME        = "encryption"
    DESCRIPTION = "CAGOULE (CBC + CTR) vs AES-256-GCM vs ChaCha20-Poly1305"

    def __init__(self, iterations=500, warmup=10, sizes=None, store_samples=True):
        super().__init__(iterations=iterations, warmup=warmup)
        self.sizes = sizes or DEFAULT_SIZES
        self.store_samples = store_samples
        self._timer = TimeCollector()
        self._mem   = MemoryCollector()
        self._cpu   = CpuCollector()
        self._arch  = _detect_arch()

        # Pré-dérivation (une seule fois) — compatible v2.x et v3.x
        self._params = None
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                self._params = CagouleParams.derive_for_benchmark(
                    PASSWORD, fast_mode=False, salt=BENCHMARK_SALT
                )
            except Exception:
                pass

    def run(self):
        results = []
        for size in self.sizes:
            pt = os.urandom(size)
            label = self._fmt_size(size)

            # Pre-compute ciphertexts for decrypt
            kw = {"params": self._params} if self._params else {}
            cbc_ct  = encrypt_cbc(pt, PASSWORD, **kw)
            ctr_ct  = encrypt_ctr(pt, PASSWORD, **kw) if CAGOULE_V30 else cbc_ct
            aes_ct  = _aes_encrypt(pt)
            cha_ct  = _chacha_encrypt(pt)

            # ── CAGOULE CBC (historique — comparable v2.5.x) ──────────
            results += self._bench(f"encrypt-{label}", "CAGOULE-CBC",
                lambda pt=pt, kw=kw: encrypt_cbc(pt, PASSWORD, **kw), size, mode="cbc")
            results += self._bench(f"decrypt-{label}", "CAGOULE-CBC",
                lambda ct=cbc_ct, kw=kw: decrypt_cbc(ct, PASSWORD, **kw), size, mode="cbc")

            # ── CAGOULE CTR (v3.0.0 nouveauté) ────────────────────────
            if CAGOULE_V30:
                results += self._bench(f"encrypt-{label}", "CAGOULE-CTR",
                    lambda pt=pt, kw=kw: encrypt_ctr(pt, PASSWORD, **kw), size, mode="ctr",
                    ct_size=len(ctr_ct), pt_size=size)
                results += self._bench(f"decrypt-{label}", "CAGOULE-CTR",
                    lambda ct=ctr_ct, kw=kw: decrypt_ctr(ct, PASSWORD, **kw), size, mode="ctr")

            # ── AES-256-GCM ───────────────────────────────────────────
            results += self._bench(f"encrypt-{label}", "AES-256-GCM",
                lambda pt=pt: _aes_encrypt(pt), size)
            results += self._bench(f"decrypt-{label}", "AES-256-GCM",
                lambda ct=aes_ct: _aes_decrypt(ct), size)

            # ── ChaCha20-Poly1305 ─────────────────────────────────────
            results += self._bench(f"encrypt-{label}", "ChaCha20-Poly1305",
                lambda pt=pt: _chacha_encrypt(pt), size)
            results += self._bench(f"decrypt-{label}", "ChaCha20-Poly1305",
                lambda ct=cha_ct: _chacha_decrypt(ct), size)

        return results

    def _bench(self, name, algorithm, op, data_size, mode="", ct_size=0, pt_size=0):
        for _ in range(3):
            self._mem.measure(op)
        _, mem = self._mem.measure(op, label=f"{algorithm}-{name}")
        timing = self._timer.measure(op, iterations=self.iterations,
                                     warmup=self.warmup, label=f"{algorithm}-{name}")
        _, cpu = self._cpu.measure(op, label=f"{algorithm}-{name}")

        extra = {
            "cagoule_available": CAGOULE_AVAILABLE,
            "cagoule_v22": CAGOULE_V22, "cagoule_v23": CAGOULE_V23,
            "cagoule_v30": CAGOULE_V30,
            "matrix_backend": CAGOULE_BACKEND.get("matrix_backend", "mock"),
            "sbox_backend": CAGOULE_BACKEND.get("sbox_backend", "unknown"),
            "omega_backend": CAGOULE_BACKEND.get("omega_backend", "mock"),
            "params_precomputed": self._params is not None,
            "arch": self._arch, "mode": mode,
        }
        # CT overhead ratio — key v3.0.0 metric (0 for CTR vs PKCS7 for CBC)
        if ct_size and pt_size:
            extra["ct_pt_overhead_bytes"] = ct_size - pt_size
            extra["ct_overhead_pct"] = round((ct_size - pt_size) / pt_size * 100, 2)

        return [self._make_result(
            name=name, algorithm=algorithm, data_size_bytes=data_size,
            mean_ms=timing.mean_ms, stddev_ms=timing.stddev_ms,
            min_ms=timing.min_ms, max_ms=timing.max_ms,
            p95_ms=timing.p95_ms, p99_ms=timing.p99_ms,
            cv_percent=timing.cv_percent,
            throughput_mbps=timing.throughput_mbps(data_size),
            peak_mb=mem.peak_mb, delta_mb=mem.delta_mb,
            cpu_mean_pct=cpu.cpu_mean_pct, cpu_peak_pct=cpu.cpu_peak_pct,
            samples_ns=timing.samples_ns if self.store_samples else [],
            extra=extra,
        )]

    def __del__(self):
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS:
            try:
                CagouleParams.clear_benchmark_cache()
            except Exception:
                pass

    @staticmethod
    def _fmt_size(size):
        if size < 1024: return f"{size}B"
        if size < 1_048_576: return f"{size // 1024}KB"
        return f"{size // 1_048_576}MB"
