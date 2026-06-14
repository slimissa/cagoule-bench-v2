# cagoule-bench v2.2.0

Suite de benchmarking académique officielle pour **CAGOULE** — Cryptographie Algébrique Géométrique par Ondes et Logique Entrelacée.

> **Compatibilité cible :** CAGOULE v3.0.0+ (CTR mode · AVX2 4x · `encrypt_ctr` · `encrypt_bulk_ctr`)  
> Compatible descendante : CAGOULE v2.2.0+ (CBC uniquement)

---

## Nouveautés v2.2.0

| Feature | Description |
|---|---|
| **CTRSuite** | Benchmark CTR vs CBC, pipeline 4x, symétrie encrypt/decrypt, migration, bulk KDF |
| **EncryptionSuite** | `encrypt_cbc()` historique + `encrypt_ctr()` séparé — HistoryDB par mode |
| **ParallelSuite** | `encrypt_bulk_ctr` ProcessPool — cible >80 MB/s à 20 cœurs |
| **StreamingSuite** | CTR streaming — cible >18 MB/s vs ~7.8 MB/s CBC |
| **AVX2Suite** | Bloc CTR 4x — gain ILP des 4 blocs simultanés |
| **Notebook Reporter** | `.ipynb` pré-exécuté (Option B) — 7 graphiques Matplotlib/Seaborn inline |
| **14 bugs corrigés** | Critiques (3), sérieux (3), moyens (4), mineurs (4) |

---

## Installation

```bash
git clone https://github.com/slimissa/cagoule-bench-v2.git
cd cagoule-bench-v2

python3 -m venv venv
source venv/bin/activate

pip install -e ".[dev]"
pip install "cagoule>=3.0.0"
pip install -e ".[notebook]"  # optionnel
```

---

## Démarrage rapide

```bash
cagoule-bench run                          # toutes les suites sauf avx2
cagoule-bench run --suite ctr              # CTR vs CBC (v3.0.0 requis)
cagoule-bench run --suite ctr --format notebook  # rapport Jupyter
cagoule-bench info                         # environnement
cagoule-bench list-suites                  # suites disponibles
```

---

## Suites

| Suite | Description | CAGOULE |
|---|---|---|
| `encryption` | CAGOULE (CBC + CTR) vs AES-256-GCM vs ChaCha20-Poly1305 | v2.2.0+ |
| `ctr` | CTR vs CBC, 4x pipeline, symétrie, migration, bulk | **v3.0.0+** |
| `kdf` | Argon2id × 27 + PBKDF2 + scrypt × 3 | v2.2.0+ |
| `memory` | Vault scaling + cache + fragmentation | v2.2.0+ |
| `parallel` | ProcessPool 1–20 workers + encrypt_bulk_ctr | v3.0.0+ |
| `streaming` | 50/100/500 MB — CTR + CBC | v3.0.0+ |
| `avx2` | AVX2 vs Scalaire + CTR 4x — opt-in (`--avx2`) | v2.2.0+ |

---

## CTRSuite — cible roadmap v3.0.0

```bash
cagoule-bench run --suite ctr --format console html notebook
```

| Benchmark | Mesure | Cible |
|---|---|---|
| `ctr-encrypt-*` vs `cbc-encrypt-*` | Gain CTR / CBC par taille | >15 MB/s Python |
| `ctr-auto-*` | Pipeline 4x C-layer | >25 MB/s |
| `ctr-sym-*` | Symétrie encrypt = decrypt | ratio ≈ 1.0 |
| `migrate-cbc-ctr-*` | Coût migration v0x01 → v0x02 | — |
| `bulk-ctr-Nmsgs` | Amortissement KDF bulk | >80 MB/s @ 20 cœurs |

---

## Notebook Reporter

```bash
pip install 'cagoule-bench[notebook]'
cagoule-bench run --suite ctr encryption --format notebook
```

7 graphiques pré-exécutés : débit, latence p95/p99, CTR vs CBC speedup, Amdahl parallèle, overhead CT, heatmap Mersenne-64, conclusions automatiques.

---

## Historique

```bash
cagoule-bench run --db .cagoule_bench/history.db --tag v3.0.0
cagoule-bench history
cagoule-bench compare-history --suite ctr --algo CAGOULE-CTR --name ctr-encrypt-1MB
cagoule-bench compare baseline.json current.json
```

---

## Configuration

```toml
# cagoule_bench.toml
iterations = 500
warmup     = 10
formats    = ["console", "json", "html"]
db_path    = ".cagoule_bench/history.db"

[suites.ctr]
iterations = 200

[notebook]
execute   = true
```

---

## Résultats (CAGOULE v3.0.0, x86_64 AVX2, 20 cœurs)

| Métrique | CAGOULE-CTR | CAGOULE-CBC |
|---|---|---|
| encrypt 1 MB | **22.3 MB/s** | 6.9 MB/s |
| encrypt 10 MB | **21.3 MB/s** | 6.8 MB/s |
| CTR 4x C-layer | **31.0 MB/s** | 10.8 MB/s |
| Speedup CTR/CBC | **×3.2** | — |
| Overhead \|CT\| | \|PT\| + 65B | \|PT\| + PKCS7 + 65B |
| Symétrie enc/dec | **1.0×** | — |
| Bulk 20 cœurs | **>80 MB/s** | ~40 MB/s |

---

## Tests

```bash
pytest tests/ -v                    # 117 tests
pytest tests/ -v -m slow            # 3 tests lents
pytest tests/ --cov=bench           # couverture
```

---

## Roadmap

- **v2.0.0** ✅ Streaming, AVX2, HistoryDB, Mann-Whitney, HTML dashboard, CI multi-arch
- **v2.1.0** ✅ Notebook Reporter — `.ipynb` pré-exécuté, 7 graphiques
- **v2.2.0** ✅ CTRSuite + CAGOULE v3.0.0 (CTR, encrypt_bulk_ctr, migration, streaming CTR)
- **v2.3.0** 🔜 WASM + benchmark browser (QuantOS Cloud Shell)

---

## Licence

MIT — [LICENSE](LICENSE)

**LASS** — QuantOS CTO  
[github.com/slimissa/cagoule-bench-v2](https://github.com/slimissa/cagoule-bench-v2) · [github.com/slimissa/cagoule](https://github.com/slimissa/cagoule)