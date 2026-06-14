"""
NotebookReporter — génération de notebooks Jupyter (.ipynb) pré-exécutés.

Option A : génère les cellules avec données injectées (toujours disponible).
Option B : pré-exécute le notebook via nbconvert + ipykernel pour produire
           un .ipynb avec outputs PNG inline — zéro action requise à l'ouverture.

Dépendances optionnelles (groupe [notebook] dans pyproject.toml) :
    nbformat>=5.9        — construction des cellules (Option A)
    matplotlib>=3.7      — graphiques
    seaborn>=0.12        — styling statistique
    pandas>=2.0          — DataFrames
    nbconvert>=7.0       — pré-exécution (Option B)
    ipykernel>=6.0       — kernel headless (Option B)

Usage :
    cagoule-bench run --format notebook
    cagoule-bench run --format notebook --no-execute   # Option A seulement
"""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bench.suites.base import BenchmarkResult

# ── Import guard : Option A (nbformat requis) ──────────────────────────────────
try:
    import nbformat
    from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook
    NBFORMAT_AVAILABLE = True
except ImportError:
    NBFORMAT_AVAILABLE = False

# ── Import guard : Option B (nbconvert + ipykernel optionnels) ────────────────
try:
    from nbconvert.preprocessors import ExecutePreprocessor as _ExecutePreprocessor
    NBCONVERT_AVAILABLE = True
except ImportError:
    _ExecutePreprocessor = None  # type: ignore
    NBCONVERT_AVAILABLE = False

# ── Matplotlib backend sûr pour SSH/CI ───────────────────────────────────────
import os as _os
_os.environ.setdefault("MPLBACKEND", "Agg")


def _check_deps(execute: bool = True) -> None:
    if not NBFORMAT_AVAILABLE:
        raise ImportError(
            "nbformat requis : pip install 'cagoule-bench[notebook]'"
        )
    if execute and not NBCONVERT_AVAILABLE:
        raise ImportError(
            "nbconvert + ipykernel requis pour la pré-exécution : "
            "pip install 'cagoule-bench[notebook]'"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Cellules Markdown
# ─────────────────────────────────────────────────────────────────────────────

def _cell_md_header(results: list[BenchmarkResult]) -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    suites = sorted({r.suite for r in results})
    algos  = sorted({r.algorithm for r in results})

    # Environnement depuis extra du premier résultat
    first_extra = results[0].extra if results else {}
    arch    = first_extra.get("arch", platform.machine())
    v30     = first_extra.get("cagoule_v30", False)
    backend = first_extra.get("matrix_backend", "unknown")

    cag_badge = "✅ v3.0.0 (CTR)" if v30 else "⚠️ <v3.0.0"
    n_results = len(results)
    n_suites  = len(suites)

    return f"""# 🔬 cagoule-bench — Rapport de Performance

**Date :** {ts}  
**Suites :** {', '.join(suites)}  
**Algorithmes :** {', '.join(algos)}  
**CAGOULE :** {cag_badge} — backend matrix: `{backend}`  
**Architecture :** `{arch}` · `{platform.processor() or platform.machine()}`  
**Résultats :** {n_results} entrées · {n_suites} suites

---

> *Ce notebook a été généré automatiquement par `cagoule-bench`.  
> Toutes les données sont injectées inline — aucune dépendance externe requise à l'exécution.*"""


def _cell_md_section(title: str, description: str = "") -> str:
    out = f"## {title}"
    if description:
        out += f"\n\n{description}"
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Cellules Code — données + imports
# ─────────────────────────────────────────────────────────────────────────────

def _results_to_records(results: list[BenchmarkResult]) -> list[dict]:
    return [
        {
            "suite":             r.suite,
            "name":              r.name,
            "algorithm":         r.algorithm,
            "data_size_bytes":   r.data_size_bytes,
            "data_size_kb":      round(r.data_size_bytes / 1024, 1),
            "mean_ms":           round(r.mean_ms, 4),
            "stddev_ms":         round(r.stddev_ms, 4),
            "p95_ms":            round(r.p95_ms, 4),
            "p99_ms":            round(r.p99_ms, 4),
            "throughput_mbps":   round(r.throughput_mbps, 3),
            "cv_percent":        round(r.cv_percent, 2),
            "peak_mb":           round(r.peak_mb, 3),
            "mode":              r.extra.get("mode", ""),
            "cagoule_v30":       r.extra.get("cagoule_v30", False),
            "n_messages":        r.extra.get("n_messages", None),
            "ct_overhead_bytes": r.extra.get("ct_overhead_bytes", None),
            "symmetry_ratio":    r.extra.get("symmetry_ratio_dec_enc", None),
            "target_mbps":       r.extra.get("target_mbps", None),
        }
        for r in results
    ]


def _cell_imports_and_data(results: list[BenchmarkResult]) -> str:
    records = _results_to_records(results)
    data_json = json.dumps(records, indent=2)

    return f"""import matplotlib
matplotlib.use('Agg')  # SSH/CI safe — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ── Style ──────────────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="deep")
PALETTE_ALGO = {{
    "CAGOULE-CTR":      "#1E7145",
    "CAGOULE-CBC":      "#2E75B6",
    "CAGOULE":          "#2E75B6",
    "AES-256-GCM":      "#C0392B",
    "ChaCha20-Poly1305":"#8E44AD",
    "CAGOULE-bulk-CTR": "#1A9850",
    "CAGOULE-individual-CTR": "#91CF60",
    "CAGOULE-migrate":  "#FC8D59",
}}

# ── Données injectées (cagoule-bench runtime) ──────────────────────────────
_raw = {data_json}

df = pd.DataFrame(_raw)
df['data_size_label'] = df['data_size_kb'].apply(
    lambda x: f"{{int(x)}}KB" if x < 1024 else f"{{int(x//1024)}}MB"
)

print(f"Résultats chargés : {{len(df)}} entrées · {{df['suite'].nunique()}} suites · {{df['algorithm'].nunique()}} algorithmes")
df.head(3)"""


# ─────────────────────────────────────────────────────────────────────────────
# Cellules Code — graphiques
# ─────────────────────────────────────────────────────────────────────────────

def _cell_chart_throughput_comparison() -> str:
    return '''# ── Chart 1 : Débit MB/s par algorithme et taille ────────────────────────────
# Graphique central du roadmap v3.0.0 : CTR vs CBC vs standards

enc_df = df[df['name'].str.startswith('encrypt') | df['name'].str.contains('ctr-encrypt|cbc-encrypt')].copy()
enc_df = enc_df[enc_df['throughput_mbps'] > 0]

if enc_df.empty:
    print("Aucune donnée encrypt disponible.")
else:
    sizes = enc_df['data_size_label'].unique()
    algos = enc_df['algorithm'].unique()

    fig, ax = plt.subplots(figsize=(12, 5))
    x = np.arange(len(sizes))
    width = 0.8 / max(len(algos), 1)

    for i, algo in enumerate(algos):
        sub = enc_df[enc_df['algorithm'] == algo]
        tp  = [sub[sub['data_size_label'] == s]['throughput_mbps'].mean() for s in sizes]
        color = PALETTE_ALGO.get(algo, None)
        offset = (i - len(algos)/2 + 0.5) * width
        bars = ax.bar(x + offset, tp, width * 0.9, label=algo, color=color)
        for bar, val in zip(bars, tp):
            if val > 0:
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                        f"{val:.1f}", ha='center', va='bottom', fontsize=7)

    ax.set_xlabel("Taille du message")
    ax.set_ylabel("Débit (MB/s)")
    ax.set_title("Débit chiffrement par algorithme et taille de message", fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(sizes)
    ax.legend(loc='upper left', fontsize=8)
    ax.set_ylim(bottom=0)
    # Ligne cible CTR v3.0.0
    if any('CTR' in a for a in algos):
        ax.axhline(15.0, color=PALETTE_ALGO["CAGOULE-CTR"], linestyle='--', alpha=0.5, label='Cible CTR 15 MB/s')
    plt.tight_layout()
    plt.savefig("chart_throughput.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_throughput.png")'''


def _cell_chart_latency_distribution() -> str:
    return '''# ── Chart 2 : Distribution de latence (p50, p95, p99) ───────────────────────
# Box plot des percentiles par algorithme

lat_df = df[df['mean_ms'] > 0].copy()

if lat_df.empty:
    print("Aucune donnée de latence disponible.")
else:
    # On prend la taille 1MB ou la plus grande disponible pour la comparaison
    target_kb = 1024.0
    avail_kbs = sorted(lat_df['data_size_kb'].unique())
    chosen_kb = min(avail_kbs, key=lambda x: abs(x - target_kb))
    sub = lat_df[lat_df['data_size_kb'] == chosen_kb]

    algos = sub['algorithm'].unique()
    metrics = ['mean_ms', 'p95_ms', 'p99_ms']
    labels  = ['p50 (mean)', 'p95', 'p99']
    x = np.arange(len(algos))
    width = 0.25

    fig, ax = plt.subplots(figsize=(10, 5))
    for j, (metric, label) in enumerate(zip(metrics, labels)):
        vals = [sub[sub['algorithm'] == a][metric].mean() for a in algos]
        bars = ax.bar(x + j*width, vals, width*0.9, label=label, alpha=0.85)
        for bar, val in zip(bars, vals):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.1,
                    f"{val:.1f}", ha='center', va='bottom', fontsize=7)

    ax.set_xlabel("Algorithme")
    ax.set_ylabel("Latence (ms)")
    size_label = f"{int(chosen_kb)}KB" if chosen_kb < 1024 else f"{int(chosen_kb//1024)}MB"
    ax.set_title(f"Distribution de latence — {size_label}", fontweight='bold')
    ax.set_xticks(x + width)
    ax.set_xticklabels([a.replace('-', '-\\n') for a in algos], fontsize=8)
    ax.legend()
    plt.tight_layout()
    plt.savefig("chart_latency.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_latency.png")'''


def _cell_chart_ctr_vs_cbc() -> str:
    return '''# ── Chart 3 : CTR vs CBC — gain par taille (v3.0.0 centerpiece) ─────────────

ctr = df[df['algorithm'].str.contains('CTR') & df['name'].str.contains('encrypt')].copy()
cbc = df[df['algorithm'].str.contains('CBC') & df['name'].str.contains('encrypt')].copy()

if ctr.empty or cbc.empty:
    print("Suite CTR ou données CBC non disponibles — skip Chart 3.")
else:
    # Merger sur la taille pour calculer le ratio
    ctr_g = ctr.groupby('data_size_kb')['throughput_mbps'].mean().reset_index()
    cbc_g = cbc.groupby('data_size_kb')['throughput_mbps'].mean().reset_index()
    merged = ctr_g.merge(cbc_g, on='data_size_kb', suffixes=('_ctr', '_cbc'))
    merged['speedup'] = merged['throughput_mbps_ctr'] / merged['throughput_mbps_cbc'].replace(0, float('nan'))
    merged['size_label'] = merged['data_size_kb'].apply(
        lambda x: f"{int(x)}KB" if x < 1024 else f"{int(x//1024)}MB"
    )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Débit absolu
    w = 0.35
    x = np.arange(len(merged))
    ax1.bar(x - w/2, merged['throughput_mbps_cbc'], w, label='CBC', color=PALETTE_ALGO['CAGOULE-CBC'])
    ax1.bar(x + w/2, merged['throughput_mbps_ctr'], w, label='CTR', color=PALETTE_ALGO['CAGOULE-CTR'])
    ax1.axhline(15.0, linestyle='--', color=PALETTE_ALGO['CAGOULE-CTR'], alpha=0.4, label='Cible CTR 15 MB/s')
    ax1.set_xticks(x); ax1.set_xticklabels(merged['size_label'])
    ax1.set_ylabel("Débit (MB/s)"); ax1.set_title("Débit CTR vs CBC")
    ax1.legend(fontsize=8); ax1.set_ylim(bottom=0)

    # Speedup
    colors = ['#1E7145' if s >= 1.0 else '#C0392B' for s in merged['speedup'].fillna(0)]
    ax2.bar(x, merged['speedup'], color=colors, edgecolor='white')
    ax2.axhline(1.0, color='gray', linestyle='-', alpha=0.5)
    ax2.axhline(3.0, color=PALETTE_ALGO['CAGOULE-CTR'], linestyle='--', alpha=0.5, label='Cible ×3')
    for xi, s in zip(x, merged['speedup'].fillna(0)):
        ax2.text(xi, s + 0.05, f"×{s:.1f}", ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax2.set_xticks(x); ax2.set_xticklabels(merged['size_label'])
    ax2.set_ylabel("Speedup CTR / CBC"); ax2.set_title("Facteur d'accélération CTR vs CBC")
    ax2.legend(fontsize=8)

    plt.suptitle("CAGOULE v3.0.0 — CTR vs CBC", fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig("chart_ctr_vs_cbc.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_ctr_vs_cbc.png")'''


def _cell_chart_scaling() -> str:
    return '''# ── Chart 4 : Scaling parallèle — workers × débit (Amdahl empirique) ─────────

par = df[df['name'].str.contains('worker|parallel|bulk')].copy()

if par.empty:
    print("Aucune donnée de scaling parallèle — skip Chart 4.")
else:
    fig, ax = plt.subplots(figsize=(9, 5))
    for algo in par['algorithm'].unique():
        sub = par[par['algorithm'] == algo].sort_values('throughput_mbps')
        if len(sub) < 2:
            continue
        workers = sub['name'].str.extract(r'([0-9]+)w(?:orker)?').astype(float)[0]
        tp = sub['throughput_mbps'].values
        if workers.notna().sum() < 2:
            continue
        color = PALETTE_ALGO.get(algo, None)
        ax.plot(workers[workers.notna()], tp[workers.notna()],
                marker='o', label=algo, color=color, linewidth=2)

    ax.axhline(80.0, linestyle='--', color='#1E7145', alpha=0.5, label='Cible CTR bulk 80 MB/s')
    ax.set_xlabel("Nombre de workers"); ax.set_ylabel("Débit agrégé (MB/s)")
    ax.set_title("Courbe de scaling parallèle — CAGOULE CTR bulk", fontweight='bold')
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig("chart_scaling.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_scaling.png")'''


def _cell_chart_mersenne_heatmap() -> str:
    return '''# ── Chart 5 : Heatmap des 8 primes Mersenne-64 × taille (si AVX2 suite) ──────

mers = df[df['suite'] == 'avx2'].copy()

if mers.empty or 'prime_idx' not in mers.columns:
    # Tenter de récupérer depuis extra si disponible
    print("Suite avx2 / données Mersenne primes non disponibles — skip Chart 5.")
else:
    pivot = mers.pivot_table(values='throughput_mbps', index='prime_idx',
                              columns='data_size_label', aggfunc='mean')
    fig, ax = plt.subplots(figsize=(10, 5))
    sns.heatmap(pivot, annot=True, fmt=".1f", cmap="YlGn",
                cbar_kws={"label": "Débit MB/s"}, ax=ax)
    ax.set_title("Débit par prime Mersenne-64 et taille de message", fontweight='bold')
    ax.set_xlabel("Taille"); ax.set_ylabel("Index prime pool")
    plt.tight_layout()
    plt.savefig("chart_mersenne_heatmap.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_mersenne_heatmap.png")'''


def _cell_chart_ct_overhead() -> str:
    return '''# ── Chart 6 : Overhead CT — CTR (0 padding) vs CBC (PKCS7) ──────────────────

oh_df = df[df['ct_overhead_bytes'].notna()].copy()

if oh_df.empty:
    print("Données overhead CT non disponibles — skip Chart 6.")
else:
    fig, ax = plt.subplots(figsize=(9, 4))
    for algo in oh_df['algorithm'].unique():
        sub = oh_df[oh_df['algorithm'] == algo].sort_values('data_size_kb')
        color = PALETTE_ALGO.get(algo, None)
        ax.plot(sub['data_size_kb'], sub['ct_overhead_bytes'],
                marker='s', label=algo, color=color, linewidth=2)

    ax.set_xscale('log'); ax.set_xlabel("Taille plaintext (KB, log)")
    ax.set_ylabel("Overhead ciphertext (bytes)")
    ax.set_title("Overhead ciphertext : CTR (zéro padding) vs CBC (PKCS7)", fontweight='bold')
    ax.axhline(65, color=PALETTE_ALGO["CAGOULE-CTR"], linestyle='--', alpha=0.4,
               label="CTR overhead constant (header+tag = ~65B)")
    ax.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig("chart_ct_overhead.png", dpi=150, bbox_inches='tight')
    plt.show()
    print("✓ chart_ct_overhead.png")'''


def _cell_summary(results: list[BenchmarkResult]) -> str:
    # Compute key numbers
    ctr_results = [r for r in results if 'CTR' in r.algorithm and 'encrypt' in r.name and r.throughput_mbps > 0]
    cbc_results = [r for r in results if 'CBC' in r.algorithm and 'encrypt' in r.name and r.throughput_mbps > 0]

    ctr_best = max((r.throughput_mbps for r in ctr_results), default=0)
    cbc_best = max((r.throughput_mbps for r in cbc_results), default=0)
    ratio = f"×{ctr_best/cbc_best:.1f}" if cbc_best > 0 else "N/A"
    n_algo = len({r.algorithm for r in results})

    return f"""# ── Conclusions automatiques ──────────────────────────────────────────────

summary = {{
    "total_results":      {len(results)},
    "algorithms_tested":  {n_algo},
    "ctr_peak_mbps":      {round(ctr_best, 2)},
    "cbc_peak_mbps":      {round(cbc_best, 2)},
    "ctr_vs_cbc_ratio":   "{ratio}",
    "ctr_target_15mbps":  {ctr_best >= 15.0},
}}

print("=" * 55)
print("  CAGOULE v3.0.0 — Résultats clés")
print("=" * 55)
for k, v in summary.items():
    print(f"  {{k:<28}} {{v}}")
print("=" * 55)

if summary["ctr_target_15mbps"]:
    print("  ✅ Cible roadmap >15 MB/s Python e2e : ATTEINTE")
else:
    gap = 15.0 - summary["ctr_peak_mbps"]
    print("  ⚠️  Cible >15 MB/s : " + str(round(gap, 1)) + " MB/s restants (portage C wrapper v3.1.0)")"""


# ─────────────────────────────────────────────────────────────────────────────
# Assemblage du notebook
# ─────────────────────────────────────────────────────────────────────────────

def _build_notebook(results: list[BenchmarkResult]) -> "nbformat.NotebookNode":
    # Merge all charts into one cell for reliable pre-execution
    all_charts = (
        _cell_imports_and_data(results) + "\n\n" +
        _cell_chart_throughput_comparison() + "\n\n" +
        _cell_chart_latency_distribution() + "\n\n" +
        _cell_chart_ctr_vs_cbc() + "\n\n" +
        _cell_chart_scaling() + "\n\n" +
        _cell_chart_ct_overhead() + "\n\n" +
        _cell_chart_mersenne_heatmap() + "\n\n" +
        _cell_summary(results)
    )

    cells = [
        new_markdown_cell(_cell_md_header(results)),
        new_code_cell(all_charts),
    ]

    nb = new_notebook(cells=cells)
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language":     "python",
        "name":         "python3",
    }
    nb.metadata["language_info"] = {
        "name":    "python",
        "version": "3.12",
    }
    nb.metadata["cagoule_bench"] = {
        "generated_by":   "NotebookReporter",
        "format_version": "2.2.0",
        "timestamp":      time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_results":      len(results),
    }
    return nb


# ─────────────────────────────────────────────────────────────────────────────
# Reporter public
# ─────────────────────────────────────────────────────────────────────────────

class NotebookReporter:
    """
    Génère un notebook Jupyter .ipynb depuis les résultats de cagoule-bench.

    Option A (execute=False) : cellules avec données injectées, pas de outputs.
    Option B (execute=True)  : pré-exécution headless via nbconvert — outputs
                               PNG inline, zéro action requise à l'ouverture.
    """

    def __init__(self, execute: bool = True, timeout: int = 300,
                 kernel: str = "python3"):
        self.execute = execute
        self.timeout = timeout
        self.kernel  = kernel

    def report(self, results: list[BenchmarkResult],
               output_path: str | Path) -> Path:
        """
        Génère le notebook et le sauvegarde à output_path.

        Args:
            results:     Liste de BenchmarkResult depuis l'orchestrateur.
            output_path: Chemin de sortie (.ipynb).

        Returns:
            Path du fichier généré.
        """
        _check_deps(execute=self.execute)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Option A : construction des cellules ──────────────────────────
        nb = _build_notebook(results)

        # ── Option B : pré-exécution headless ────────────────────────────
        if self.execute and NBCONVERT_AVAILABLE:
            nb = self._execute_notebook(nb, output_path.parent)

        # ── Écriture ──────────────────────────────────────────────────────
        with open(output_path, "w", encoding="utf-8") as f:
            nbformat.write(nb, f)

        return output_path

    def _execute_notebook(self, nb: "nbformat.NotebookNode",
                          work_dir: Path) -> "nbformat.NotebookNode":
        """
        Pré-exécute le notebook via ExecutePreprocessor.

        Les outputs (figures PNG base64) sont injectés dans les cellules.
        Le notebook résultant s'ouvre avec tous les graphiques visibles.
        """
        ep = _ExecutePreprocessor(
            timeout=self.timeout,
            kernel_name=self.kernel,
            allow_errors=True,   # Un graphique qui échoue ne bloque pas tout
        )
        try:
            nb, _ = ep.preprocess(nb, {"metadata": {"path": str(work_dir)}})
        except Exception as exc:   # noqa: BLE001
            # Si l'exécution échoue (kernel absent, etc.), retourner le
            # notebook non-exécuté plutôt que de planter.
            import warnings
            warnings.warn(
                f"NotebookReporter: pré-exécution échouée ({exc}). "
                "Le notebook est généré sans outputs — "
                "pip install 'cagoule-bench[notebook]' et ipykernel>=6.0.",
                stacklevel=2,
            )
        return nb
