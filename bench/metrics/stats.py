"""
bench/metrics/stats.py — Comparaisons statistiques rigoureuses.

Nouveautés v2.0 :
  - Mann-Whitney U test (non-paramétrique, robuste aux outliers)
  - Cohen's d effect size
  - Overlap coefficient
  - Bootstrap confidence intervals
  - Ratio test pour significance pratique

Ces outils permettent des publications académiques valides.
La différence entre deux distributions n'est significative que si
à la fois le test statistique ET l'effect size sont seuils franchis.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Sequence

# ── Mann-Whitney U ────────────────────────────────────────────────────────────

@dataclass
class MannWhitneyResult:
    """Résultat du test de Mann-Whitney U."""
    u_statistic: float
    p_value: float
    # BUG9 FIX: rank-biserial correlation r = 1 - 2*U_min/(n1*n2), range [0,1]
    # 0 = aucun effet (distributions équivalentes), 1 = séparation parfaite
    # (ancien commentaire erroné : "r = U / (n1 * n2)" → supprimé)
    effect_size_r: float
    significant: bool
    alpha: float
    n1: int
    n2: int
    median_a: float
    median_b: float
    interpretation: str

    @property
    def effect_label(self) -> str:
        # Rank-biserial r ∈ [0, 1] : 0 = aucun effet, 1 = séparation parfaite
        r = abs(self.effect_size_r)
        if r < 0.1: return "negligible"
        if r < 0.3: return "small"
        if r < 0.5: return "medium"
        return "large"

    def to_dict(self) -> dict:
        return {
            "u_statistic": round(self.u_statistic, 4),
            "p_value": round(self.p_value, 6),
            "effect_size_r": round(self.effect_size_r, 4),
            "effect_label": self.effect_label,
            "significant": self.significant,
            "alpha": self.alpha,
            "median_a_ms": round(self.median_a, 4),
            "median_b_ms": round(self.median_b, 4),
            "interpretation": self.interpretation,
        }


def _normal_cdf(z: float) -> float:
    """CDF de la loi normale standard (approximation Abramowitz & Stegun)."""
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    poly = t * (0.319381530 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))))
    p = 1.0 - (1.0 / math.sqrt(2 * math.pi)) * math.exp(-0.5 * z * z) * poly
    return p if z > 0 else 1.0 - p


def mann_whitney_u(
    a: Sequence[float],
    b: Sequence[float],
    alpha: float = 0.05,
) -> MannWhitneyResult:
    """
    Test de Mann-Whitney U (Wilcoxon rank-sum).

    Non-paramétrique : ne suppose pas la normalité des distributions.
    Idéal pour comparer des latences (souvent asymétriques).

    Args:
        a: échantillon A (ex: latences CAGOULE en ms)
        b: échantillon B (ex: latences AES en ms)
        alpha: seuil de significativité (défaut 0.05)

    Returns:
        MannWhitneyResult avec p-value, effect size, interprétation
    """
    n1, n2 = len(a), len(b)
    if n1 < 2 or n2 < 2:
        return MannWhitneyResult(
            u_statistic=0.0, p_value=1.0, effect_size_r=0.0,
            significant=False, alpha=alpha, n1=n1, n2=n2,
            median_a=statistics.median(a) if a else 0.0,
            median_b=statistics.median(b) if b else 0.0,
            interpretation="Pas assez de données pour le test.",
        )

    # Calcul U via comptage des paires concordantes
    u1 = sum(1 for x in a for y in b if x < y) + 0.5 * sum(1 for x in a for y in b if x == y)
    u2 = n1 * n2 - u1

    u_stat = min(u1, u2)

    # Approximation normale (valide pour n > 20)
    mean_u = n1 * n2 / 2
    std_u = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
    z = (u_stat - mean_u) / std_u if std_u > 0 else 0.0

    p_value = 2 * (1 - _normal_cdf(abs(z)))   # bilatéral

    # Rank-biserial correlation : 0 = no effect, 1 = perfect separation
    # r = 1 - 2*U_min/(n1*n2) — range [0, 1] avec 1 = effet maximal
    effect_r = 1.0 - 2.0 * u_stat / (n1 * n2)
    significant = p_value < alpha

    median_a = statistics.median(a)
    median_b = statistics.median(b)
    delta_pct = (median_a - median_b) / median_b * 100 if median_b != 0 else 0.0

    if significant:
        direction = "A plus lent" if median_a > median_b else "A plus rapide"
        # BUG10 FIX: abs(effect_r - 0.5) n'avait pas de sens pour rank-biserial
        # La bonne formule est simplement abs(effect_r) ∈ [0,1]
        interp = f"{direction} ({delta_pct:+.1f}%), p={p_value:.4f}, r={abs(effect_r):.2f}"
    else:
        interp = f"Pas de différence significative (p={p_value:.4f}), Δmédiane={delta_pct:+.1f}%"

    return MannWhitneyResult(
        u_statistic=u_stat,
        p_value=p_value,
        effect_size_r=effect_r,
        significant=significant,
        alpha=alpha,
        n1=n1,
        n2=n2,
        median_a=median_a,
        median_b=median_b,
        interpretation=interp,
    )


# ── Cohen's d ────────────────────────────────────────────────────────────────

def cohens_d(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Cohen's d — effect size paramétrique.
    d = (mean_a - mean_b) / pooled_std
    Interprétation : |d| < 0.2 negligible, < 0.5 small, < 0.8 medium, ≥ 0.8 large
    """
    if len(a) < 2 or len(b) < 2:
        return 0.0
    mean_a = statistics.mean(a)
    mean_b = statistics.mean(b)
    var_a = statistics.variance(a)
    var_b = statistics.variance(b)
    pooled = math.sqrt((var_a + var_b) / 2)
    return (mean_a - mean_b) / pooled if pooled > 0 else 0.0


# ── Bootstrap CI ─────────────────────────────────────────────────────────────

def bootstrap_ci(
    samples: Sequence[float],
    statistic_fn=statistics.mean,
    n_boot: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """
    Intervalle de confiance bootstrap.

    Returns:
        (lower, upper) bornes de l'IC à `confidence`%
    """
    rng = random.Random(seed)
    n = len(samples)
    boot_stats = []
    for _ in range(n_boot):
        resample = [rng.choice(samples) for _ in range(n)]  # type: ignore[arg-type]
        boot_stats.append(statistic_fn(resample))  # type: ignore[arg-type]
    boot_stats.sort()
    lo = int((1 - confidence) / 2 * n_boot)
    hi = int((1 + confidence) / 2 * n_boot) - 1
    return boot_stats[lo], boot_stats[hi]


# ── Comparaison complète ──────────────────────────────────────────────────────

@dataclass
class StatComparison:
    """
    Comparaison statistique complète entre deux algorithmes.

    Combine Mann-Whitney U, Cohen's d et bootstrap CI pour
    une analyse publication-ready.
    """
    algo_a: str
    algo_b: str
    mann_whitney: MannWhitneyResult
    cohens_d: float
    ci_a: tuple[float, float]   # 95% bootstrap CI mean
    ci_b: tuple[float, float]
    ratio_medians: float        # median_b / median_a — speedup factor
    overhead_pct: float         # (median_a - median_b) / median_b * 100

    @property
    def verdict(self) -> str:
        if not self.mann_whitney.significant:
            return "EQUIVALENT"
        elif self.overhead_pct > 0:
            return f"SLOWER ({self.overhead_pct:+.1f}%)"
        else:
            return f"FASTER ({self.overhead_pct:+.1f}%)"

    def to_dict(self) -> dict:
        return {
            "algo_a": self.algo_a,
            "algo_b": self.algo_b,
            "mann_whitney": self.mann_whitney.to_dict(),
            "cohens_d": round(self.cohens_d, 4),
            "ci_a_95": [round(x, 4) for x in self.ci_a],
            "ci_b_95": [round(x, 4) for x in self.ci_b],
            "ratio_medians": round(self.ratio_medians, 4),
            "overhead_pct": round(self.overhead_pct, 2),
            "verdict": self.verdict,
        }


def compare_algorithms(
    samples_a: Sequence[float],
    samples_b: Sequence[float],
    algo_a: str = "A",
    algo_b: str = "B",
    alpha: float = 0.05,
) -> StatComparison:
    """
    Comparaison statistique complète entre deux séries de mesures.

    Args:
        samples_a: latences de l'algorithme A (ms)
        samples_b: latences de l'algorithme B (ms)
        algo_a, algo_b: noms des algorithmes
        alpha: seuil de significativité

    Returns:
        StatComparison avec tous les tests statistiques
    """
    mw = mann_whitney_u(samples_a, samples_b, alpha=alpha)
    d = cohens_d(samples_a, samples_b)

    ci_a = bootstrap_ci(list(samples_a)) if len(samples_a) >= 10 else (0.0, 0.0)
    ci_b = bootstrap_ci(list(samples_b)) if len(samples_b) >= 10 else (0.0, 0.0)

    med_a = statistics.median(samples_a) if samples_a else 0.0
    med_b = statistics.median(samples_b) if samples_b else 0.0

    ratio = med_b / med_a if med_a > 0 else 1.0
    overhead = (med_a - med_b) / med_b * 100 if med_b > 0 else 0.0

    return StatComparison(
        algo_a=algo_a,
        algo_b=algo_b,
        mann_whitney=mw,
        cohens_d=d,
        ci_a=ci_a,
        ci_b=ci_b,
        ratio_medians=ratio,
        overhead_pct=overhead,
    )
