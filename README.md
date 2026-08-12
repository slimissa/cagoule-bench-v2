# cagoule-bench v2.3.0

Suite de benchmarking académique officielle pour **CAGOULE** — Cryptographie Algébrique Géométrique par Ondes et Logique Entrelacée.

> **Compatibilité cible :** CAGOULE v3.1.0 (CTR mode · AVX2 lazy reduction · `encrypt_ctr` · `encrypt_v3` · streaming API)  
> Compatible descendante : CAGOULE v3.0.0+ (CTR) · v2.2.0+ (CBC uniquement)

---

## Nouveautés v2.3.0

| Feature | Description |
|---|---|
| **History DB version filter** | Regression detection filters by `cagoule_version` — no cross-version blending |
| **`_find_lib()` warning surfaced** | Stale `.so` divergence detected, logged, flagged in results |
| **CTR-lazy-path benchmark** | AVX2 suite now exercises `encrypt_ctr`/`decrypt_ctr` with `get_backend_info_v310()` |
| **`encrypt_v3` benchmark** | Unified C API benchmark in CTR suite, with graceful degradation |
| **Streaming Python binding** | `CagouleStreamCtx` context manager, automatic buffer sizing |
| **NEON detection** | `get_backend_info_v310()` reports `neon_backend`, `matrix_backend: neon` on ARM |
| **Throughput targets updated** | 30 MB/s Python e2e · 120 MB/s parallel · 30 MB/s streaming |

---

## Installation

```bash
git clone https://github.com/slimissa/cagoule-bench-v2.git
cd cagoule-bench-v2

python3 -m venv venv
source venv/bin/activate

# Install CAGOULE first (local, not PyPI — not published there yet)
pip install -e /path/to/CAGOULE_v3_1_0 --no-deps
pip install -e ".[dev]" --no-deps
pip install cryptography argon2-cffi psutil rich click jinja2 pytest
```

---

## Démarrage rapide

```bash
cagoule-bench info                         # environnement — vérifie NEON, CTR backend
cagoule-bench run --suite ctr              # CTR vs CBC
cagoule-bench run --suite avx2             # AVX2 vs Scalar + CTR-lazy-path
cagoule-bench run --suite encryption       # vs AES-256-GCM vs ChaCha20-Poly1305
cagoule-bench run --suite parallel         # ProcessPool scaling
cagoule-bench run --suite streaming        # Large file streaming
cagoule-bench run --suite ctr --format notebook  # 7 chartes Jupyter
```

---

## Suites

| Suite | Description | CAGOULE |
|---|---|---|
| `encryption` | CAGOULE (CBC + CTR) vs AES-256-GCM vs ChaCha20-Poly1305 | v2.2.0+ |
| `ctr` | CTR vs CBC, 4x pipeline, symétrie, migration, bulk, `encrypt_v3` | v3.1.0+ |
| `kdf` | Argon2id × 27 + PBKDF2 + scrypt × 3 | v2.2.0+ |
| `memory` | Vault scaling + cache + fragmentation | v2.2.0+ |
| `parallel` | ProcessPool 1–20 workers + encrypt_bulk_ctr | v3.0.0+ |
| `streaming` | 50/100/500 MB — CTR + CBC | v3.0.0+ |
| `avx2` | AVX2 vs Scalar + CTR-lazy-path + NEON detection | v2.2.0+ |

---

## Résultats (CAGOULE v3.1.0, x86_64 AVX2, 20 cœurs)

| Métrique | CAGOULE-CTR | CAGOULE-CBC |
|---|---|---|
| encrypt 1 MB (Python e2e) | **21.9 MB/s** | 4.0 MB/s |
| encrypt 10 MB (Python e2e) | **19.9 MB/s** | 3.9 MB/s |
| CTR 4x C-layer | **65.1 MB/s** | 10.8 MB/s |
| Speedup CTR/CBC | **×5.3** | — |
| Symétrie enc/dec | **~1.0×** | — |
| Bulk KDF amortization (100 msgs) | **12.05×** | — |
| Parallel peak (16 workers) | **142.2 MB/s** | — |
| Streaming (500 MB) | **20.0 MB/s** | 20.0 MB/s |

**Comparaison (encrypt 1 MB):**

| Algorithme | Throughput | vs CAGOULE-CTR |
|---|---|---|
| AES-256-GCM | 2,370 MB/s | ×108 faster |
| ChaCha20-Poly1305 | 912 MB/s | ×42 faster |
| CAGOULE-CTR | 21.9 MB/s | — |

**Méthodologie :** mesuré sur x86-64 Linux, 20 cœurs, avec `--iterations 30 --warmup 5`. Les chiffres dépendent du hardware — re-mesurer sur votre cible avant de citer.

---

## Roadmap

- **v2.0.0** ✅ Streaming, AVX2, HistoryDB
- **v2.1.0** ✅ Notebook Reporter
- **v2.2.0** ✅ CTRSuite + CAGOULE v3.0.0
- **v2.3.0** ✅ v3.1.0 compatibility, history DB fix, NEON detection, `encrypt_v3` benchmark
- **v2.4.0** 🔜 WASM + benchmark browser (QuantOS Cloud Shell)

---

## Licence

MIT — [LICENSE](LICENSE)

**LASS** — QuantOS CTO  
[github.com/slimissa/cagoule-bench-v2](https://github.com/slimissa/cagoule-bench-v2) · [github.com/slimissa/cagoule](https://github.com/slimissa/cagoule)
```

---