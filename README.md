# cagoule-bench v2.2.0

Suite de benchmarking académique officielle pour **CAGOULE** — Cryptographie Algébrique Géométrique par Ondes et Logique Entrelacée.

> **Compatibilité cible :** CAGOULE v3.1.0+ (CTR mode · AVX2 4x/lazy-reduction · NEON (ARM) · `encrypt_ctr` · `encrypt_bulk_ctr` · `encrypt_v3`/`decrypt_v3` · `CagouleStreamCtx`)  
> Compatible descendante : CAGOULE v2.2.0+ (CBC uniquement)

---

## Nouveautés v2.2.0

| Feature | Description |
|---|---|
| **CTRSuite** | Benchmark CTR vs CBC, pipeline 4x, symétrie encrypt/decrypt, migration, bulk KDF, `encrypt_v3`/`decrypt_v3` (API C unifiée) |
| **EncryptionSuite** | `encrypt_cbc()` historique + `encrypt_ctr()` séparé — HistoryDB par mode |
| **ParallelSuite** | `encrypt_bulk_ctr` ProcessPool — cible >120 MB/s à 20 cœurs |
| **StreamingSuite** | CTR streaming (chunking Python) — cible >30 MB/s vs ~7.8 MB/s CBC |
| **AVX2Suite** | Bloc CBC AVX2 vs scalaire + **CTR-lazy-path** (`cagoule_matrix_mul_avx2_lazy`, `ctr_backend`/`ctr_4x_available` via `get_backend_info_v310()`) |
| **Notebook Reporter** | `.ipynb` pré-exécuté (Option B) — 7 graphiques Matplotlib/Seaborn inline |
| **HistoryDB** | Régression détectée par version CAGOULE (`cagoule_version`), plus de mélange v3.0.0/v3.1.0 dans le baseline |
| **`_find_lib()` warning** | Divergence entre copies de `libcagoule.so` détectée et propagée (`lib_divergence_warning` sur chaque résultat) — n'interrompt pas le run |
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

## CTRSuite — cible v3.1.0 (fix AVX2 lazy-reduction)

```bash
cagoule-bench run --suite ctr --format console html notebook
```

| Benchmark | Mesure | Cible |
|---|---|---|
| `ctr-encrypt-*` vs `cbc-encrypt-*` | Gain CTR / CBC par taille | >30 MB/s Python |
| `ctr-auto-*` | Pipeline 4x C-layer | >50 MB/s |
| `ctr-sym-*` | Symétrie encrypt = decrypt | ratio ≈ 1.0 |
| `migrate-cbc-ctr-*` | Coût migration v0x01 → v0x02 | — |
| `bulk-ctr-Nmsgs` | Amortissement KDF bulk | >120 MB/s @ 20 cœurs |
| `encrypt-v3-*` / `decrypt-v3-*` | API C unifiée mono-message (`cagoule_encrypt_v3`) | — *(KDF par appel, non comparable aux lignes ci-dessus)* |

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
cagoule-bench run --db .cagoule_bench/history.db --tag v3.1.0
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

## Résultats (CAGOULE v3.1.0, x86_64 AVX2 — fix lazy-reduction, 20 cœurs)

> ⚠️ **PLACEHOLDER — chiffres v3.0.0 retirés, pas encore remesurés sur v3.1.0.**
> Les valeurs ci-dessous doivent être remplies après un run
> `cagoule-bench run --suite ctr --format console` sur le matériel de
> référence réel (pas un environnement virtualisé/sandbox — voir
> `SECURITY.md` §6.1 sur la variance mono-vCPU). Ne PAS republier les
> anciens chiffres v3.0.0 (22.3 / 21.3 / 31.0 MB/s, ×3.2) tels quels : le
> fix AVX2 lazy-reduction change le débit CTR d'un facteur ~2x côté
> C-layer, donc ces nombres sont maintenant faux pour v3.1.0, pas juste
> obsolètes.

| Métrique | CAGOULE-CTR (v3.1.0) | CAGOULE-CBC | Cible v3.1.0 |
|---|---|---|---|
| encrypt 1 MB (Python e2e) | `TBD MB/s` | `TBD MB/s` | >30 MB/s |
| encrypt 10 MB (Python e2e) | `TBD MB/s` | `TBD MB/s` | >30 MB/s |
| CTR 4x C-layer | `TBD MB/s` | `TBD MB/s` | >50 MB/s |
| Speedup CTR/CBC | `TBD×` | — | ×4+ |
| Overhead \|CT\| | \|PT\| + 65B | \|PT\| + PKCS7 + 65B | — |
| Symétrie enc/dec | `TBD×` | — | ≈ 1.0× |
| Bulk 20 cœurs | `TBD MB/s` | `TBD MB/s` | >120 MB/s |

<!--
Remplir après un run réel :
  cagoule-bench run --suite ctr --format console --tag v3.1.0
Voir aussi `cagoule-bench run --suite avx2` pour les nombres CTR-lazy-path
(cagoule_matrix_mul_avx2_lazy, distinct du chemin CBC ci-dessus) et
`get_backend_info_v310()` pour confirmer ctr_backend="C" / ctr_4x_available
avant de prendre les chiffres au sérieux -- un run avec matrix_backend
"scalar" ou lib_divergence_warning=True dans les résultats ne doit PAS
être utilisé pour remplir ce tableau (voir orchestrator.py, tâche 1 de
l'audit de release v3.1.0).
-->

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