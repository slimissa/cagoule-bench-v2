# cagoule-bench v2.0.0

Suite de benchmarking académique officielle pour **CAGOULE** — Cryptographie Algébrique Géométrique par Ondes et Logique Entrelacée.

> **Compatibilité cible :** CAGOULE v2.2.0+ (AVX2 · `backend_info` · `DiffusionMatrixC.free()`)

---

## Nouveautés v2.0.0

| Feature | Description |
|---|---|
| **Suite AVX2** | Benchmark `CAGOULE-AVX2` vs `CAGOULE-Scalar` via `CAGOULE_FORCE_SCALAR=1` |
| **HistoryDB** | SQLite local — trend, drift, régression sur N derniers runs |
| **Mann-Whitney U** | Comparaison statistique non-paramétrique + Cohen's d + bootstrap CI |
| **StreamingSuite** | Chiffrement chunked 50MB/100MB/500MB — RAM = O(chunk) |
| **scrypt** dans KdfSuite | 3 configurations OWASP + comparatif Argon2id/PBKDF2 |
| **Config file** | `cagoule_bench.toml` ou `[tool.cagoule-bench]` dans `pyproject.toml` |
| **CLI enrichi** | `history`, `compare-history`, `profile`, `info`, `list-suites` |
| **CI multi-arch** | x86_64 + ARM64 + scalar forcé dans GitHub Actions |

---

## Installation

```bash
pip install -e .
# Avec CAGOULE v2.2.0 (recommandé pour la suite avx2)
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
```

---

## Suites disponibles

| Suite | Description | Opt-in |
|---|---|---|
| `encryption` | CAGOULE vs AES-256-GCM vs ChaCha20-Poly1305 | — |
| `kdf` | Argon2id × 27 combos + PBKDF2-SHA256 + scrypt | — |
| `memory` | Scalabilité vault tracemalloc + cache chaud/froid | — |
| `parallel` | ProcessPoolExecutor 1/2/4/8 workers — speedup & efficacité | — |
| `streaming` | Chiffrement chunked 50/100/500 MB | — |
| `avx2` | CAGOULE-AVX2 vs CAGOULE-Scalar — gain vectorisation | `--avx2` |

---

## Historique et détection de régression

```bash
# Sauvegarder dans l'historique SQLite + détecter régressions
cagoule-bench run --db .cagoule_bench/history.db --tag main

# Voir les 10 derniers runs
cagoule-bench history --db .cagoule_bench/history.db

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

## Résultats v2.1.0 (CAGOULE v2.2.0, x86_64 AVX2 actif)

| Métrique | Valeur |
|---|---|
| Débit CAGOULE (1 MB) | **23.4 MB/s** |
| Overhead vs AES-256-GCM | ~−34% |
| Overhead vs ChaCha20-Poly1305 | ~−28% |
| Latence encrypt 1 MB | **42.8 ms** |
| Symétrie encrypt/decrypt | ~1× |
| Empreinte mémoire | **3.2 MB** |

> Cible v2.2.0 avec AVX2 : **> 30 MB/s** (+25–30%)

---

## Tests

```bash
# Tests unitaires rapides (pas de crypto réel)
pytest tests/ -v

# Tests lents (streaming, avec crypto réel)
pytest tests/ -v -m slow

# Avec couverture
pytest tests/ --cov=bench --cov-report=html
```

---

## Architecture

```
bench/
├── cli.py            # Click CLI — run, compare, history, profile, info
├── config.py         # Config loader (TOML)
├── orchestrator.py   # Orchestration + régression
├── metrics/
│   ├── time_collector.py
│   ├── memory_collector.py
│   ├── cpu_collector.py
│   └── stats.py      # Mann-Whitney U, Cohen's d, bootstrap CI
├── suites/
│   ├── encryption_suite.py   # CAGOULE v2.2.0 + AES + ChaCha20
│   ├── kdf_suite.py          # Argon2id + PBKDF2 + scrypt
│   ├── memory_suite.py       # tracemalloc + cache
│   ├── parallel_suite.py     # ProcessPoolExecutor
│   ├── streaming_suite.py    # Chunked streaming
│   └── avx2_suite.py         # AVX2 vs scalar delta
├── reporters/
│   ├── console_reporter.py   # rich tables + AVX2 panel
│   ├── data_reporters.py     # JSON, CSV, Markdown
│   └── html_reporter.py      # Jinja2 + Chart.js dashboard
└── db/
    └── history.py            # SQLite history + trend + drift
```

---

## Roadmap

- **v2.0.0** ✅ AVX2 suite, HistoryDB, Mann-Whitney, streaming, scrypt, CLI enrichi
- **v2.1.0** 🔜 Notebook reporter (Jupyter .ipynb)
- **v2.2.0** 🔜 WASM build + benchmark browser (QuantOS Cloud Shell)

---

Auteur : **LASS** — QuantOS CTO · [github.com/slimissa/cagoule-bench](https://github.com/slimissa/cagoule-bench) · MIT License
