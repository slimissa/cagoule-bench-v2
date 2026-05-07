# cagoule-bench v2.0.0

Suite de benchmarking académique officielle pour **CAGOULE** — Cryptographie Algébrique Géométrique par Ondes et Logique Entrelacée.

> **Compatibilité cible :** CAGOULE v2.2.0+ (AVX2 · `backend_info` · `DiffusionMatrixC.free()`)

---

## Nouveautés v2.0.0

| Feature | Description |
|---|---|
| **Suite AVX2** | Benchmark `CAGOULE-AVX2` vs `CAGOULE-Scalar` via subprocess isolé (`CAGOULE_FORCE_SCALAR=1`) |
| **HistoryDB** | Base SQLite locale — suivi de tendance, drift, détection de régression sur N derniers runs |
| **Mann-Whitney U** | Comparaison statistique non-paramétrique + Cohen's d + bootstrap CI (intervalles de confiance) |
| **StreamingSuite** | Chiffrement chunked 50MB/100MB/500MB — RAM = O(chunk), validation mémoire constante |
| **scrypt** dans KdfSuite | 3 configurations OWASP + comparatif Argon2id/PBKDF2 avec scores de sécurité |
| **Config file** | `cagoule_bench.toml` ou `[tool.cagoule-bench]` dans `pyproject.toml` |
| **CLI enrichi** | `history`, `compare-history`, `profile`, `info`, `list-suites` — 7 commandes |
| **CI multi-arch** | GitHub Actions : x86_64 + ARM64 + scalaire forcé + schedule hebdomadaire |
| **HTML Dashboard** | Rapport interactif auto-contenu via Jinja2 + Chart.js — publiable sur GitHub Pages |
| **14 bugs corrigés** | Critiques (3), sérieux (3), moyens (4), mineurs (4) — documentés dans le build report |

---

## Installation

```bash
# Cloner le dépôt
git clone https://github.com/slimissa/cagoule-bench-v2.git
cd cagoule-bench-v2

# Créer l'environnement virtuel
python3 -m venv venv
source venv/bin/activate

# Installer cagoule-bench + dépendances
pip install -e ".[dev]"

# Installer CAGOULE v2.2.0 (recommandé pour la suite avx2)
pip install "cagoule>=2.2.0"
```

---

## Démarrage rapide

```bash
# Toutes les suites (sauf avx2 qui est opt-in)
cagoule-bench run

# Avec la suite AVX2 — CAGOULE v2.2.0 requis
cagoule-bench run --avx2

# Suites ciblées + formats multiples
cagoule-bench run --suite encryption avx2 --format console json html

# Profiling haute précision d'une suite
cagoule-bench profile encryption --iterations 1000 --size 1048576

# Informations environnement (backend, AVX2, dépendances)
cagoule-bench info

# Lister toutes les suites disponibles
cagoule-bench list-suites
```

---

## Suites disponibles

| Suite | Description | Opt-in |
|---|---|---|
| `encryption` | CAGOULE vs AES-256-GCM vs ChaCha20-Poly1305 (5 tailles, encrypt/decrypt) | — |
| `kdf` | Argon2id × 27 combos + PBKDF2-SHA256 + scrypt × 3 configs | — |
| `memory` | Scalabilité vault (10/100/1000 entrées) + cache chaud/froid + fragmentation | — |
| `parallel` | ProcessPoolExecutor 1/2/4/8 workers + ThreadPoolExecutor (preuve GIL) | — |
| `streaming` | Chiffrement chunked 50/100/500 MB — streaming mode | — |
| `avx2` | CAGOULE-AVX2 vs CAGOULE-Scalar — subprocess isolé, gain vectorisation | `--avx2` |

---

## Historique et détection de régression

```bash
# Sauvegarder dans l'historique SQLite + détecter régressions
cagoule-bench run --db .cagoule_bench/history.db --tag main

# Voir les 10 derniers runs
cagoule-bench history --db .cagoule_bench/history.db

# Détail d'un run spécifique
cagoule-bench history --detail <run_id>

# Tendance d'un benchmark spécifique (20 derniers runs)
cagoule-bench compare-history --suite encryption --algo CAGOULE --name encrypt-1MB

# Comparer deux fichiers JSON
cagoule-bench compare baseline.json current.json --threshold -5.0
```

---

## Configuration

Créer `cagoule_bench.toml` à la racine :

```toml
iterations = 500
warmup     = 10
formats    = ["console", "json", "html"]
output_dir = "./benchmark_results"
db_path    = ".cagoule_bench/history.db"
regression_threshold = -5.0
```

Ou dans `pyproject.toml` :

```toml
[tool.cagoule-bench]
iterations = 500
formats    = ["console", "json"]
```

---

## Résultats (CAGOULE v2.2.0, x86_64 AVX2 actif, 20 cœurs)

### Chiffrement (suite encryption, 50 itérations)

| Métrique | CAGOULE | AES-256-GCM | ChaCha20-Poly1305 |
|---|---|---|---|
| Débit encrypt 1 KB | 5.1 MB/s | 180.8 MB/s | 190.9 MB/s |
| Débit encrypt 1 MB | 4.8 MB/s | 4,225.6 MB/s | 1,852.2 MB/s |
| Débit encrypt 10 MB | 4.6 MB/s | 3,433.1 MB/s | 1,493.3 MB/s |
| Débit decrypt 1 MB | 4.1 MB/s | 4,132.0 MB/s | 1,844.9 MB/s |
| Stabilité (CV%) | < 2% | < 5% | < 10% |

### AVX2 vs Scalaire (suite avx2, 30 itérations)

| Taille | AVX2 | Scalaire | Gain |
|---|---|---|---|
| 64 KB | 5.4 MB/s | 5.4 MB/s | ~0% |
| 1 MB | 4.8 MB/s | 4.8 MB/s | ~0% |
| 10 MB | 4.7 MB/s | 4.8 MB/s | ~0% |

### Analyse de performance

| Couche | Débit | Notes |
|---|---|---|
| C — multiplication matricielle (scalaire) | 10.5 MB/s | `test_matrix` C |
| C — couche algébrique complète | 9.7 MB/s | `test_cipher` C |
| Python — `cagoule.encrypt()` | **5.0 MB/s** | API publique |

L'écart entre la couche C (9.7 MB/s) et l'API Python (5.0 MB/s) provient du wrapper CGL1 (header, AEAD ChaCha20-Poly1305, copies mémoire). L'AVX2 accélère la multiplication matricielle (~40% du pipeline). Les 60% restants (S-box, round keys, sérialisation) n'en bénéficient pas encore — travail prévu pour CAGOULE v2.3.0.

> **Cible roadmap CAGOULE v2.2.0 :** ≥ 23.4 MB/s. Le travail d'optimisation continue.

---

## Tests

```bash
# Tests unitaires rapides (pas de crypto réel) — 117 tests
pytest tests/ -v

# Tests lents (streaming, avec crypto réel) — 3 tests
pytest tests/ -v -m slow

# Tous les tests — 120 tests
pytest tests/ -v -m ""

# Avec couverture
pytest tests/ --cov=bench --cov-report=html
```

---

## Architecture

```
cagoule-bench/
├── bench/
│   ├── __init__.py          # API publique (26 exports)
│   ├── cli.py               # Click CLI — 7 commandes
│   ├── config.py            # Config loader (TOML, 3 niveaux de priorité)
│   ├── orchestrator.py      # Orchestration + régression
│   ├── metrics/
│   │   ├── time_collector.py    # Mesure nanoseconde (perf_counter_ns)
│   │   ├── memory_collector.py  # tracemalloc + snapshot differencing
│   │   ├── cpu_collector.py     # psutil daemon thread
│   │   └── stats.py             # Mann-Whitney U, Cohen's d, bootstrap CI
│   ├── suites/
│   │   ├── base.py                  # BaseSuite ABC + BenchmarkResult
│   │   ├── encryption_suite.py      # CAGOULE v2.2.0 + AES + ChaCha20
│   │   ├── kdf_suite.py             # Argon2id + PBKDF2 + scrypt
│   │   ├── memory_suite.py          # Vault scaling + cache analysis
│   │   ├── parallel_suite.py        # ProcessPoolExecutor + GIL proof
│   │   ├── streaming_suite.py       # Chunked streaming 50/100/500 MB
│   │   └── avx2_suite.py            # AVX2 vs scalar (subprocess isolé)
│   ├── reporters/
│   │   ├── console_reporter.py      # Rich tables + overhead analysis
│   │   ├── data_reporters.py        # JSON, CSV, Markdown
│   │   └── html_reporter.py         # Jinja2 + Chart.js dashboard
│   └── db/
│       └── history.py               # SQLite + trend + drift
├── tests/
│   ├── test_config.py        # 16 tests
│   ├── test_db.py            # 27 tests
│   ├── test_stats.py         # 32 tests
│   └── test_suites.py        # 45 tests
├── .github/workflows/
│   └── bench.yml             # CI : test, benchmark, scalar, ARM64, lint
├── cagoule_bench.toml        # Configuration par défaut
├── pyproject.toml            # Build system + dépendances
└── README.md
```

---

## Roadmap

- **v2.0.0** ✅ StreamingSuite, AVX2Suite, HistoryDB, Mann-Whitney U, scrypt, HTML dashboard, CI multi-arch, 14 bugs corrigés
- **v2.1.0** 🔜 Notebook reporter (Jupyter .ipynb)
- **v2.2.0** 🔜 WASM build + benchmark browser (QuantOS Cloud Shell)

---

## Licence

MIT License — voir [LICENSE](LICENSE)

---

Auteur : **LASS** — QuantOS CTO
- [github.com/slimissa/cagoule-bench-v2](https://github.com/slimissa/cagoule-bench-v2)
- CAGOULE : [github.com/slimissa/cagoule](https://github.com/slimissa/cagoule)
```