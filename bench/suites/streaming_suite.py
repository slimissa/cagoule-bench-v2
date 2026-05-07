"""
StreamingSuite v2.0 — benchmark chiffrement en streaming (NEW).

Mesure les performances sur de très gros fichiers (50MB, 100MB, 500MB)
en mode streaming : chunked read → encrypt → chunked write.

Objectifs :
  - Détecter les bottlenecks I/O vs CPU (utilisation RAM constante)
  - Comparer throughput streaming vs in-memory (EncryptionSuite)
  - Mesurer stabilité du débit sur la durée (stddev relative)

Cette suite est critique pour les cas d'usage QuantOS :
  - Chiffrement de market data archives (CSV historiques, tickdata)
  - Export de rapports sensibles
  - Sauvegarde vault cagoule-pass
"""

import io
import os
import time
import statistics  # BUG mineur FIX: import au niveau module, pas dans la boucle interne
from bench.metrics import TimeCollector, MemoryCollector, CpuCollector
from bench.suites.base import BaseSuite, BenchmarkResult

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

# ── CAGOULE v2.2.0 import ─────────────────────────────────────────────────────

CAGOULE_AVAILABLE = False
CAGOULE_PARAMS = None
BENCHMARK_SALT = b'\xca\xf0' * 16
PASSWORD = b"cagoule-bench-v2-streaming-test"

try:
    from cagoule import encrypt as cagoule_encrypt
    from cagoule.params import CagouleParams
    CAGOULE_AVAILABLE = True
    CAGOULE_PARAMS = CagouleParams.derive_for_benchmark(
        PASSWORD, fast_mode=True, salt=BENCHMARK_SALT
    )
except ImportError:
    def cagoule_encrypt(plaintext: bytes, password: bytes, **kwargs) -> bytes:
        """Fallback mock — NOT real crypto, benchmark harness only."""
        key = password * (len(plaintext) // len(password) + 1)
        return bytes(p ^ k for p, k in zip(plaintext, key[:len(plaintext)]))

# Configuration streaming
DEFAULT_STREAM_SIZES = [
    50 * 1_048_576,   # 50 MB
    100 * 1_048_576,  # 100 MB
    500 * 1_048_576,  # 500 MB
]

CHUNK_SIZE = 64 * 1024   # 64 KB chunks (balance entre CPU et RAM)

AES_KEY_STREAM = AESGCM.generate_key(bit_length=256) if CRYPTO_AVAILABLE else b'\x00' * 32
CHACHA_KEY_STREAM = os.urandom(32)


# ── Streaming helpers ─────────────────────────────────────────────────────────

def _stream_aes_encrypt(data_size: int, chunk_size: int = CHUNK_SIZE) -> tuple[float, int]:
    """
    Chiffre data_size bytes en mode streaming (chunks).

    BUG5 FIX v2.0.0 : io.BytesIO accumulait TOUT le ciphertext en RAM
    (500MB pour le plus grand test → RAM = O(total), pas O(chunk)).
    Maintenant le ciphertext est immédiatement discardé → RAM = O(chunk).
    """
    aes = AESGCM(AES_KEY_STREAM)

    t0 = time.perf_counter()
    remaining = data_size
    total_out = 0

    while remaining > 0:
        chunk = os.urandom(min(chunk_size, remaining))
        nonce = os.urandom(12)
        ct = aes.encrypt(nonce, chunk, None)
        # Discard output: on mesure le throughput CPU, pas l'I/O disque
        total_out += 12 + len(ct)
        remaining -= len(chunk)

    return time.perf_counter() - t0, total_out


def _stream_chacha_encrypt(data_size: int, chunk_size: int = CHUNK_SIZE) -> tuple[float, int]:
    """ChaCha20-Poly1305 streaming encrypt — output discardé (BUG5 FIX)."""
    chacha = ChaCha20Poly1305(CHACHA_KEY_STREAM)

    t0 = time.perf_counter()
    remaining = data_size
    total_out = 0

    while remaining > 0:
        chunk = os.urandom(min(chunk_size, remaining))
        nonce = os.urandom(12)
        ct = chacha.encrypt(nonce, chunk, None)
        total_out += 12 + len(ct)
        remaining -= len(chunk)

    return time.perf_counter() - t0, total_out


def _stream_cagoule_encrypt(data_size: int, chunk_size: int = CHUNK_SIZE) -> tuple[float, int]:
    """
    CAGOULE v2.2.0 streaming encrypt — output discardé (BUG5 FIX).

    Utilise CAGOULE_PARAMS pré-dérivés pour éviter le coût KDF par chunk.
    Chaque chunk est chiffré indépendamment avec le même jeu de paramètres.
    """
    t0 = time.perf_counter()
    remaining = data_size
    total_out = 0

    while remaining > 0:
        chunk = os.urandom(min(chunk_size, remaining))
        if CAGOULE_AVAILABLE and CAGOULE_PARAMS is not None:
            ct = cagoule_encrypt(chunk, PASSWORD, params=CAGOULE_PARAMS)
        else:
            ct = cagoule_encrypt(chunk, PASSWORD)
        total_out += len(ct)
        remaining -= len(chunk)

    return time.perf_counter() - t0, total_out


# ── Suite ─────────────────────────────────────────────────────────────────────

class StreamingSuite(BaseSuite):
    NAME = "streaming"
    DESCRIPTION = "Chiffrement en streaming — 50MB/100MB/500MB, chunks 64KB"

    def __init__(
        self,
        iterations: int = 3,
        warmup: int = 1,
        sizes: list[int] | None = None,
        chunk_size: int = CHUNK_SIZE,
    ):
        super().__init__(iterations=iterations, warmup=warmup)
        self.sizes = sizes or DEFAULT_STREAM_SIZES
        self.chunk_size = chunk_size
        self._mem = MemoryCollector()
        self._cpu = CpuCollector()

    def run(self) -> list[BenchmarkResult]:
        if not CRYPTO_AVAILABLE:
            return []

        results: list[BenchmarkResult] = []

        for size in self.sizes:
            size_label = f"{size // 1_048_576}MB"

            for algo, stream_fn in [
                ("AES-256-GCM", _stream_aes_encrypt),
                ("ChaCha20-Poly1305", _stream_chacha_encrypt),
                ("CAGOULE", _stream_cagoule_encrypt),
            ]:
                def _op(s=size, fn=stream_fn):
                    return fn(s, self.chunk_size)

                # Warmup
                _op()

                # Timing manual (stream functions return their own duration)
                timings_s = []
                for _ in range(self.iterations):
                    duration, _ = stream_fn(size, self.chunk_size)
                    timings_s.append(duration)

                mean_s = statistics.mean(timings_s)
                std_s  = statistics.stdev(timings_s) if len(timings_s) > 1 else 0.0
                p95_s  = sorted(timings_s)[int(len(timings_s) * 0.95)]

                throughput = (size / 1_048_576) / mean_s if mean_s > 0 else 0.0

                # Memory footprint (streaming should be O(chunk_size), not O(total))
                _, mem = self._mem.measure(lambda: _op(), label=f"stream-{algo}-{size_label}")
                _, cpu = self._cpu.measure(lambda: _op(), label=f"stream-{algo}-{size_label}")

                results.append(self._make_result(
                    name=f"stream-encrypt-{size_label}",
                    algorithm=algo,
                    data_size_bytes=size,
                    mean_ms=mean_s * 1000,
                    stddev_ms=std_s * 1000,
                    min_ms=min(timings_s) * 1000,
                    max_ms=max(timings_s) * 1000,
                    p95_ms=p95_s * 1000,
                    p99_ms=sorted(timings_s)[int(len(timings_s) * 0.99)] * 1000,
                    cv_percent=(std_s / mean_s * 100) if mean_s > 0 else 0.0,
                    throughput_mbps=throughput,
                    peak_mb=mem.peak_mb,
                    delta_mb=mem.delta_mb,
                    cpu_mean_pct=cpu.cpu_mean_pct,
                    cpu_peak_pct=cpu.cpu_peak_pct,
                    samples_ns=[int(t * 1e9) for t in timings_s],
                    extra={
                        "chunk_size_kb": self.chunk_size // 1024,
                        "total_mb": size / 1_048_576,
                        "chunks_count": size // self.chunk_size,
                        "streaming_mode": True,
                        "ram_efficiency": "O(chunk)" if mem.peak_mb < (size / 1_048_576 * 0.1) else "O(total)",
                        "cagoule_available": CAGOULE_AVAILABLE,
                        "note_non_ce_generation": "Includes os.urandom(12) nonce generation per chunk — realistic streaming overhead",
                    },
                ))

        return results