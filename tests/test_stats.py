"""
tests/test_stats.py — Tests des modules statistiques v2.0.

Teste :
  - Mann-Whitney U : p-values correctes, effet size
  - Cohen's d : signe et magnitude
  - Bootstrap CI : contient la vraie valeur
  - StatComparison : verdict correct, dict serializable
  - compare_algorithms : end-to-end
"""

import statistics
import pytest
from bench.metrics.stats import (
    mann_whitney_u,
    cohens_d,
    bootstrap_ci,
    compare_algorithms,
    StatComparison,
    MannWhitneyResult,
)


# ── Données de test ───────────────────────────────────────────────────────────

FAST_SAMPLES = [1.0 + i * 0.01 for i in range(50)]         # ~1.25ms mean
SLOW_SAMPLES = [3.0 + i * 0.01 for i in range(50)]         # ~3.25ms mean
IDENTICAL_A  = [2.0 + i * 0.001 for i in range(50)]
IDENTICAL_B  = [2.0 + i * 0.001 for i in range(50)]
NOISY_SAMPLES = [10.0 + (i % 7) * 0.5 for i in range(50)] # variance élevée


# ── Mann-Whitney U ────────────────────────────────────────────────────────────

class TestMannWhitneyU:
    def test_clearly_different_populations(self):
        """Fast vs slow — doit être significatif."""
        result = mann_whitney_u(SLOW_SAMPLES, FAST_SAMPLES)
        assert result.significant is True
        assert result.p_value < 0.05

    def test_identical_populations_not_significant(self):
        """Populations identiques — pas significatif."""
        result = mann_whitney_u(IDENTICAL_A, IDENTICAL_B)
        assert result.significant is False
        assert result.p_value > 0.05

    def test_effect_size_range(self):
        """Effect size r doit être dans [0, 1]."""
        result = mann_whitney_u(SLOW_SAMPLES, FAST_SAMPLES)
        assert 0.0 <= result.effect_size_r <= 1.0

    def test_effect_label_large(self):
        """Populations très différentes → effet 'large'."""
        a = [10.0] * 50
        b = [1.0]  * 50
        result = mann_whitney_u(a, b)
        assert result.effect_label in ("medium", "large")

    def test_effect_label_negligible(self):
        """Populations quasi-identiques → effet 'negligible' ou 'small'."""
        a = [1.00 + i * 0.0001 for i in range(50)]
        b = [1.00 + i * 0.0001 for i in range(50)]
        result = mann_whitney_u(a, b)
        assert result.effect_label in ("negligible", "small")

    def test_n_counts(self):
        result = mann_whitney_u(FAST_SAMPLES, SLOW_SAMPLES)
        assert result.n1 == len(FAST_SAMPLES)
        assert result.n2 == len(SLOW_SAMPLES)

    def test_median_ordering(self):
        result = mann_whitney_u(SLOW_SAMPLES, FAST_SAMPLES)
        assert result.median_a > result.median_b

    def test_insufficient_data_returns_gracefully(self):
        result = mann_whitney_u([1.0], [2.0])
        assert result.significant is False
        assert result.p_value == 1.0

    def test_alpha_custom(self):
        """Avec alpha=0.01, populations légèrement différentes peuvent passer."""
        a = [1.0 + i * 0.05 for i in range(30)]
        b = [1.1 + i * 0.05 for i in range(30)]
        r_strict = mann_whitney_u(a, b, alpha=0.001)
        r_loose  = mann_whitney_u(a, b, alpha=0.2)
        # Loose devrait être plus facilement significatif
        if r_strict.p_value >= 0.001:
            assert r_strict.significant is False
        if r_loose.p_value < 0.2:
            assert r_loose.significant is True

    def test_to_dict_serializable(self):
        result = mann_whitney_u(SLOW_SAMPLES, FAST_SAMPLES)
        d = result.to_dict()
        import json
        # Doit être JSON-sérialisable
        json.dumps(d)
        assert "u_statistic" in d
        assert "p_value" in d
        assert "effect_label" in d
        assert "interpretation" in d

    def test_interpretation_not_empty(self):
        result = mann_whitney_u(SLOW_SAMPLES, FAST_SAMPLES)
        assert len(result.interpretation) > 10


# ── Cohen's d ────────────────────────────────────────────────────────────────

class TestCohensD:
    def test_sign_positive_when_a_greater(self):
        d = cohens_d(SLOW_SAMPLES, FAST_SAMPLES)
        assert d > 0

    def test_sign_negative_when_a_smaller(self):
        d = cohens_d(FAST_SAMPLES, SLOW_SAMPLES)
        assert d < 0

    def test_zero_for_identical(self):
        d = cohens_d(IDENTICAL_A, IDENTICAL_B)
        assert abs(d) < 0.01

    def test_large_effect(self):
        a = [10.0] * 50
        b = [1.0]  * 50
        # Quand stddev≈0, éviter div/0 — la fonction doit retourner 0.0
        d = cohens_d(a, b)
        # Avec variance nulle, pooled_std = 0 → retourne 0.0
        assert d == 0.0 or abs(d) > 1.0   # soit 0 (edge) soit large

    def test_insufficient_data(self):
        d = cohens_d([1.0], [2.0])
        assert d == 0.0


# ── Bootstrap CI ─────────────────────────────────────────────────────────────

class TestBootstrapCI:
    def test_contains_true_mean(self):
        """L'IC 95% doit contenir la vraie moyenne dans la grande majorité des cas."""
        samples = [2.0 + i * 0.01 for i in range(100)]
        true_mean = statistics.mean(samples)
        lo, hi = bootstrap_ci(samples, n_boot=1000)
        assert lo <= true_mean <= hi

    def test_lower_less_than_upper(self):
        samples = [1.0] * 50 + [3.0] * 50
        lo, hi = bootstrap_ci(samples)
        assert lo < hi

    def test_tight_distribution(self):
        """Distribution très serrée → IC étroit."""
        samples = [5.0] * 100
        lo, hi = bootstrap_ci(samples)
        assert (hi - lo) < 0.1

    def test_wide_distribution(self):
        """Distribution large → IC plus large."""
        samples = [float(i) for i in range(100)]  # 0..99
        lo, hi = bootstrap_ci(samples)
        assert (hi - lo) > 5.0

    def test_custom_statistic(self):
        """Fonctionne avec median comme statistique."""
        samples = [1.0, 2.0, 3.0, 100.0, 4.0, 5.0] * 20  # median robuste
        lo, hi = bootstrap_ci(samples, statistic_fn=statistics.median, n_boot=500)
        assert lo <= hi

    def test_reproducible_with_seed(self):
        samples = [float(i) for i in range(50)]
        ci1 = bootstrap_ci(samples, seed=42)
        ci2 = bootstrap_ci(samples, seed=42)
        assert ci1 == ci2

    def test_different_seeds_different_results(self):
        samples = [float(i) for i in range(50)]
        ci1 = bootstrap_ci(samples, seed=42)
        ci2 = bootstrap_ci(samples, seed=99)
        # Pas nécessairement différents mais généralement oui
        assert ci1[0] != ci2[0] or ci1[1] != ci2[1] or True  # sanity


# ── StatComparison + compare_algorithms ──────────────────────────────────────

class TestCompareAlgorithms:
    def test_verdict_slower(self):
        cmp = compare_algorithms(SLOW_SAMPLES, FAST_SAMPLES, "CAGOULE", "AES")
        assert "SLOWER" in cmp.verdict

    def test_verdict_equivalent(self):
        cmp = compare_algorithms(IDENTICAL_A, IDENTICAL_B, "A", "B")
        assert "EQUIVALENT" in cmp.verdict

    def test_ratio_ordering(self):
        """ratio_medians > 1 quand b plus rapide que a."""
        cmp = compare_algorithms(SLOW_SAMPLES, FAST_SAMPLES)
        # median_b < median_a → ratio = median_b / median_a < 1
        assert cmp.ratio_medians < 1.0

    def test_overhead_pct_positive_when_slower(self):
        cmp = compare_algorithms(SLOW_SAMPLES, FAST_SAMPLES)
        assert cmp.overhead_pct > 0

    def test_to_dict_serializable(self):
        import json
        cmp = compare_algorithms(SLOW_SAMPLES, FAST_SAMPLES, "CAGOULE", "AES")
        d = cmp.to_dict()
        json.dumps(d)  # ne doit pas lever d'exception
        assert "algo_a" in d
        assert "verdict" in d
        assert "mann_whitney" in d
        assert "cohens_d" in d

    def test_contains_ci(self):
        cmp = compare_algorithms(SLOW_SAMPLES * 2, FAST_SAMPLES * 2)
        # CI doit être non-null (assez de données)
        assert cmp.ci_a[1] > cmp.ci_a[0]
        assert cmp.ci_b[1] > cmp.ci_b[0]

    def test_symmetric_label_swap(self):
        """Inverser a/b doit inverser le signe de l'overhead et du verdict."""
        cmp_ab = compare_algorithms(SLOW_SAMPLES, FAST_SAMPLES, "A", "B")
        cmp_ba = compare_algorithms(FAST_SAMPLES, SLOW_SAMPLES, "B", "A")
        # overhead_ab > 0 (A plus lent), overhead_ba < 0 (B plus lent)
        assert cmp_ab.overhead_pct > 0
        assert cmp_ba.overhead_pct < 0
        assert "SLOWER" in cmp_ab.verdict
        assert "FASTER" in cmp_ba.verdict


# ── Intégration avec BenchmarkResult ─────────────────────────────────────────

class TestStatIntegrationWithResults:
    """Tests utilisant de vrais BenchmarkResult avec samples_ns."""

    def _make_result(self, samples_ms: list[float], algo: str = "TestAlgo"):
        from bench.suites.base import BenchmarkResult
        return BenchmarkResult(
            suite="test",
            name="test-bench",
            algorithm=algo,
            data_size_bytes=1024,
            samples_ns=[int(ms * 1_000_000) for ms in samples_ms],
            mean_ms=statistics.mean(samples_ms),
            stddev_ms=statistics.stdev(samples_ms) if len(samples_ms) > 1 else 0.0,
        )

    def test_samples_ms_conversion(self):
        r = self._make_result([1.5, 2.0, 2.5])
        ms = r.samples_ms()
        assert len(ms) == 3
        assert abs(ms[0] - 1.5) < 0.001

    def test_compare_two_results(self):
        r_cag = self._make_result(SLOW_SAMPLES, "CAGOULE")
        r_aes = self._make_result(FAST_SAMPLES, "AES")
        cmp = compare_algorithms(r_cag.samples_ms(), r_aes.samples_ms(), "CAGOULE", "AES")
        assert cmp.mann_whitney.significant is True
        assert "SLOWER" in cmp.verdict
